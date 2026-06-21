"""
DIAMOR — intake domain models.

Single governed entry point for candidates. This module defines STRUCTURE only.
All business logic (validation, normalization, identity resolution, consent
verification, audit emission) lives in the intake operation and the audit
primitive — never here.

Per-field data-tier classification:
  T0 public/operational | T1 internal | T2 personal | T3 sensitive personal

Routing: this app is NOT diamor_runtime, so under DiamorRuntimeRouter it lives on
the `default` (managed, PITR-backed, system-of-record) database.
"""
import uuid

from django.db import models
from django.db.models import Q


class LifecycleStage(models.TextChoices):
    # Provisional v1 set. The canonical 15-stage enum is owned by the lifecycle
    # module and will reconcile with / extend this. INTAKE is the entry stage.
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
    WEB = "web", "Web portal"
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


class Candidate(models.Model):
    """Canonical candidate identity. `intake` is the sole writer in v1."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)  # T0
    updated_at = models.DateTimeField(auto_now=True)      # T0

    lifecycle_stage = models.CharField(  # T1
        max_length=32, choices=LifecycleStage.choices, default=LifecycleStage.INTAKE
    )
    source_channel = models.CharField(max_length=16, choices=Channel.choices)  # T1
    preferred_language = models.CharField(max_length=8)  # T1  e.g. ru, uz, tg, ky

    # --- Identity keys ---
    # telegram_id is the strongest per-account match key. unique=True with null=True:
    # Postgres treats NULLs as distinct, so this enforces "<=1 candidate per telegram_id"
    # while still allowing future non-Telegram candidates (web portal) to have no id.
    telegram_id = models.BigIntegerField(null=True, blank=True, unique=True)  # T2
    telegram_username = models.CharField(max_length=64, null=True, blank=True)  # T2
    # phone normalized to E.164 at the boundary. Deliberately NOT unique — shared
    # devices/intermediaries are common in this population; uniqueness would create
    # false collisions. Phone is a *signal* for identity resolution, not a hard key.
    phone_e164 = models.CharField(max_length=20)  # T2

    # --- Profile (normalized at the boundary) ---
    full_name = models.CharField(max_length=200)            # T2
    citizenship_iso = models.CharField(max_length=2)        # T2  ISO 3166-1 alpha-2
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
        indexes = [
            models.Index(fields=["phone_e164"]),
            models.Index(fields=["telegram_id"]),
            models.Index(fields=["duplicate_review_state"]),
        ]

    def __str__(self):
        return f"Candidate {self.id} ({self.full_name})"


class ConsentVersion(models.Model):
    """Immutable, versioned consent notice. At most one active version per locale."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    version = models.CharField(max_length=32)        # e.g. "2026-06-v1"
    locale = models.CharField(max_length=8)          # ru, uz, tg, ky
    purposes = models.JSONField(default=list)        # list[str] of processing purposes
    lawful_basis = models.CharField(
        max_length=32, choices=LawfulBasis.choices, default=LawfulBasis.CONSENT
    )
    notice_body = models.TextField()                 # the exact text shown to the candidate
    effective_from = models.DateTimeField()
    is_active = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["version", "locale"], name="uq_consent_version_locale"
            ),
            # Partial unique index (Postgres): enforces <=1 active version per locale.
            models.UniqueConstraint(
                fields=["locale"],
                condition=Q(is_active=True),
                name="uq_one_active_consent_per_locale",
            ),
        ]

    def __str__(self):
        return f"ConsentVersion {self.version}/{self.locale} (active={self.is_active})"


class ConsentRecord(models.Model):
    """First-class, append-only consent grant. Never updated except revocation fields."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    candidate = models.ForeignKey(
        "intake.Candidate", on_delete=models.PROTECT, related_name="consent_records"
    )
    consent_version = models.ForeignKey(
        "intake.ConsentVersion", on_delete=models.PROTECT, related_name="records"
    )
    granted_at = models.DateTimeField()
    channel = models.CharField(max_length=16, choices=Channel.choices)
    locale_shown = models.CharField(max_length=8)
    actor_type = models.CharField(max_length=16, choices=ActorType.choices)
    actor_id = models.CharField(max_length=128)      # server-verified actor identifier
    evidence = models.JSONField(default=dict)        # affirmative-action evidence
    expires_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revocation_reason = models.CharField(max_length=255, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["candidate", "revoked_at"])]

    def __str__(self):
        return f"ConsentRecord {self.id} for {self.candidate_id}"


class IntakeSubmission(models.Model):
    """Raw submission envelope. Separates 'what was submitted' from the canonical
    candidate. raw_payload is PII-bearing (T2/T3) and is in scope for retention/erasure."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    idempotency_key = models.CharField(max_length=128, unique=True)
    received_at = models.DateTimeField(auto_now_add=True)
    channel = models.CharField(max_length=16, choices=Channel.choices)
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
    """Operator queue for ambiguous identity matches. No automatic destructive merges."""

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
