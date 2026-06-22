"""
DIAMOR — intake validation & normalization (pure functions, no DB access).

Boundary checks for the governed intake operation. Each raises
IntakeValidationError on bad input; the service maps that to a rejected intake
and persists NOTHING for an invalid or non-consented attempt.
"""
import datetime
import re

import phonenumbers


MINIMUM_AGE = 18
SUPPORTED_LANGUAGES = {"ru", "uz", "tg", "ky", "en"}

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_USERNAME_RE = re.compile(r"^[a-z0-9._]{1,64}$")


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
    cleaned = " ".join(str(value).split())
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


def normalize_identifier_value(identifier_type, value, default_region=None):
    """Normalize a channel identifier's value by its type. Raises on bad value.
    The caller (service) validates that identifier_type itself is known."""
    v = (str(value).strip() if value is not None else "")
    if not v:
        raise IntakeValidationError("identifier_value", "Identifier value is required.")

    if identifier_type == "phone_e164":
        return normalize_phone(v, default_region)

    if identifier_type == "email":
        email = v.lower()
        if not _EMAIL_RE.match(email):
            raise IntakeValidationError("identifier_value", "Invalid email address.")
        return email

    if identifier_type in ("telegram_id", "instagram_user_id"):
        if not v.isdigit():
            raise IntakeValidationError(
                "identifier_value", f"{identifier_type} must be numeric."
            )
        return v

    if identifier_type in ("telegram_username", "instagram_username"):
        username = v.lstrip("@").lower()
        if not _USERNAME_RE.match(username):
            raise IntakeValidationError("identifier_value", "Invalid username.")
        return username

    if identifier_type in ("whatsapp_id", "website_session"):
        if len(v) > 255:
            raise IntakeValidationError("identifier_value", "Identifier value too long.")
        return v

    raise IntakeValidationError(
        "identifier_type", f"Unsupported identifier_type '{identifier_type}'."
    )
