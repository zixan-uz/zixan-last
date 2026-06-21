"""
DIAMOR — intake validation & normalization (pure functions, no DB access).

Boundary checks for the governed intake operation. Each raises
IntakeValidationError on bad input; the service layer maps that to a rejected
intake and, by design, persists NOTHING for an invalid or non-consented attempt.
No persistence and no business logic here.
"""
import datetime

import phonenumbers


MINIMUM_AGE = 18
SUPPORTED_LANGUAGES = {"ru", "uz", "tg", "ky", "en"}


class IntakeValidationError(Exception):
    """Raised when an intake payload field fails validation."""

    def __init__(self, field, message):
        self.field = field
        self.message = message
        super().__init__(f"{field}: {message}")


def clean_text(value, field, max_length, required=True):
    if value is None or not str(value).strip():
        if required:
            raise IntakeValidationError(field, "This field is required.")
        return None
    cleaned = " ".join(str(value).split())  # collapse internal/edge whitespace
    if len(cleaned) > max_length:
        raise IntakeValidationError(field, f"Exceeds maximum length of {max_length}.")
    return cleaned


def normalize_language(value):
    if value is None or not str(value).strip():
        raise IntakeValidationError("preferred_language", "Preferred language is required.")
    lang = str(value).strip().lower()
    if lang not in SUPPORTED_LANGUAGES:
        raise IntakeValidationError("preferred_language", f"Unsupported language '{lang}'.")
    return lang


def normalize_country(value, field):
    if value is None or not str(value).strip():
        raise IntakeValidationError(field, "Country is required.")
    code = str(value).strip().upper()
    # ISO 3166-1 alpha-2 shape check. Membership against a controlled vocabulary
    # is a later hardening step; for now we enforce the shape and uppercase it.
    if len(code) != 2 or not code.isalpha():
        raise IntakeValidationError(
            field, "Country must be an ISO 3166-1 alpha-2 code (e.g. UZ, DE)."
        )
    return code


def normalize_phone(value, default_region=None):
    if value is None or not str(value).strip():
        raise IntakeValidationError("phone", "Phone number is required.")
    region = default_region if (default_region and len(default_region) == 2) else None
    try:
        parsed = phonenumbers.parse(str(value).strip(), region)
    except phonenumbers.NumberParseException:
        raise IntakeValidationError("phone", "Phone number could not be parsed.")
    if not phonenumbers.is_valid_number(parsed):
        raise IntakeValidationError("phone", "Phone number is not a valid number.")
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)


def parse_date_of_birth(value, today=None):
    if value is None or (isinstance(value, str) and not value.strip()):
        raise IntakeValidationError("date_of_birth", "Date of birth is required.")
    if isinstance(value, datetime.datetime):
        dob = value.date()
    elif isinstance(value, datetime.date):
        dob = value
    else:
        try:
            dob = datetime.date.fromisoformat(str(value).strip())
        except ValueError:
            raise IntakeValidationError(
                "date_of_birth", "Date of birth must be ISO format YYYY-MM-DD."
            )
    today = today or datetime.date.today()
    if dob > today:
        raise IntakeValidationError("date_of_birth", "Date of birth is in the future.")
    age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
    if age < MINIMUM_AGE:
        raise IntakeValidationError(
            "date_of_birth", f"Candidate must be at least {MINIMUM_AGE} years old."
        )
    return dob


def coerce_telegram_id(value):
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        raise IntakeValidationError("telegram_id", "telegram_id must be an integer.")
