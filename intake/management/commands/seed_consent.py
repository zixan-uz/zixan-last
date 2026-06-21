"""
Seed / activate ONE consent version for a locale (idempotent).

IMPORTANT: `notice_body` here is a PLACEHOLDER. The production notice text,
purposes, and lawful basis MUST be provided/approved by counsel before any real
candidate sees it. Do not ship the placeholder to production.

Usage:
    python manage.py seed_consent
    python manage.py seed_consent --consent-version 2026-06-v1 --locale ru
"""
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from intake.models import ConsentVersion, LawfulBasis


PLACEHOLDER_NOTICE = (
    "[PLACEHOLDER — replace with counsel-approved text before production] "
    "DIAMOR collects your personal data to assess and support your international "
    "employment application. You are interacting with DIAMOR's digital assistant. "
    "Your data is processed on the basis of your consent and you may withdraw it "
    "at any time."
)


class Command(BaseCommand):
    help = "Create and activate one ConsentVersion for a locale (idempotent)."

    def add_arguments(self, parser):
        # NOTE: Django's BaseCommand reserves --version (it prints the Django
        # version), so the consent version flag is --consent-version.
        parser.add_argument("--consent-version", default="2026-06-v1")
        parser.add_argument("--locale", default="ru")
        parser.add_argument("--lawful-basis", default=LawfulBasis.CONSENT)

    @transaction.atomic
    def handle(self, *args, **opts):
        version = opts["consent_version"]
        locale = opts["locale"]
        lawful_basis = opts["lawful_basis"]

        # Preserve the one-active-per-locale invariant: deactivate any other active
        # version for this locale before activating the target.
        ConsentVersion.objects.filter(locale=locale, is_active=True).exclude(
            version=version
        ).update(is_active=False)

        obj, created = ConsentVersion.objects.get_or_create(
            version=version,
            locale=locale,
            defaults={
                "purposes": [
                    "recruitment_assessment",
                    "candidate_support",
                    "communication",
                ],
                "lawful_basis": lawful_basis,
                "notice_body": PLACEHOLDER_NOTICE,
                "effective_from": timezone.now(),
                "is_active": True,
            },
        )
        if not created and not obj.is_active:
            obj.is_active = True
            obj.save(update_fields=["is_active"])

        action = "Created" if created else "Activated existing"
        self.stdout.write(
            self.style.SUCCESS(
                f"{action} ConsentVersion {obj.version}/{obj.locale} "
                f"(id={obj.id}, active={obj.is_active})"
            )
        )
