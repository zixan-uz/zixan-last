-- =====================================================================
-- DIAMOR Phase 1A — provisioning step 01: prepare the diamor_app schema
-- ---------------------------------------------------------------------
-- RUN AS: diamor_app_user (NOT the admin), connected to diamor_app, AFTER its password
--   has been set interactively (see step 00 footer):
--     psql "host=<host> port=<port> user=diamor_app_user dbname=diamor_app" \
--          -v ON_ERROR_STOP=1 -f 01_prepare_diamor_app_schema.sql
--
-- diamor_app_user was GRANTED CREATE on diamor_app in step 00, so it can create and own
-- this schema even though it does NOT own the database (the Render-safe pattern).
--
-- SCOPE: prepares ONLY the Django app schema. No DIAMOR business tables are created here.
-- RERUN-SAFE: CREATE SCHEMA IF NOT EXISTS.
-- =====================================================================

-- 1) Dedicated, app-owned schema for the Django `diamor_app` connection.
CREATE SCHEMA IF NOT EXISTS diamor_app_schema AUTHORIZATION diamor_app_user;

-- 2) search_path is intentionally NOT set here. Under the Render-safe pattern,
--    diamor_app_user does NOT own diamor_app and therefore cannot ALTER DATABASE.
--    Instead, the Django `diamor_app` connection sets it per-connection via OPTIONS in
--    settings_snippet.py:  "options": "-c search_path=diamor_app_schema,public"
--    (a pure libpq connection parameter — no database/role privilege required).

-- 3) No extensions are required for Phase 1A.

-- =====================================================================
-- NEXT: run ONLY the diamor_runtime migration, and ONLY against diamor_app
--   (never a bare `migrate` — your existing Django default DB may be zixan_db):
--       python manage.py migrate diamor_runtime --database=diamor_app
-- =====================================================================
