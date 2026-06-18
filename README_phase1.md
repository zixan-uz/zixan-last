# DIAMOR — Django Phase 1A runtime

> **Scope: Phase 1A — the minimal manager disclosure slice.** This is the first live
> Django ↔ DIAMOR integration step: an authenticated **staff/manager** can drive the
> contact-disclosure decision through the DIAMOR SQL layer, using a DIAMOR app role and
> `session_set_party(...)`. No Django ORM touches DIAMOR business tables.
>
> **In this package (Phase 1A):**
> - `GET  /diamor/phase1/whoami` — caller's Django user id + mapped DIAMOR staff party id.
> - `POST /diamor/phase1/disclosure/decide` — manager approves/denies a disclosure request.
>
> **NOT yet (deferred to Phase 1B, after 1A runs successfully in Django):**
> - finance payment confirm
> - finance payment list
> - the full manager/finance back-office slice
>
> Finance endpoints are added only after Phase 1A passes in your environment.

## POST contract

```json
{ "request_id": 123, "approve": true }
```

- `approve` **must** be a real JSON boolean (`true`/`false`). `"true"`, `"false"`, `1`,
  `0`, `"yes"` are rejected with **400** (`require_json_bool`).
- `request_id` must be a JSON integer.
- `party_id` / `decided_by` are **never** accepted from the client. The acting party is the
  server-resolved staff party (from the identity map), which the DIAMOR layer further
  requires to equal the bound session party. (Test: `test_client_decided_by_is_ignored`.)

## Three databases (the existing default DB is never touched)

| Django alias | Database | Managed how | Role |
| --- | --- | --- | --- |
| `default` | your existing DB (may be `zixan_db`) | unchanged by this package | unchanged |
| `diamor_app` | `diamor_app` (new) | Django ORM — **only** `diamor_staff_identity_map` | `diamor_app_user` |
| `diamor` | the DIAMOR DB (e.g. `diamor_staging`) | **raw SQL only**, never ORM | `app_manager_admin` (manager_role) |

Both DIAMOR aliases connect over TLS (`sslmode=require`, configurable). The DIAMOR runtime
connection is opened per request and **explicitly closed** after the transaction, so the
app role and its bound session never leak into a later request.

## Provisioning (once, per environment) — Render-safe

1. **Create the role + database** — as the Render admin, connected to the maintenance DB
   `postgres` (see the file header for the Render fallback; never connect to `zixan_db`).
   Run **plain** (not `--single-transaction`):
   ```
   psql "host=<h> port=<p> user=<admin> dbname=postgres" -v ON_ERROR_STOP=1 \
        -f provisioning/00_create_diamor_app_db.sql
   ```
   This creates `diamor_app_user` (LOGIN only), creates `diamor_app` **without an OWNER
   override** (the admin may not be allowed to create a DB owned by another role on Render),
   and grants `CONNECT, CREATE, TEMPORARY` on `diamor_app` to `diamor_app_user`.
2. **Set the app password interactively** (never in SQL or shell history):
   ```
   psql "host=<h> port=<p> user=<admin> dbname=postgres"
   \password diamor_app_user
   ```
3. **Prepare the schema** — as `diamor_app_user`, connected to `diamor_app`:
   ```
   psql "host=<h> port=<p> user=diamor_app_user dbname=diamor_app" -v ON_ERROR_STOP=1 \
        -f provisioning/01_prepare_diamor_app_schema.sql
   ```
   Creates `diamor_app_schema` owned by `diamor_app_user` (which has `CREATE` on the DB from
   step 1). The search_path is set on the Django connection via `OPTIONS`
   (`-c search_path=diamor_app_schema,public`), so no `ALTER DATABASE`/ownership is needed.
4. **Migrate only the runtime app, only against `diamor_app`** (never a bare `migrate`):
   ```
   python manage.py migrate diamor_runtime --database=diamor_app
   ```
5. **Seed the staff map** (in `diamor_app`): one `diamor_staff_identity_map` row per staff
   user — `django_user_id` → the DIAMOR staff **party** id. That party must hold the DIAMOR
   `manager` business role for disclosure decisions to be accepted.

## Settings & environment

See `settings_snippet.py` — it **adds** the `diamor_app` and `diamor` aliases (without
overwriting `default`), sets `OPTIONS` (TLS `sslmode`, plus the `search_path` for
`diamor_app`), registers the router, and documents CSRF + URL wiring. Variables are in
`.env.diamor.example` (including `DIAMOR_APP_DB_SSLMODE` and `DIAMOR_DB_SSLMODE`).

## HTTP error mapping

| Status | Meaning |
| --- | --- |
| **400** | Malformed input — bad JSON, `approve` not a real JSON boolean, or `request_id` missing/not an integer. |
| **401** | Not logged in (`require_auth`). |
| **403** | Logged in but not a mapped DIAMOR staff, **or** a database privilege was denied (PostgreSQL `42501`). |
| **422** | A DIAMOR domain/business rule rejected the action (a SECURITY DEFINER function `RAISE`, SQLSTATE `P0001`). |
| 500 | Unexpected error (details are not leaked to the client). |

## CSRF

Phase 1A uses **existing Django session authentication**, so `CsrfViewMiddleware` stays
enabled and the endpoints are **not** `csrf_exempt`. The staff client must send the CSRF
token (`X-CSRFToken`) on `POST`. A genuinely server-to-server endpoint would be the only
case to use token auth instead — raise it explicitly rather than exempting a staff mutation.

## Tests

`tests/test_phase1.py` is DB-free (DIAMOR/auth layers mocked): `require_json_bool`
(`true`/`false` accepted; `"true"`, `"false"`, `1`, `0`, `"yes"`, missing → 400); the
endpoint contract (401 unauthenticated, 403 unmapped, 200 on real booleans, 400 on
`"false"`/`1`/missing `request_id`); and `test_client_decided_by_is_ignored` (a client
`decided_by` is dropped — the call uses the mapped staff party).

```
python manage.py test diamor_runtime
```

## Grant audit

`diamor_grant_audit.py` makes read-only checks that the `diamor` connection is a
least-privilege manager app role — not `zixan_user`, not on `zixan_db`, not a superuser, a
member of `manager_role`:

```
DJANGO_SETTINGS_MODULE=yourproject.settings python diamor_grant_audit.py
```

## Constraints honored

- `zixan_db` is never touched; the existing `default` DB is left as-is.
- The DIAMOR database design is not changed; no DIAMOR table DML from Django.
- `zixan_user` is never used at runtime; DIAMOR calls use `app_manager_admin`.
- Only `diamor_staff_identity_map` is ORM-managed, and only inside `diamor_app`.
- No passwords are printed, requested, or stored by this package.
- `party_id` / `decided_by` are never accepted from the client.
- Every DIAMOR call runs through an app role, binds `session_set_party(staff_party_id)`
  first inside an explicit transaction, and closes the connection afterward.
