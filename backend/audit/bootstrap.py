"""Provision the immudb audit database and least-privilege user."""

from __future__ import annotations

import os


def main() -> None:
    from immudb.client import ImmudbClient  # type: ignore[import-not-found]
    from immudb.constants import PERMISSION_RW  # type: ignore[import-not-found]

    host = os.environ.get("AUDIT_IMMUDB_HOST", "immudb")
    port = os.environ.get("AUDIT_IMMUDB_PORT", "3322")
    database = os.environ.get("AUDIT_IMMUDB_DATABASE", "trace_audit")
    admin_user = os.environ.get("AUDIT_IMMUDB_ADMIN_USER", "immudb")
    admin_password = os.environ["AUDIT_IMMUDB_ADMIN_PASSWORD"]
    audit_user = os.environ["AUDIT_IMMUDB_USERNAME"]
    audit_password = os.environ["AUDIT_IMMUDB_PASSWORD"]

    client = ImmudbClient(f"{host}:{port}")
    try:
        client.login(admin_user, admin_password)
        if database not in client.databaseList():
            client.createDatabase(database.encode("utf-8"))
        users = client.listUsers()
        # immudb-py 1.5 wraps the protobuf ``UserList`` in a
        # ``listUsersResponse`` object, while older SDK releases exposed the
        # repeated users directly.  Support both shapes so bootstrap remains
        # compatible with the pinned client and with local upgrade checks.
        user_list = getattr(users, "users", None)
        if user_list is None:
            user_list = getattr(getattr(users, "userlist", None), "users", ())
        user_names = {
            (
                getattr(user, "user", b"").decode("utf-8")
                if isinstance(getattr(user, "user", b""), bytes)
                else str(getattr(user, "user", ""))
            )
            for user in user_list
        }
        if audit_user not in user_names:
            client.createUser(
                audit_user,
                audit_password,
                PERMISSION_RW,
                database.encode("utf-8"),
            )
    finally:
        client.shutdown()


if __name__ == "__main__":
    main()
