from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
from portal.models import SessionToken, Patient, UploadJob
from tests.conftest import csrf, login, PASSWORD
from tests.dicom_factory import make_dicom


def test_password_whitespace_from_account_cli_is_preserved(client, app):
    from portal.auth import hash_password
    from portal.models import User

    password = "  Strong-test-password42!  "
    with Session(app.state.engine) as db:
        db.scalar(select(User).where(User.username == "operator")).password_hash = hash_password(password)
        db.commit()
    assert login(client, password=password).status_code == 303


def test_login_session_and_logout_revoke_access(client, app):
    assert login(client).status_code == 303
    assert client.get("/api/session").status_code == 200
    token = csrf(client)
    assert client.post("/portal/logout", data={"csrf": token}, follow_redirects=False).status_code == 303
    assert client.get("/api/session").status_code == 401
    with Session(app.state.engine) as db:
        assert db.scalar(select(SessionToken)) is None


def test_login_requires_csrf(client):
    assert (
        client.post(
            "/portal/login", data={"username": "operator", "password": PASSWORD, "csrf": "bad"}
        ).status_code
        == 403
    )


def test_wrong_password_is_throttled(client):
    for _ in range(3):
        assert login(client, password="wrong").status_code == 401
    assert login(client).status_code == 429


def test_session_expiry_denies_access(client, app):
    assert login(client).status_code == 303
    with Session(app.state.engine) as db:
        db.scalar(select(SessionToken)).expires_at = 0
        db.commit()
    assert client.get("/api/session").status_code == 401


def test_patient_cannot_create_or_upload(client):
    assert login(client, "patient1").status_code == 303
    assert client.get("/portal/patients/new").status_code == 403
    assert client.post("/portal/uploads", data={"patient_id": 1, "csrf": csrf(client)}).status_code == 403


def test_operator_can_create_patient_account(client, app):
    assert login(client).status_code == 303
    response = client.post(
        "/portal/patients/new",
        data={
            "csrf": csrf(client),
            "name": "بیمار جدید",
            "record_number": "P003",
            "dicom_id": "NEW003",
            "issuer": "CLINIC",
            "username": "patient3",
            "password": PASSWORD,
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    with Session(app.state.engine) as db:
        assert db.scalar(select(Patient).where(Patient.record_number == "P003")) is not None
    with TestClient(app) as other:
        assert login(other, "patient3").status_code == 303


def test_create_patient_requires_csrf(client):
    assert login(client).status_code == 303
    assert client.post("/portal/patients/new", data={"csrf": "bad"}).status_code == 403


def test_upload_is_staged_as_durable_job(client, app, tmp_path):
    assert login(client).status_code == 303
    file = make_dicom(tmp_path / "one.dcm")
    response = client.post(
        "/portal/uploads",
        data={"patient_id": "1", "csrf": csrf(client)},
        files=[("files", ("one.dcm", file.read_bytes(), "application/dicom"))],
        headers={"Accept": "application/json"},
    )
    assert response.status_code == 202
    job_id = response.json()["job_id"]
    with Session(app.state.engine) as db:
        job = db.get(UploadJob, job_id)
        assert job.status == "queued"
        assert (app.state.settings.upload_dir / job_id / job.files[0]).exists()
    assert client.get("/api/jobs/" + job_id).json()["status"] == "queued"


def test_patient_cannot_see_other_patient_page(client):
    assert login(client, "patient1").status_code == 303
    assert client.get("/portal/patients/2").status_code == 404


def test_state_changing_request_from_foreign_origin_is_blocked(client):
    assert login(client).status_code == 303
    assert (
        client.post(
            "/portal/logout", data={"csrf": csrf(client)}, headers={"Origin": "https://evil.example"}
        ).status_code
        == 403
    )
