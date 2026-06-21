"""
DIAMOR — governed candidate intake operation.

ingest_candidate() is the single governed entry point that turns a raw intake
submission into a canonical Candidate, inside ONE transaction:

  validate + normalize -> resolve identity (create-or-match) -> capture consent
  -> emit audit events -> record the submission envelope

Privacy ordering: validation (including the explicit-consent check) runs BEFORE
any PII is persisted. An invalid or non-consented attempt rolls back and leaves
NOTHING — no candidate, no consent, no submission, no audit event.

Scope: service only. The HTTP/DRF endpoint and Telegram-verified identity wiring
are later steps. For now actor_type/actor_id are supplied by the caller so audit
and consent record a real acting identity. Bitrix is intentionally untouched.
"""
from dataclasses import dataclass
from typing import Optional

from django.db import transaction
from django.utils import timezone

from audit.chain import append_event
from audit.models import AuditEventType
from intake.models import (
    ActorType,
    Candidate,
    Channel,
    ConsentRecord,
    ConsentVersion,
    DuplicateReviewState,
    IdentityMatchReview,
    IntakeSubmission,
    LifecycleStage,
    MatchReviewState,
    ProcessingStatus,
)
from intake.validators import (
    IntakeValidationError,
    clean_text,
    coerce_telegram_id,
    normalize_country,
    normalize_language,
    normalize_phone,
    parse_date_of_birth,
)


@dataclass
class IngestResult:
    outcome: str                       # "created" | "matched" | "duplicate"
    candidate_id: Optional[str]
    submission_id: Optional[str]
    created: bool
    consent_id: Optional[str] = None
    review_id: Optional[str] = None


def _validate(payload):
    consent_block = payload.get("consent") or {}
    if consent_block.get("granted") is not True:
        raise IntakeValidationError("consent", "Explicit consent is required before intake.")

    preferred_language = normalize_language(payload.get("preferred_language"))
    full_name = clean_text(payload.get("full_name"), "full_name", 200)
    citizenship = normalize_country(payload.get("citizenship"), "citizenship")
    current_country = normalize_country(payload.get("current_country"), "current_country")
    desired_country = normalize_country(payload.get("desired_country"), "desired_country")
    # Dialing region for phone parsing: where the candidate is, then citizenship.
    default_region = current_country or citizenship
    phone_e164 = normalize_phone(payload.get("phone"), default_region)
    date_of_birth = parse_date_of_birth(payload.get("date_of_birth"))
    profession = clean_text(payload.get("profession"), "profession", 120, required=False)
    telegram_id = coerce_telegram_id(payload.get("telegram_id"))
    telegram_username = clean_text(
        payload.get("telegram_username"), "telegram_username", 64, required=False
    )

    return {
        "preferred_language": preferred_language,
        "full_name": full_name,
        "citizenship": citizenship,
        "current_country": current_country,
        "desired_country": desired_country,
        "phone_e164": phone_e164,
        "date_of_birth": date_of_birth,
        "profession": profession,
        "telegram_id": telegram_id,
        "telegram_username": telegram_username,
        "consent_evidence": consent_block.get("evidence") or {},
    }


def _active_consent_version(locale):
    cv = ConsentVersion.objects.filter(locale=locale, is_active=True).first()
    if cv is None:
        raise IntakeValidationError("consent", f"No active consent version for locale '{locale}'.")
    return cv


def _resolve_identity(v, channel):
    """Create-or-match the canonical candidate. Returns (candidate, created, review).

    telegram_id is the strong per-account key. An ambiguous phone-only collision
    (a DIFFERENT candidate already on this phone) is flagged for operator review,
    never auto-merged.
    """
    telegram_id = v["telegram_id"]

    if telegram_id is not None:
        match = (
            Candidate.objects.select_for_update()
            .filter(telegram_id=telegram_id)
            .first()
        )
        if match is not None:
            # Returning candidate. v1 policy: no silent overwrite of stored fields;
            # the field-update policy is a separate, later decision.
            return match, False, None

    phone_qs = Candidate.objects.filter(phone_e164=v["phone_e164"])
    if telegram_id is not None:
        phone_qs = phone_qs.exclude(telegram_id=telegram_id)
    ambiguous_against = phone_qs.first()

    candidate = Candidate.objects.create(
        lifecycle_stage=LifecycleStage.INTAKE,
        source_channel=channel,
        preferred_language=v["preferred_language"],
        telegram_id=telegram_id,
        telegram_username=v["telegram_username"],
        phone_e164=v["phone_e164"],
        full_name=v["full_name"],
        citizenship_iso=v["citizenship"],
        current_country_iso=v["current_country"],
        desired_country_iso=v["desired_country"],
        date_of_birth=v["date_of_birth"],
        profession=v["profession"],
        duplicate_review_state=(
            DuplicateReviewState.PENDING_REVIEW
            if ambiguous_against is not None
            else DuplicateReviewState.CLEAR
        ),
    )

    review = None
    if ambiguous_against is not None:
        review = IdentityMatchReview.objects.create(
            candidate=candidate,
            matched_against=ambiguous_against,
            reason=f"Phone already linked to candidate {ambiguous_against.id}",
            state=MatchReviewState.OPEN,
        )

    return candidate, True, review


@transaction.atomic
def ingest_candidate(*, payload, idempotency_key, channel, actor_type, actor_id):
    if channel not in Channel.values:
        raise ValueError(f"Unknown channel '{channel}'.")
    if actor_type not in ActorType.values:
        raise ValueError(f"Unknown actor_type '{actor_type}'.")
    if not idempotency_key:
        raise ValueError("idempotency_key is required.")

    # Idempotency: a prior committed submission with this key returns its result.
    prior = IntakeSubmission.objects.filter(idempotency_key=idempotency_key).first()
    if prior is not None:
        return IngestResult(
            outcome="duplicate",
            candidate_id=str(prior.candidate_id) if prior.candidate_id else None,
            submission_id=str(prior.id),
            created=False,
        )

    # Validate FIRST — nothing persists for an invalid or non-consented attempt.
    v = _validate(payload)
    consent_version = _active_consent_version(v["preferred_language"])

    # Record the submission envelope (payload now validated and consented).
    submission = IntakeSubmission.objects.create(
        idempotency_key=idempotency_key,
        channel=channel,
        raw_payload=payload,
        processing_status=ProcessingStatus.VALIDATED,
    )

    candidate, created, review = _resolve_identity(v, channel)

    now = timezone.now()
    consent = ConsentRecord.objects.create(
        candidate=candidate,
        consent_version=consent_version,
        granted_at=now,
        channel=channel,
        locale_shown=consent_version.locale,
        actor_type=actor_type,
        actor_id=actor_id,
        evidence=v["consent_evidence"],
    )

    # Audit events — each inside this same transaction (atomic with the writes above).
    append_event(
        event_type=AuditEventType.INTAKE_SUBMITTED.value,
        actor_type=actor_type,
        actor_id=actor_id,
        subject_type="candidate",
        subject_id=str(candidate.id),
        source=channel,
        correlation_id=idempotency_key,
        payload={"submission_id": str(submission.id)},
    )
    append_event(
        event_type=(
            AuditEventType.CANDIDATE_CREATED.value
            if created
            else AuditEventType.CANDIDATE_MATCHED.value
        ),
        actor_type=actor_type,
        actor_id=actor_id,
        subject_type="candidate",
        subject_id=str(candidate.id),
        source=channel,
        correlation_id=idempotency_key,
        payload={"source_channel": channel, "lifecycle_stage": str(candidate.lifecycle_stage)},
    )
    append_event(
        event_type=AuditEventType.CONSENT_GRANTED.value,
        actor_type=actor_type,
        actor_id=actor_id,
        subject_type="consent_record",
        subject_id=str(consent.id),
        source=channel,
        correlation_id=idempotency_key,
        payload={
            "consent_version": consent_version.version,
            "locale": consent_version.locale,
            "lawful_basis": str(consent_version.lawful_basis),
        },
    )
    if review is not None:
        append_event(
            event_type=AuditEventType.IDENTITY_REVIEW_FLAGGED.value,
            actor_type=actor_type,
            actor_id=actor_id,
            subject_type="identity_match_review",
            subject_id=str(review.id),
            source=channel,
            correlation_id=idempotency_key,
            payload={"matched_against": str(review.matched_against_id)},
        )

    submission.candidate = candidate
    submission.processing_status = ProcessingStatus.COMPLETED
    submission.save(update_fields=["candidate", "processing_status"])

    return IngestResult(
        outcome="created" if created else "matched",
        candidate_id=str(candidate.id),
        submission_id=str(submission.id),
        created=created,
        consent_id=str(consent.id),
        review_id=str(review.id) if review is not None else None,
    )
