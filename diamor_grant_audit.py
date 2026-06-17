#!/usr/bin/env python
"""Read-only audit of the DIAMOR runtime database connection.

Verifies that the `diamor` alias the app uses for DIAMOR calls is a least-privilege
DIAMOR app role — NOT zixan_user, NOT on zixan_db, NOT a superuser — and is a member of
manager_role (so manager decisions are accepted). Makes only SELECTs; changes nothing.

Run:
    DJANGO_SETTINGS_MODULE=yourproject.settings python diamor_grant_audit.py
Exit code 0 = pass, 1 = audit failure, 2 = misconfiguration.
"""
import os
import sys


def main():
    if not os.environ.get("DJANGO_SETTINGS_MODULE"):
        print("ERROR: set DJANGO_SETTINGS_MODULE to your project settings.")
        return 2

    import django

    django.setup()
    from django.db import connections

    with connections["diamor"].cursor() as cur:
        cur.execute("SELECT current_user, session_user, current_database()")
        current_user, session_user, db = cur.fetchone()
        cur.execute(
            "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"
        )
        rolsuper, rolbypassrls = cur.fetchone()
        cur.execute("SELECT pg_has_role(current_user, 'manager_role', 'member')")
        is_manager = cur.fetchone()[0]

    print("DIAMOR runtime connection audit")
    print(f"  database     : {db}")
    print(f"  current_user : {current_user}")
    print(f"  session_user : {session_user}")
    print(f"  superuser    : {rolsuper}")
    print(f"  bypassrls    : {rolbypassrls}")
    print(f"  manager_role : {is_manager}")

    problems = []
    if "zixan_user" in (current_user, session_user):
        problems.append("connection uses zixan_user — FORBIDDEN for DIAMOR runtime")
    if db == "zixan_db":
        problems.append("connection is on zixan_db — FORBIDDEN")
    if rolsuper:
        problems.append("connection role is a superuser — must be a least-privilege app role")
    if rolbypassrls:
        problems.append("connection role has BYPASSRLS — must not")
    if not is_manager:
        problems.append(
            "connection role is not a member of manager_role — disclosure decisions will be denied"
        )

    if problems:
        print("\nAUDIT FAILED:")
        for p in problems:
            print(f"  - {p}")
        return 1

    print("\nAUDIT PASSED: DIAMOR runtime connection is a least-privilege manager app role.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
