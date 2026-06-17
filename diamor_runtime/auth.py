"""Staff authentication + DIAMOR staff-party resolution.

401 = not logged in.
403 = logged in but not a mapped DIAMOR staff (or, later, DB privilege denied).
"""
from .db import Http401, Http403
from .models import DiamorStaffIdentityMap


def require_auth(request):
    """Return the authenticated user, or raise Http401."""
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        raise Http401("authentication required")
    return user


def resolve_staff_party(user):
    """Map a Django staff user to a DIAMOR staff party id via diamor_staff_identity_map
    (in diamor_app). Raise Http403 if the user is not staff or has no active mapping.

    Defense in depth: only Django staff may map to a DIAMOR staff party."""
    if not getattr(user, "is_staff", False):
        raise Http403("user is not staff")
    try:
        mapping = DiamorStaffIdentityMap.objects.using("diamor_app").get(
            django_user_id=user.id, is_active=True
        )
    except DiamorStaffIdentityMap.DoesNotExist:
        raise Http403("no active DIAMOR staff mapping for this user")
    return mapping.staff_party_id
