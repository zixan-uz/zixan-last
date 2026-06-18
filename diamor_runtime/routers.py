class DiamorRuntimeRouter:
    """Database router for Phase 1.

    * diamor_runtime models + migrations -> the `diamor_app` database ONLY.
    * The raw DIAMOR alias (`diamor`) is raw-SQL only: NOTHING ORM ever reads, writes,
      or migrates there.
    * Every other app is left to the existing `default` database, untouched.
    """

    APP_LABEL = "diamor_runtime"
    DIAMOR_APP_ALIAS = "diamor_app"
    RAW_DIAMOR_ALIAS = "diamor"

    def db_for_read(self, model, **hints):
        if model._meta.app_label == self.APP_LABEL:
            return self.DIAMOR_APP_ALIAS
        return None  # default DB handles everything else

    def db_for_write(self, model, **hints):
        if model._meta.app_label == self.APP_LABEL:
            return self.DIAMOR_APP_ALIAS
        return None

    def allow_relation(self, obj1, obj2, **hints):
        labels = {obj1._meta.app_label, obj2._meta.app_label}
        if labels == {self.APP_LABEL}:
            return True
        return None

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        # The runtime app migrates ONLY onto diamor_app.
        if app_label == self.APP_LABEL:
            return db == self.DIAMOR_APP_ALIAS
        # No other app may migrate onto diamor_app.
        if db == self.DIAMOR_APP_ALIAS:
            return False
        # Nothing — ever — migrates onto the raw DIAMOR connection.
        if db == self.RAW_DIAMOR_ALIAS:
            return False
        return None  # default behavior for the existing default DB
