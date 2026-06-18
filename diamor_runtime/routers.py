class DiamorRuntimeRouter:
    """
    Database router for DIAMOR Phase 1 runtime integration.

    Invariants:
    - Managed Django model for staff identity map lives only in `diamor_app`.
    - Raw DIAMOR domain database alias `diamor` is never migrated by Django.
    - DIAMOR runtime migrations must never be applied to `default`.
    """

    app_label = "diamor_runtime"
    managed_db = "diamor_app"
    raw_db = "diamor"

    def db_for_read(self, model, **hints):
        if model._meta.app_label == self.app_label:
            return self.managed_db
        return None

    def db_for_write(self, model, **hints):
        if model._meta.app_label == self.app_label:
            return self.managed_db
        return None

    def allow_relation(self, obj1, obj2, **hints):
        if (
            obj1._meta.app_label == self.app_label
            or obj2._meta.app_label == self.app_label
        ):
            return True
        return None

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        # The raw DIAMOR domain alias is managed by SQL scripts only.
        # Django migrations must never run there.
        if db == self.raw_db:
            return False

        # DIAMOR runtime Django models may migrate only to diamor_app.
        # This is a hard deny for default and every other alias.
        if app_label == self.app_label:
            return db == self.managed_db

        # diamor_app is reserved for DIAMOR runtime mapping tables only.
        # Prevent auth/admin/sessions/etc. from being created there.
        if db == self.managed_db:
            return False

        # For all unrelated apps/databases, let Django/default routers decide.
        return None
