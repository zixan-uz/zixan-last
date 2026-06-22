"""
DIAMOR — audit trust domain.

Append-only, hash-chained event log. Separate app/tables on the managed `default`
database; AuditEvent references subjects generically (type + id), not via FK, so
the chain survives erasure of operational rows. The insert-and-hash primitive in
audit/chain.py is the sole writer.
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
    CHANNEL_IDENTITY_ADDED = "channel_identity_added", "Channel identity added"
    CHANNEL_IDENTITY_VERIFIED = "channel_identity_verified", "Channel identity verified"


class AuditEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    sequence = models.BigIntegerField(unique=True)
    event_type = models.CharField(max_length=48, choices=AuditEventType.choices)

    actor_type = models.CharField(max_length=16)
    actor_id = models.CharField(max_length=128)

    subject_type = models.CharField(max_length=48)
    subject_id = models.CharField(max_length=64)

    occurred_at = models.DateTimeField()
    source = models.CharField(max_length=32)
    correlation_id = models.CharField(max_length=128)

    payload = models.JSONField(default=dict)

    prev_hash = models.CharField(max_length=64, null=True, blank=True)
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


class AuditChainHead(models.Model):
    id = models.SmallIntegerField(primary_key=True, default=1, editable=False)
    last_sequence = models.BigIntegerField()
    last_hash = models.CharField(max_length=64, null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(id=1), name="audit_chain_head_singleton"
            ),
        ]

    def __str__(self):
        return f"AuditChainHead(last_sequence={self.last_sequence})"
