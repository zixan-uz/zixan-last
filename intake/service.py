"""
DIAMOR — governed candidate intake operation (omnichannel).

ingest_candidate() turns a raw intake submission into a canonical Candidate plus
one or more CandidateChannelIdentity rows, inside ONE transaction:

  validate profile + identifiers + consent -> resolve identity (create + attach,
  or flag cross-candidate collision) -> capture consent -> emit audit events ->
  record the submission envelope

Identity policy (DEC-IDENTITY-001 + Revision A), interim state (all inbound
identifiers unverified):
  - No presented identifier matches any existing candidate -> create a new
    candidate and attach all identifiers (unverified/self_asserted).
  - A presented identifier already belongs to another candidate -> create a new
    candidate, attach identifiers, and raise IdentityMatchReview against each
    matched candidate. Never auto-attach to, or merge with, the existing one.
  - Operator-managed attach-to-existing and verification promotion are a later,
    separate step; the model supports them already.

Privacy ordering: validation (incl. the explicit-consent check) runs BEFORE any
PII is persisted. An invalid/non-consented attempt rolls back, persisting nothing.
"""
from dataclasses import dataclass, field
from typing import List, Optional

from django.db import transaction
from django.utils import timezone

from audit.chain import append_event
from audit.models import AuditEventType
from intake.models import (
    ActorType,
    Candidate,
    CandidateChannelIdentity,
    Channel,
    ConsentRecord,
    ConsentVersion,
    DuplicateReviewState,
    IdentifierType,
    IdentityMatchReview,
    IdentityStatus,
    IntakeSubmission,
    LifecycleStage,
    MatchReviewState,
    ProcessingStatus,
    VerificationMethod,
)
from intake.validators import (
    IntakeValidationError,
    clean_text,
    normalize_country,
    normalize_identifier_value,
    normalize_language,
    parse_date_of_birth,
)


@dataclass
class IngestResult:
    outcome: str                       # "created" | "duplicate"
    candidate_id: Optional[str]
    submission_id: Optional[str]
    created: bool
    consent_id: Optional[str] = None
    identity_count: int = 0
    review_ids: List[str] = field(default_factory=list)


def _validate_profile(payload):
    consent_block = payload.get("consent") or {}
    if consent_block.get("granted") is not True:
        raise IntakeValidationError("consent", "Explicit consent is required before intake.")

    return {
        "preferred_language": normalize_language(payload.get("preferred_language")),
        "full_name": clean_text(payload.get("full_name"), "full_name", 200),
        "citizenship": normalize_country(payload.get("citizenship"), "citizenship"),
        "current_country": normalize_country(payload.get("current_country"), "current_country"),
        "desired_country": normalize_country(payload.get("desired_country"), "desired_country"),
        "date_of_birth": parse_date_of_birth(payload.get("date_of_birth")),
        "profession": clean_text(payload.get("profession"), "profession", 120, required=False),
        "consent_evidence": consent_block.get("evidence") or {},
    }


def _validate_identifiers(identifiers_raw, default_region):
    if not identifiers_raw:
        raise IntakeValidationError("identifiers", "At least one identifier is required.")

    seen = set()
    out = []
    for idx, item in enumerate(identifiers_raw):
        position = idx + 1
        channel = str(item.get("channel") or "").strip()
        if channel not in Channel.values:
            raise IntakeValidationError(
                "identifiers", f"Unknown channel '{channel}' in identifier #{position}."
            )
        itype = str(item.get("identifier_type") or "").strip()
        if itype not in IdentifierType.values:
            raise IntakeValidationError(
                "identifiers", f"Unknown identifier_type '{itype}' in identifier #{position}."
            )
        value = normalize_identifier_value(itype, item.get("identifier_value"), default_region)

        key = (itype, value)
        if key in seen:
            continue  # dedup exact duplicates within the same request
        seen.add(key)
        out.append({
            "channel": channel,
            "identifier_type": itype,
            "identifier_value": value,
            "source_attribution": item.get("source_attribution") or {},
        })

    if not out:
        raise IntakeValidationError("identifiers", "At least one valid identifier is required.")
    return out


def _active_consent_version(locale):
    cv = ConsentVersion.objects.filter(locale=locale, is_active=True).first()
    if cv is None:
        raise IntakeValidationError("consent", f"No active consent version for locale '{locale}'.")
    return cv


def _resolve_identity(profile, identifiers, channel):
    """Create a new candidate, attach the presented identifiers (unverified), and
    raise an IdentityMatchReview for each existing candidate that already owns one
    of those identifiers. Returns (candidate, created, added_identities, reviews)."""
    matched_candidate_ids = set()
    for ident in identifiers:
        owner_ids = CandidateChannelIdentity.objects.filter(
            identifier_type=ident["identifier_type"],
            identifier_value=ident["identifier_value"],
            status=IdentityStatus.ACTIVE,
        ).values_list("candidate_id", flat=True)
        matched_candidate_ids.update(owner_ids)

    has_collision = len(matched_candidate_ids) > 0

    candidate = Candidate.objects.create(
        lifecycle_stage=LifecycleStage.INTAKE,
        source_channel=channel,
        preferred_language=profile["preferred_language"],
        full_name=profile["full_name"],
        citizenship_iso=profile["citizenship"],
        current_country_iso=profile["current_country"],
        desired_country_iso=profile["desired_country"],
        date_of_birth=profile["date_of_birth"],
        profession=profile["profession"],
        duplicate_review_state=(
            DuplicateReviewState.PENDING_REVIEW if has_collision else DuplicateReviewState.CLEAR
        ),
    )

    added_identities = []
    for ident in identifiers:
        cci = CandidateChannelIdentity.objects.create(
            candidate=candidate,
            channel=ident["channel"],
            identifier_type=ident["identifier_type"],
            identifier_value=ident["identifier_value"],
            is_verified=False,
            verification_method=VerificationMethod.SELF_ASSERTED,
            source_attribution=ident["source_attribution"],
            status=IdentityStatus.ACTIVE,
        )
        added_identities.append(cci)

    reviews = []
    for existing_id in matched_candidate_ids:
        review = IdentityMatchReview.objects.create(
            candidate=candidate,
            matched_against_id=existing_id,
            reason="Presented identifier already associated with another candidate.",
            state=MatchReviewState.OPEN,
        )
        reviews.append(review)

    return candidate, True, added_identities, reviews


@transaction.atomic
def ingest_candidate(*, payload, identifiers, idempotency_key, channel, actor_type, actor_id):
    if channel not in Channel.values:
        raise ValueError(f"Unknown channel '{channel}'.")
    if actor_type not in ActorType.values:
        raise ValueError(f"Unknown actor_type '{actor_type}'.")
    if not idempotency_key:
        raise ValueError("idempotency_key is required.")

    prior = IntakeSubmission.objects.filter(idempotency_key=idempotency_key).first()
    if prior is not None:
        return IngestResult(
            outcome="duplicate",
            candidate_id=str(prior.candidate_id) if prior.candidate_id else None,
            submission_id=str(prior.id),
            created=False,
        )

    # Validate FIRST — nothing persists for an invalid or non-consented attempt.
    profile = _validate_profile(payload)
    norm_identifiers = _validate_identifiers(identifiers, default_region=profile["current_country"])
    consent_version = _active_consent_version(profile["preferred_language"])

    submission = IntakeSubmission.objects.create(
        idempotency_key=idempotency_key,
        channel=channel,
        raw_payload={"candidate": payload, "identifiers": identifiers},
        processing_status=ProcessingStatus.VALIDATED,
    )

    candidate, created, added_identities, reviews = _resolve_identity(
        profile, norm_identifiers, channel
    )

    now = timezone.now()
    consent = ConsentRecord.objects.create(
        candidate=candidate,
        consent_version=consent_version,
        granted_at=now,
        channel=channel,
        locale_shown=consent_version.locale,
        actor_type=actor_type,
        actor_id=actor_id,
        evidence=profile["consent_evidence"],
    )

    # Audit — each inside this transaction (atomic with the writes above).
    append_event(
        event_type=AuditEventType.INTAKE_SUBMITTED.value,
        actor_type=actor_type, actor_id=actor_id,
        subject_type="candidate", subject_id=str(candidate.id),
        source=channel, correlation_id=idempotency_key,
        payload={"submission_id": str(submission.id)},
    )
    append_event(
        event_type=AuditEventType.CANDIDATE_CREATED.value,
        actor_type=actor_type, actor_id=actor_id,
        subject_type="candidate", subject_id=str(candidate.id),
        source=channel, correlation_id=idempotency_key,
        payload={"source_channel": channel, "lifecycle_stage": str(candidate.lifecycle_stage)},
    )
    for cci in added_identities:
        append_event(
            event_type=AuditEventType.CHANNEL_IDENTITY_ADDED.value,
            actor_type=actor_type, actor_id=actor_id,
            subject_type="channel_identity", subject_id=str(cci.id),
            source=channel, correlation_id=idempotency_key,
            payload={
                "channel": str(cci.channel),
                "identifier_type": str(cci.identifier_type),
                "is_verified": cci.is_verified,
            },
        )
    append_event(
        event_type=AuditEventType.CONSENT_GRANTED.value,
        actor_type=actor_type, actor_id=actor_id,
        subject_type="consent_record", subject_id=str(consent.id),
        source=channel, correlation_id=idempotency_key,
        payload={
            "consent_version": consent_version.version,
            "locale": consent_version.locale,
            "lawful_basis": str(consent_version.lawful_basis),
        },
    )
    for review in reviews:
        append_event(
            event_type=AuditEventType.IDENTITY_REVIEW_FLAGGED.value,
            actor_type=actor_type, actor_id=actor_id,
            subject_type="identity_match_review", subject_id=str(review.id),
            source=channel, correlation_id=idempotency_key,
            payload={"matched_against": str(review.matched_against_id)},
        )

    submission.candidate = candidate
    submission.processing_status = ProcessingStatus.COMPLETED
    submission.save(update_fields=["candidate", "processing_status"])

    return IngestResult(
        outcome="created",
        candidate_id=str(candidate.id),
        submission_id=str(submission.id),
        created=True,
        consent_id=str(consent.id),
        identity_count=len(added_identities),
        review_ids=[str(r.id) for r in reviews],
    )
