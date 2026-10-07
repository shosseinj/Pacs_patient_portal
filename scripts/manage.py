import argparse
import getpass
from sqlalchemy import select
from sqlalchemy.orm import Session
from portal.auth import hash_password, valid_username, revoke_sessions, audit
from portal.config import Settings
from portal.db import make_engine
from portal.models import User


def main():
    parser = argparse.ArgumentParser(description="Server-side account administration")
    parser.add_argument("action", choices=["create-admin", "reset-password", "disable", "enable"])
    parser.add_argument("--username", required=True)
    parser.add_argument("--name", default="مدیر مرکز")
    args = parser.parse_args()
    username = valid_username(args.username)
    engine = make_engine(Settings.from_env().database_url)
    with Session(engine) as db:
        user = db.scalar(select(User).where(User.username == username))
        if args.action == "create-admin":
            if user:
                parser.error("Username already exists")
            user = User(username=username, display_name=args.name[:120], role="admin", password_hash="")
            db.add(user)
        elif not user:
            parser.error("User not found")
        if args.action in {"create-admin", "reset-password"}:
            password = getpass.getpass("New password (at least 12 characters): ")
            if password != getpass.getpass("Repeat password: "):
                parser.error("Passwords differ")
            user.password_hash = hash_password(password)
        elif args.action == "disable":
            active_admins = db.scalars(select(User).where(User.role == "admin", User.active.is_(True))).all()
            if user.role == "admin" and user.active and len(active_admins) <= 1:
                parser.error("Cannot disable the last active administrator")
            user.active = False
        else:
            user.active = True
        db.flush()
        revoke_sessions(db, user.id)
        audit(db, None, "account_" + args.action, user.id)
        db.commit()
    print("Account updated; existing sessions revoked.")


if __name__ == "__main__":
    main()
