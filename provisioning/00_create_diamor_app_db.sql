-- =====================================================================
-- DIAMOR Phase 1A — provisioning step 00: create app role + app database
-- ---------------------------------------------------------------------
-- RUN AS: the Render admin/owner login, connected to the MAINTENANCE database
--   `postgres` (i.e. dbname=postgres) — NOT zixan_db, and NOT diamor_app (which does not
--   exist yet).
--     psql "host=<host> port=<port> user=<admin> dbname=postgres" -v ON_ERROR_STOP=1 \
--          -f 00_create_diamor_app_db.sql
--
--   RENDER FALLBACK: if your instance does not expose a `postgres` maintenance database,
--   connect to whatever default database Render created — ANY database OTHER THAN zixan_db
--   and diamor_app is safe, because step 00 only touches cluster-global catalog objects
--   (a role, CREATE DATABASE, and database-level grants). Never run step 00 on zixan_db.
--
-- RENDER-SAFE PATTERN: we do NOT create the database with an OWNER override. On Render the
--   admin may have CREATEDB/CREATEROLE yet not be permitted to create a database owned by
--   another role (that requires membership in the target role). So diamor_app is owned by
--   the admin/install user, and diamor_app_user is instead GRANTED the database-level
--   privileges it needs (CONNECT to log in, CREATE to make its own schema, TEMPORARY).
--   We also do NOT set explicit superuser attributes on the role (default is non-superuser;
--   Render has rejected explicit superuser attribute changes).
--
-- RUN PLAIN — do NOT use --single-transaction. CREATE DATABASE cannot run inside a
--   transaction block.
--
-- RERUN-SAFE: role created only if absent; database created only if absent; grants idempotent.
-- =====================================================================

-- 1) App login role — minimal attributes only.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'diamor_app_user') THEN
        CREATE ROLE diamor_app_user LOGIN;
    END IF;
END $$;

-- 2) App database, WITHOUT an OWNER override. Guarded \gexec keeps it idempotent
--    (CREATE DATABASE cannot live in a DO block or a transaction).
SELECT 'CREATE DATABASE diamor_app'
 WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'diamor_app')\gexec

-- 3) Connect lockdown + database-level grants for the app role.
REVOKE CONNECT ON DATABASE diamor_app FROM PUBLIC;
GRANT  CONNECT, CREATE, TEMPORARY ON DATABASE diamor_app TO diamor_app_user;

-- =====================================================================
-- NEXT (manual, between step 00 and step 01):
--
--   SET THE PASSWORD INTERACTIVELY so it never lands in SQL files or shell history.
--   In an interactive psql session connected as the admin:
--       \password diamor_app_user
--   \password prompts for the value and issues ALTER ROLE ... PASSWORD for you without
--   echoing it or writing it to ~/.psql_history. Never pass a password on the command line
--   or embed it in any file.
--
--   Then run 01_prepare_diamor_app_schema.sql AS diamor_app_user, connected to diamor_app.
-- =====================================================================
