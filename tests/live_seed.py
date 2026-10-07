"""Explicit opt-in fixture setup for an EMPTY, loopback-only test database."""

import argparse
import os
from urllib.parse import urlsplit
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from portal.auth import hash_password
from portal.config import Settings
from portal.db import make_engine
from portal.models import User, Patient


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm-empty-test-db", action="store_true", required=True)
    parser.parse_args()
    settings = Settings.from_env()
    if urlsplit(settings.public_url).hostname not in {"localhost", "127.0.0.1"}:
        parser.error("Only a loopback test origin is allowed")
    password = os.environ.get("PACS_TEST_PASSWORD", "")
    if len(password) < 12:
        parser.error("Set PACS_TEST_PASSWORD to at least 12 characters")
    with Session(make_engine(settings.database_url)) as db:
        if db.scalar(select(func.count(User.id))):
            parser.error("Database is not empty; refusing fixture creation")
        encoded = hash_password(password)
        for username, role in [
            ("admin.live", "admin"),
            ("operator.live", "operator"),
            ("patient.live", "patient"),
            ("other.live", "patient"),
        ]:
            db.add(User(username=username, display_name=username, password_hash=encoded, role=role))
        db.flush()
        db.add_all(
            [
                Patient(
                    name="بیمار آزمایشی",
                    record_number="DEMO-LIVE",
                    dicom_id="DEMO001",
                    issuer="DEMO",
                    user_id=3,
                ),
                Patient(
                    name="بیمار آزمایشی دوم",
                    record_number="OTHER-LIVE",
                    dicom_id="OTHER",
                    issuer="DEMO",
                    user_id=4,
                ),
            ]
        )
        db.commit()
    print("Isolated synthetic fixture users created.")


if __name__ == "__main__":
    main()
