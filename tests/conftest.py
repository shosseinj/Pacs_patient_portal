import re
import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from portal.app import create_app
from portal.config import Settings
from portal.models import User, Patient

PASSWORD = "Strong-test-password42!"


@pytest.fixture
def app(tmp_path):
    settings = Settings(
        secret="test-secret-" * 6,
        database_url="sqlite:///" + str(tmp_path / "portal.db"),
        upload_dir=tmp_path / "uploads",
        login_limit=3,
    )
    application = create_app(settings)
    password_hash = PasswordHasher(time_cost=1, memory_cost=8192, parallelism=1).hash(PASSWORD)
    with Session(application.state.engine) as db:
        for name, role in [
            ("admin", "admin"),
            ("operator", "operator"),
            ("patient1", "patient"),
            ("patient2", "patient"),
        ]:
            db.add(User(username=name, display_name=name, password_hash=password_hash, role=role))
        db.flush()
        db.add(
            Patient(
                name="بیمار آزمایشی یک", record_number="P001", dicom_id="DEMO001", issuer="CLINIC", user_id=3
            )
        )
        db.add(
            Patient(
                name="بیمار آزمایشی دو", record_number="P002", dicom_id="OTHER", issuer="CLINIC", user_id=4
            )
        )
        db.commit()
    return application


def csrf(client):
    response = client.get("/portal/login" if not client.cookies.get("pacs_session") else "/portal")
    match = re.search(r'name="csrf" value="([^"]+)"', response.text)
    return match.group(1) if match else "missing"


def login(client, username="operator", password=PASSWORD):
    token = csrf(client)
    return client.post(
        "/portal/login",
        data={"username": username, "password": password, "csrf": token},
        follow_redirects=False,
    )


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c
