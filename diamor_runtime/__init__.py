# DIAMOR Runtime (Phase 1) — thin adapter over the DIAMOR SQL layer.
# No Django ORM over DIAMOR tables; only diamor_staff_identity_map is ORM-managed.
default_app_config = "diamor_runtime.apps.DiamorRuntimeConfig"
