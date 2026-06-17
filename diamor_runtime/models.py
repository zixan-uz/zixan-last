from django.db import models


class DiamorStaffIdentityMap(models.Model):
    """Maps an existing Django staff user to a DIAMOR staff *party* id.

    This is the ONLY ORM-managed table in Phase 1, and it lives ONLY in the
    `diamor_app` database (enforced by DiamorRuntimeRouter).

    There is deliberately NO Django ForeignKey to auth_user: that table lives in the
    existing `default` database (possibly zixan_db), and a cross-database FK cannot be
    enforced or joined in PostgreSQL. We store the user id as a plain integer and look
    up by it. `staff_party_id` is the DIAMOR party id used for both
    session_set_party(...) and as decided_by in manager decisions; that party must hold
    the DIAMOR 'manager' business role for the disclosure decision to be accepted.
    """

    django_user_id = models.IntegerField(unique=True, db_index=True)
    staff_party_id = models.BigIntegerField()
    # Phase 1 wires only the manager app role; field kept for later phases.
    app_role = models.CharField(max_length=64, default="manager")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "diamor_runtime"
        db_table = "diamor_staff_identity_map"

    def __str__(self):
        return f"django_user {self.django_user_id} -> diamor party {self.staff_party_id}"
