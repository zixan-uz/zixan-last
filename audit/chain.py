"""
DIAMOR — audit chain primitive (DEC-AUDIT-001, Option B).

This module is the SOLE writer of audit.AuditEvent. It serializes appends by
taking a row lock (SELECT ... FOR UPDATE) on the single AuditChainHead row, so
concurrent appends cannot fork the chain. The audit event is inserted INSIDE the
caller's transaction, so it commits or rolls back atomically with the
operational write it records.

Hash: SHA-256 over a deterministic JSON serialization (fixed field set, sorted
keys, UTF-8, compact separators) of:
    sequence, event_type, actor_type, actor_id, subject_type, subject_id,
    occurred_at (ISO-8601, UTC), source, correlation_id, payload, prev_hash

NOTE on payload: keep payload values to JSON-safe primitives (str, int, bool,
None, and nested dicts/lists of those). Avoid floats — jsonb round-tripping can
alter float representation and would break hash verification. Audit payloads are
minimized (ids, types, counts), so this is not a practical limitation.
"""
import hashlib
import json
from datetime import datetime, timezone

from django.db import transaction

from audit.models import AuditChainHead, AuditEvent

CHAIN_HEAD_ID = 1
GENESIS_PREV_HASH = None  # genesis last_hash is NULL; first event's prev_hash is None


def _iso_utc(dt):
    """Canonical ISO-8601 string in UTC. Naive datetimes are treated as UTC."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _compute_hash(*, sequence, event_type, actor_type, actor_id, subject_type,
                  subject_id, occurred_at_iso, source, correlation_id, payload,
                  prev_hash):
    doc = {
        "sequence": sequence,
        "event_type": event_type,
        "actor_type": actor_type,
        "actor_id": actor_id,
        "subject_type": subject_type,
        "subject_id": subject_id,
        "occurred_at": occurred_at_iso,
        "source": source,
        "correlation_id": correlation_id,
        "payload": payload,
        "prev_hash": prev_hash,
    }
    canonical = json.dumps(
        doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def append_event(*, event_type, actor_type, actor_id, subject_type, subject_id,
                 source, correlation_id, payload=None, occurred_at=None):
    """Append one event to the audit chain and return the created AuditEvent.

    MUST be called inside transaction.atomic() (the caller's transaction), so the
    audit record commits atomically with the operational write it records.
    """
    conn = transaction.get_connection()  # 'default' — where audit + intake live
    if not conn.in_atomic_block:
        raise RuntimeError(
            "append_event() must run inside transaction.atomic() so the audit "
            "record commits atomically with the operational write it records."
        )

    payload = payload if payload is not None else {}
    occurred_at = occurred_at if occurred_at is not None else datetime.now(timezone.utc)
    occurred_at_iso = _iso_utc(occurred_at)

    # Serialize appends: lock the single chain-head row for the rest of the txn.
    head = AuditChainHead.objects.select_for_update().get(pk=CHAIN_HEAD_ID)

    sequence = head.last_sequence + 1
    prev_hash = head.last_hash  # None for the first real event (genesis)

    digest = _compute_hash(
        sequence=sequence,
        event_type=event_type,
        actor_type=actor_type,
        actor_id=actor_id,
        subject_type=subject_type,
        subject_id=subject_id,
        occurred_at_iso=occurred_at_iso,
        source=source,
        correlation_id=correlation_id,
        payload=payload,
        prev_hash=prev_hash,
    )

    event = AuditEvent.objects.create(
        sequence=sequence,
        event_type=event_type,
        actor_type=actor_type,
        actor_id=actor_id,
        subject_type=subject_type,
        subject_id=subject_id,
        occurred_at=occurred_at,
        source=source,
        correlation_id=correlation_id,
        payload=payload,
        prev_hash=prev_hash,
        hash=digest,
    )

    head.last_sequence = sequence
    head.last_hash = digest
    head.save(update_fields=["last_sequence", "last_hash", "updated_at"])

    return event


def verify_chain():
    """Read-only tamper-evidence check.

    Walks every event in sequence order, recomputes each hash, confirms each
    prev_hash links to its predecessor, and confirms the chain-head matches the
    actual tail. Returns a dict: {"ok": True, "count": N, "head_sequence": S} on
    success, or {"ok": False, "error": ..., "at": seq} at the first break.
    """
    events = list(AuditEvent.objects.order_by("sequence"))

    expected_prev = GENESIS_PREV_HASH
    expected_seq = 1
    for ev in events:
        if ev.sequence != expected_seq:
            return {"ok": False, "error": "sequence_gap",
                    "at": ev.sequence, "expected": expected_seq}
        if ev.prev_hash != expected_prev:
            return {"ok": False, "error": "prev_hash_mismatch", "at": ev.sequence}
        recomputed = _compute_hash(
            sequence=ev.sequence,
            event_type=ev.event_type,
            actor_type=ev.actor_type,
            actor_id=ev.actor_id,
            subject_type=ev.subject_type,
            subject_id=ev.subject_id,
            occurred_at_iso=_iso_utc(ev.occurred_at),
            source=ev.source,
            correlation_id=ev.correlation_id,
            payload=ev.payload,
            prev_hash=ev.prev_hash,
        )
        if recomputed != ev.hash:
            return {"ok": False, "error": "hash_mismatch", "at": ev.sequence}
        expected_prev = ev.hash
        expected_seq += 1

    head = AuditChainHead.objects.get(pk=CHAIN_HEAD_ID)
    if events:
        tail = events[-1]
        if head.last_sequence != tail.sequence or head.last_hash != tail.hash:
            return {"ok": False, "error": "head_mismatch",
                    "head_sequence": head.last_sequence,
                    "tail_sequence": tail.sequence}
    else:
        if head.last_sequence != 0 or head.last_hash is not None:
            return {"ok": False, "error": "genesis_head_invalid",
                    "head_sequence": head.last_sequence}

    return {"ok": True, "count": len(events), "head_sequence": head.last_sequence}
