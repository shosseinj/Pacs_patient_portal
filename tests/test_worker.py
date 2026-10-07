import time
import uuid
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from portal.models import UploadJob, Instance, Study, JobInstance
from portal.worker import process_once
from tests.conftest import login, csrf
from tests.dicom_factory import make_dicom, STUDY


class MemoryArchive:
    def __init__(self):
        self.items = {}
        self.fail = False

    def put(self, item):
        if self.fail:
            raise RuntimeError("archive unavailable")
        if item.sop_uid in self.items and self.items[item.sop_uid] != item.sha256:
            raise ValueError("SOP conflict")
        self.items[item.sop_uid] = item.sha256
        return "archive-" + item.sop_uid


def stage(app, files, patient=1, status="queued", updated=None):
    job_id = str(uuid.uuid4())
    directory = app.state.settings.upload_dir / job_id
    directory.mkdir()
    names = []
    for index, file in enumerate(files):
        name = f"input-{index}"
        (directory / name).write_bytes(file.read_bytes())
        names.append(name)
    with Session(app.state.engine) as db:
        db.add(
            UploadJob(
                id=job_id,
                patient_id=patient,
                uploader_id=2,
                files=names,
                source_names=["demo.dcm"],
                status=status,
                updated_at=updated or time.time(),
            )
        )
        db.commit()
    return job_id


def status(app, job_id):
    with Session(app.state.engine) as db:
        return db.get(UploadJob, job_id).status


def run(app, archive):
    return process_once(app.state.settings, app.state.engine, archive)


def test_valid_identity_requires_explicit_release(app, client, tmp_path):
    job = stage(app, [make_dicom(tmp_path / "one.dcm")])
    assert run(app, MemoryArchive())
    assert status(app, job) == "ready"
    with Session(app.state.engine) as db:
        assert not db.get(Study, STUDY).published
        assert not db.scalar(select(Instance)).published
    login(client)
    assert (
        client.post(
            f"/portal/jobs/{job}/publish", data={"csrf": csrf(client)}, follow_redirects=False
        ).status_code
        == 303
    )
    with TestClient(app) as patient:
        login(patient, "patient1")
        assert patient.get(f"/portal/studies/{STUDY}/view").status_code == 200


@pytest.mark.parametrize("patient_id", ["OTHER", ""])
def test_mismatched_or_missing_identity_is_quarantined(app, client, tmp_path, patient_id):
    job = stage(app, [make_dicom(tmp_path / "one.dcm", patient_id=patient_id)])
    assert run(app, MemoryArchive())
    assert status(app, job) == "needs_review"
    login(client)
    assert (
        client.post(
            f"/portal/jobs/{job}/publish",
            data={"csrf": csrf(client), "reason": "verified at reception"},
            follow_redirects=False,
        ).status_code
        == 403
    )
    with TestClient(app) as admin:
        login(admin, "admin")
        assert (
            admin.post(
                f"/portal/jobs/{job}/publish",
                data={"csrf": csrf(admin), "reason": "short"},
                follow_redirects=False,
            ).status_code
            == 400
        )
        assert (
            admin.post(
                f"/portal/jobs/{job}/publish",
                data={"csrf": csrf(admin), "reason": "verified at reception"},
                follow_redirects=False,
            ).status_code
            == 303
        )


def test_mixed_patient_batch_fails_before_archive_write(app, tmp_path):
    job = stage(app, [make_dicom(tmp_path / "one.dcm"), make_dicom(tmp_path / "two.dcm", patient_id="OTHER")])
    archive = MemoryArchive()
    assert run(app, archive)
    assert status(app, job) == "failed" and not archive.items


def test_duplicate_identical_upload_is_idempotent(app, tmp_path):
    file = make_dicom(tmp_path / "one.dcm")
    archive = MemoryArchive()
    first = stage(app, [file])
    run(app, archive)
    second = stage(app, [file])
    run(app, archive)
    assert status(app, first) == status(app, second) == "ready"
    with Session(app.state.engine) as db:
        assert db.scalar(select(func.count(Instance.uid))) == 1
        assert db.scalar(select(func.count(JobInstance.job_id))) == 2


def test_existing_sop_with_different_bytes_is_rejected(app, tmp_path):
    file = make_dicom(tmp_path / "one.dcm", sop_uid=STUDY + ".50")
    archive = MemoryArchive()
    stage(app, [file])
    run(app, archive)
    file = make_dicom(tmp_path / "other.dcm", sop_uid=STUDY + ".50", patient_id="OTHER")
    job = stage(app, [file])
    run(app, archive)
    assert status(app, job) == "failed"
    assert len(archive.items) == 1


def test_study_cannot_be_reassigned_to_another_patient(app, tmp_path):
    archive = MemoryArchive()
    stage(app, [make_dicom(tmp_path / "one.dcm")])
    run(app, archive)
    job = stage(app, [make_dicom(tmp_path / "two.dcm", sop_uid=STUDY + ".1.2")], patient=2)
    run(app, archive)
    assert status(app, job) == "failed"
    with Session(app.state.engine) as db:
        assert db.get(Study, STUDY).patient_id == 1


def test_failed_import_can_resume_without_duplicate_records(app, client, tmp_path):
    archive = MemoryArchive()
    archive.fail = True
    job = stage(app, [make_dicom(tmp_path / "one.dcm")])
    run(app, archive)
    assert status(app, job) == "failed"
    login(client)
    assert (
        client.post(
            f"/portal/jobs/{job}/retry", data={"csrf": csrf(client)}, follow_redirects=False
        ).status_code
        == 303
    )
    archive.fail = False
    run(app, archive)
    assert status(app, job) == "ready"


def test_crashed_processing_job_is_recovered(app, tmp_path):
    job = stage(app, [make_dicom(tmp_path / "one.dcm")], status="processing", updated=time.time() - 1000)
    assert run(app, MemoryArchive())
    assert status(app, job) == "ready"


def test_no_work_returns_false(app):
    assert run(app, MemoryArchive()) is False


def test_added_images_are_not_implicitly_released(app, client, tmp_path):
    archive = MemoryArchive()
    first = stage(app, [make_dicom(tmp_path / "one.dcm")])
    run(app, archive)
    login(client)
    client.post(f"/portal/jobs/{first}/publish", data={"csrf": csrf(client)}, follow_redirects=False)
    second = stage(app, [make_dicom(tmp_path / "two.dcm", sop_uid=STUDY + ".1.2")])
    run(app, archive)
    assert status(app, second) == "ready"
    with Session(app.state.engine) as db:
        assert db.get(Study, STUDY).published
        assert len(db.scalars(select(Instance).where(Instance.published.is_(False))).all()) == 1
