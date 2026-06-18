"""DIAMOR database access for the runtime app.

Hard rules enforced here:
  * The DIAMOR database is reached ONLY through the `diamor` Django alias, which is
    configured with a DIAMOR *app role* (Phase 1: app_manager_admin) — never zixan_user.
  * Every DIAMOR mutation runs inside a transaction that first binds the acting staff
    party via session_set_party(staff_party_id) (the session is transaction-local).
  * No Django ORM model is ever bound to the `diamor` alias (the router forbids it);
    we use raw cursors only.
  * PostgreSQL errors are mapped to HTTP semantics: 42501 -> 403, P0001 -> 422.
"""
from contextlib import contextmanager

from django.db import connections, transaction

# Django DATABASES alias for the raw DIAMOR connection (see settings_snippet.py).
DIAMOR_DB_ALIAS = "diamor"


# --- HTTP error hierarchy (mapped to JsonResponse by views) ----------------
class DiamorHttpError(Exception):
    status = 500

    def __init__(self, message):
        self.message = message
        super().__init__(message)


class Http400(DiamorHttpError):
    status = 400


class Http401(DiamorHttpError):
    status = 401


class Http403(DiamorHttpError):
    status = 403


class Http422(DiamorHttpError):
    status = 422


# --- PostgreSQL error introspection ----------------------------------------
def _sqlstate(exc):
    """Best-effort SQLSTATE across psycopg2 / psycopg3 and Django's wrappers."""
    for e in (exc, getattr(exc, "__cause__", None)):
        if e is None:
            continue
        code = getattr(e, "pgcode", None) or getattr(e, "sqlstate", None)
        if code:
            return code
        diag = getattr(e, "diag", None)
        if diag is not None and getattr(diag, "sqlstate", None):
            return diag.sqlstate
    return None


def _pg_message(exc):
    for e in (exc, getattr(exc, "__cause__", None)):
        diag = getattr(e, "diag", None)
        if diag is not None and getattr(diag, "message_primary", None):
            return diag.message_primary
    return str(exc)


def run_domain(cur, sql, params=()):
    """Execute one DIAMOR statement and translate failures to HTTP semantics.

    42501 (insufficient_privilege) -> 403 ; P0001 (a DIAMOR business-rule RAISE) -> 422.
    Returns the first column of the first row (functions are called as `SELECT fn(...)`,
    which always yields exactly one row; for RETURNS void this is harmless)."""
    try:
        cur.execute(sql, params)
    except DiamorHttpError:
        raise
    except Exception as exc:  # noqa: BLE001 — re-raised or mapped below
        state = _sqlstate(exc)
        if state == "42501":
            raise Http403("database privilege denied")
        if state == "P0001":
            raise Http422(_pg_message(exc))
        raise
    try:
        row = cur.fetchone()
        return row[0] if row else None
    except Exception:  # noqa: BLE001 — statement returned no result set
        return None


@contextmanager
def diamor_manager_session(staff_party_id):
    """Open a manager (app_manager_admin) DIAMOR transaction with `staff_party_id`
    bound as the acting party. All DIAMOR mutations for the request happen inside.

    session_set_party uses SET LOCAL, so it is valid only within this transaction —
    which is exactly the scope opened by transaction.atomic(using=...).

    The connection is explicitly closed at the end of the block, so the DIAMOR role and
    its bound session never leak into a later request even if persistent connections
    (CONN_MAX_AGE) are enabled later."""
    conn = connections[DIAMOR_DB_ALIAS]
    try:
        with transaction.atomic(using=DIAMOR_DB_ALIAS):
            with conn.cursor() as cur:
                run_domain(cur, "SELECT session_set_party(%s)", [staff_party_id])
                yield cur
    finally:
        conn.close()
