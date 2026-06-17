"""Phase 1 endpoints.

Security posture:
  * NO @csrf_exempt anywhere. Phase 1 uses existing Django session auth, so
    CsrfViewMiddleware enforces CSRF on POST. The staff client must send X-CSRFToken.
  * `party_id` and `decided_by` are NEVER read from the client. The acting party is the
    server-resolved staff party (from the identity map), which the DIAMOR layer further
    requires to equal the bound session party.
  * `approve` must be a real JSON boolean — see require_json_bool.
"""
import json

from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from .auth import require_auth, resolve_staff_party
from .db import DiamorHttpError, Http400, diamor_manager_session, run_domain


def require_json_bool(data, key):
    """Return data[key] iff it is a real JSON boolean (Python bool).

    Rejects everything else with HTTP 400: missing, "true"/"false" strings, 1/0,
    "yes"/"no". isinstance(x, bool) is True ONLY for Python True/False, which json.loads
    produces solely from JSON true/false; JSON 1/0 -> int, "true" -> str (both rejected).
    Note: 1 is NOT an instance of bool, so integers are correctly refused — unlike
    bool("false") which would wrongly be True.
    """
    if key not in data:
        raise Http400(f"missing required boolean field: {key!r}")
    val = data[key]
    if isinstance(val, bool):
        return val
    raise Http400(
        f"field {key!r} must be a JSON boolean true/false, got {type(val).__name__}"
    )


def _require_int(data, key):
    """Return data[key] iff it is a real JSON integer (not bool, not string)."""
    if key not in data:
        raise Http400(f"missing required field: {key!r}")
    val = data[key]
    if isinstance(val, bool) or not isinstance(val, int):
        raise Http400(f"field {key!r} must be an integer")
    return val


def _body(request):
    """Parse a JSON object body, or raise Http400."""
    if not request.body:
        raise Http400("request body must be a JSON object")
    try:
        data = json.loads(request.body)
    except (ValueError, TypeError):
        raise Http400("request body is not valid JSON")
    if not isinstance(data, dict):
        raise Http400("request body must be a JSON object")
    return data


def _run(handler, request):
    """Execute a handler and map DiamorHttpError -> JsonResponse; hide unexpected errors."""
    try:
        result = handler(request)
    except DiamorHttpError as exc:
        return JsonResponse({"error": exc.message}, status=exc.status)
    except Exception:  # noqa: BLE001 — never leak internals
        return JsonResponse({"error": "internal error"}, status=500)
    return JsonResponse(result, status=200)


@require_http_methods(["GET"])
def whoami(request):
    return _run(_whoami, request)


def _whoami(request):
    user = require_auth(request)                  # 401
    staff_party_id = resolve_staff_party(user)    # 403
    return {"django_user_id": user.id, "staff_party_id": staff_party_id}


@require_http_methods(["POST"])
def disclosure_decision(request):
    return _run(_disclosure_decision, request)


def _disclosure_decision(request):
    user = require_auth(request)                   # 401
    staff_party_id = resolve_staff_party(user)     # 403 (unmapped) / DB 42501 -> 403
    body = _body(request)                          # 400 (bad JSON)
    approve = require_json_bool(body, "approve")   # 400 (not a real JSON boolean)
    request_id = _require_int(body, "request_id")  # 400 (missing / not int)
    # decided_by is the server-resolved staff party — NOT taken from the client.
    with diamor_manager_session(staff_party_id) as cur:
        run_domain(
            cur,
            "SELECT decide_disclosure_request(%s, %s, %s)",
            [request_id, approve, staff_party_id],
        )  # P0001 (business rule) -> 422
    return {"status": "ok", "request_id": request_id, "approved": approve}
