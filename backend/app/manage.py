"""Account administration from the command line (inside the API container or the backend folder).

    python -m app.manage create-user --email you@example.com --role ADMIN
    python -m app.manage set-role --email someone@example.com --role MODEL_ENGINEER
    python -m app.manage disable --email someone@example.com

The password is read from CHAKRAVYUH_NEW_USER_PASSWORD if set (for scripts), otherwise prompted.
It is never accepted as a command-line argument, so it can't end up in shell history or `ps`.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys

from sqlalchemy import select

from .db import SessionLocal, init_db
from .models import User
from .security import tokens
from .security.rbac import Role
from .services.users import UserError, create_user, normalise_email


def main() -> int:
    ap = argparse.ArgumentParser(prog="python -m app.manage")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create-user")
    c.add_argument("--email", required=True)
    c.add_argument("--role", default="ANALYST", choices=[r.value for r in Role])
    s = sub.add_parser("set-role")
    s.add_argument("--email", required=True)
    s.add_argument("--role", required=True, choices=[r.value for r in Role])
    d = sub.add_parser("disable")
    d.add_argument("--email", required=True)
    args = ap.parse_args()

    init_db()
    with SessionLocal() as db:
        if args.cmd == "create-user":
            pw = os.getenv("CHAKRAVYUH_NEW_USER_PASSWORD") or getpass.getpass("Password (12+ characters): ")
            try:
                u = create_user(db, args.email, pw, args.role)
            except UserError as e:
                print(f"error: {e}", file=sys.stderr)
                return 1
            print(f"created {u.email} ({u.role})")
            return 0
        u = db.scalar(select(User).where(User.email == normalise_email(args.email)))
        if u is None:
            print("error: no such user", file=sys.stderr)
            return 1
        if args.cmd == "set-role":
            u.role = args.role
        else:
            u.status = "disabled"
        db.commit()
        tokens.revoke_all(db, u.id)
        print(f"{u.email}: role={u.role} status={u.status} (signed out everywhere)")
        return 0


if __name__ == "__main__":
    sys.exit(main())
