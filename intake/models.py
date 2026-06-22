"""
DIAMOR — intake domain models.

Candidate is PROFILE-ONLY. All channel identifiers live in
CandidateChannelIdentity (one row per identifier ever seen), per DEC-IDENTITY-001.
Identity resolution is centralized in intake.service under a conservative policy:
verified identifiers are strong keys; unverified identifiers are signals that
trigger manual review on cross-candidate collision; profiles are never
auto-merged.

Per-field data-tier classification:
  T0 public/operational | T1 internal | T2 personal | T3 sensitive personal
"""
import uuid

from django.db import models
from django.db.models import Q


class LifecycleStage(models.TextChoices):
    INTAKE = "intake", "Intake"
    SCREENING = "screening", "Screening"
    MATCHING = "matching", "Matching"
    OFFER = "offer", "Offer"
    DOCUMENTS = "documents", "Documents"
    VISA = "visa", "Visa"
    TRAVEL = "travel", "Travel"
    ARRIVAL = "arrival", "Arrival"
    POST_ARRIVAL = "post_arrival", "Post-arrival"
    RE_EMPLOYMENT = "re_employment", "Re-employment"


class DuplicateReviewState(models.TextChoices):
    CLEAR = "clear", "Clear"
    PENDING_REVIEW = "pending_review", "Pending review"
    MERGED = "merged", "Merged"
    REJECTED = "rejected", "Rejected as duplicate"


class LawfulBasis(models.TextChoices):
    CONSENT = "consent", "Consent (GDPR Art. 6(1)(a))"
    CONTRACT = "contract", "Contract (Art. 6(1)(b))"
    LEGAL_OBLIGATION = "legal_obligation", "Legal obligation (Art. 6(1)(c))"
    VITAL_INTERESTS = "vital_interests", "Vital interests (Art. 6(1)(d))"
    PUBLIC_TASK = "public_task", "Public task (Art. 6(1)(e))"
    LEGITIMATE_INTERESTS = "legitimate_interests", "Legitimate interests (Art. 6(1)(f))"


class Channel(models.TextChoices):
    TELEGRAM = "telegram", "Telegram"
    WHATSAPP = "whatsapp", "WhatsApp"
    INSTAGRAM = "instagram", "Instagram"
    INSTAGRAM_COMMENT = "instagram_comment", "Instagram comment"
    WEBSITE = "website", "Website"
    PHONE = "phone", "Phone"
    EMAIL = "email", "Email"
    OPERATOR = "operator", "Operator (manual)"


class ActorType(models.TextChoices):
    CANDIDATE = "candidate", "Candidate"
    OPERATOR = "operator", "Operator"
    SYSTEM = "system", "System"


class ProcessingStatus(models.TextChoices):
    RECEIVED = "received", "Received"
    VALIDATED = "validated", "Validated"
    REJECTED = "rejected", "Rejected"
    COMPLETED = "completed", "Completed"
    FAILED = "failed", "Failed"


class MatchReviewState(models.TextChoices):
    OPEN = "open", "Open"
    RESOLVED_MERGED = "resolved_merged", "Resolved — merged"
    RESOLVED_DISTINCT = "resolved_distinct", "Resolved — distinct"


class IdentifierType(models.TextChoices):
    TELEGRAM_ID = "telegram_id", "Telegram ID"
    TELEGRAM_USERNAME = "telegram_username", "Telegram username"
    PHONE_E164 = "phone_e164", "Phone (E.164)"
    WHATSAPP_ID = "whatsapp_id", "WhatsApp ID"
    INSTAGRAM_USER_ID = "instagram_user_id", "Instagram user ID"
    INSTAGRAM_USERNAME = "instagram_username", "Instagram username"
    EMAIL = "email", "Email"
    WEBSITE_SESSION = "website_session", "Website session"


class VerificationMethod(models.TextChoices):
    SELF_ASSERTED = "self_asserted", "Self-asserted (unverified)"
    OPERATOR_CONFIRMED = "operator_confirmed", "Operator confirmed"
    OTP_VERIFIED = "otp_verified", "OTP verified"
    PLATFORM_AUTHENTICATED = "platform_authenticated", "Platform authenticated"


class IdentityStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    MERGED = "merged", "Merged"
    BLOCKED = "blocked", "Blocked"


class Candidate(models.Model):
    """Canonical candidate PROFILE. No channel identifiers — those live in
    CandidateChannelIdentity."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)  # T0
    updated_at = models.DateTimeField(auto_now=True)      # T0

    lifecycle_stage = models.CharField(  # T1
        max_length=32, choices=LifecycleStage.choices, default=LifecycleStage.INTAKE
    )
    source_channel = models.CharField(max_length=24, choices=Channel.choices)  # T1
    preferred_language = models.CharField(max_length=8)  # T1

    full_name = models.CharField(max_length=200)            # T2
    citizenship_iso = models.CharField(max_length=2)        # T2
    current_country_iso = models.CharField(max_length=2)    # T2
    desired_country_iso = models.CharField(max_length=2)    # T2
    date_of_birth = models.DateField()                      # T3  age>=18 enforced at the operation
    profession = models.CharField(max_length=120, null=True, blank=True)  # T2

    duplicate_review_state = models.CharField(  # T1
        max_length=20,
        choices=DuplicateReviewState.choices,
        default=DuplicateReviewState.CLEAR,
    )

    class Meta:
        indexes = [models.Index(fields=["duplicate_review_state"])]

    def __str__(self):
        return f"Candidate {self.id} ({self.full_name})"


class CandidateChannelIdentity(models.Model):
    """One identifier ever seen for a candidate (ContactPoint).

    A candidate may hold MANY rows of the same identifier_type (multiple phones,
    Instagram accounts, etc.). The only per-candidate prohibition is the exact
    same identifier twice. A *verified* identifier maps to exactly one active
    candidate globally; unverified identifiers may collide (which triggers
    manual review, not an error). Verification is server-decided; inbound is
    recorded self_asserted/unverified.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    candidate = models.ForeignKey(
        "intake.Candidate", on_delete=models.PROTECT, related_name="channel_identities"
    )
    channel = models.CharField(max_length=24, choices=Channel.choices)        # T1
    identifier_type = models.CharField(max_length=32, choices=IdentifierType.choices)  # T1
    identifier_value = models.CharField(max_length=255)                       # T2/T3 (normalized)
    is_verified = models.BooleanField(default=False)
    verification_method = models.CharField(
        max_length=32,
        choices=VerificationMethod.choices,
        default=VerificationMethod.SELF_ASSERTED,
    )
    source_attribution = models.JSONField(default=dict)  # ad id, keyword, campaign, referral
    status = models.CharField(
        max_length=16, choices=IdentityStatus.choices, default=IdentityStatus.ACTIVE
    )
    first_seen_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            # No duplicate of the EXACT identifier on one candidate. Multiple
            # DIFFERENT values of the same type are allowed (many phones, etc.).
            models.UniqueConstraint(
                fields=["candidate", "identifier_type", "identifier_value"],
                name="uq_candidate_identifier",
            ),
            # A given VERIFIED identifier resolves to exactly one active candidate.
            # Unverified duplicates across candidates are permitted (-> review).
            models.UniqueConstraint(
                fields=["identifier_type", "identifier_value"],
                condition=Q(is_verified=True, status="active"),
                name="uq_verified_identifier_active",
            ),
        ]
        indexes = [
            models.Index(fields=["identifier_type", "identifier_value"]),
            models.Index(fields=["candidate"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self):
        return f"{self.identifier_type}={self.identifier_value} (verified={self.is_verified})"


class ConsentVersion(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    version = models.CharField(max_length=32)
    locale = models.CharField(max_length=8)
    purposes = models.JSONField(default=list)
    lawful_basis = models.CharField(
        max_length=32, choices=LawfulBasis.choices, default=LawfulBasis.CONSENT
    )
    notice_body = models.TextField()
    effective_from = models.DateTimeField()
    is_active = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["version", "locale"], name="uq_consent_version_locale"
            ),
            models.UniqueConstraint(
                fields=["locale"],
                condition=Q(is_active=True),
                name="uq_one_active_consent_per_locale",
            ),
        ]

    def __str__(self):
        return f"ConsentVersion {self.version}/{self.locale} (active={self.is_active})"


class ConsentRecord(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    candidate = models.ForeignKey(
        "intake.Candidate", on_delete=models.PROTECT, related_name="consent_records"
    )
    consent_version = models.ForeignKey(
        "intake.ConsentVersion", on_delete=models.PROTECT, related_name="records"
    )
    granted_at = models.DateTimeField()
    channel = models.CharField(max_length=24, choices=Channel.choices)
    locale_shown = models.CharField(max_length=8)
    actor_type = models.CharField(max_length=16, choices=ActorType.choices)
    actor_id = models.CharField(max_length=128)
    evidence = models.JSONField(default=dict)
    expires_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revocation_reason = models.CharField(max_length=255, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["candidate", "revoked_at"])]

    def __str__(self):
        return f"ConsentRecord {self.id} for {self.candidate_id}"


class IntakeSubmission(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    idempotency_key = models.CharField(max_length=128, unique=True)
    received_at = models.DateTimeField(auto_now_add=True)
    channel = models.CharField(max_length=24, choices=Channel.choices)
    raw_payload = models.JSONField()  # T2/T3 — erasure scope
    processing_status = models.CharField(
        max_length=16,
        choices=ProcessingStatus.choices,
        default=ProcessingStatus.RECEIVED,
    )
    rejection_reason = models.CharField(max_length=255, null=True, blank=True)
    candidate = models.ForeignKey(
        "intake.Candidate",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="submissions",
    )

    def __str__(self):
        return f"IntakeSubmission {self.id} ({self.processing_status})"


class IdentityMatchReview(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    candidate = models.ForeignKey(
        "intake.Candidate", on_delete=models.PROTECT, related_name="match_reviews"
    )
    matched_against = models.ForeignKey(
        "intake.Candidate",
        on_delete=models.PROTECT,
        related_name="match_reviews_against",
    )
    reason = models.CharField(max_length=255)
    state = models.CharField(
        max_length=24, choices=MatchReviewState.choices, default=MatchReviewState.OPEN
    )
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_by = models.CharField(max_length=128, null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["state"])]

    def __str__(self):
        return f"IdentityMatchReview {self.id} ({self.state})"
