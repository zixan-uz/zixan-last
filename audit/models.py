"""
DIAMOR — audit trust domain.

Append-only, hash-chained event log. Separate app (and, in v1, a separate set of
tables on the managed `default` database) so the audit chain is isolated from
mutable operational data. AuditEvent references subjects generically (type + id),
NOT via ForeignKey, so the chain survives erasure of operational rows.

STRUCTURE only. The insert-and-hash primitive (monotonic sequence assignment,
hash chaining, and chain verification) is the NEXT deliverable and is the sole
writer of this table. Do not write AuditEvent rows by hand.
"""
import uuid

from django.db import models


class AuditEventType(models.TextChoices):
    CANDIDATE_CREATED = "candidate_created", "Candidate created"
    CANDIDATE_MATCHED = "candidate_matched", "Candidate matched"
    CONSENT_GRANTED = "consent_granted", "Consent granted"
    CONSENT_REVOKED = "consent_revoked", "Consent revoked"
    INTAKE_SUBMITTED = "intake_submitted", "Intake submitted"
    IDENTITY_REVIEW_FLAGGED = "identity_review_flagged", "Identity review flagged"


class AuditEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Monotonic chain order, assigned by the audit primitive. Drives tamper-evident
    # ordering independent of UUID/timestamp.
    sequence = models.BigIntegerField(unique=True)

    event_type = models.CharField(max_length=48, choices=AuditEventType.choices)

    actor_type = models.CharField(max_length=16)   # candidate | operator | system
    actor_id = models.CharField(max_length=128)    # server-verified

    subject_type = models.CharField(max_length=48)  # e.g. candidate, consent_record
    subject_id = models.CharField(max_length=64)    # UUID/string ref — NO FK by design

    occurred_at = models.DateTimeField()
    source = models.CharField(max_length=32)        # channel / component
    correlation_id = models.CharField(max_length=128)  # ties one operation's events (== idempotency key)

    payload = models.JSONField(default=dict)        # MINIMIZED — never Tier-3 PII

    prev_hash = models.CharField(max_length=64, null=True, blank=True)  # null only for genesis
    hash = models.CharField(max_length=64, unique=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["sequence"]
        indexes = [
            models.Index(fields=["subject_type", "subject_id"]),
            models.Index(fields=["correlation_id"]),
            models.Index(fields=["event_type"]),
        ]

    def __str__(self):
        return f"AuditEvent #{self.sequence} {self.event_type}"
