import logging
import time
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from portal.auth import audit
from portal.config import Settings
from portal.db import make_engine
from portal.dicom import validate_batch, DicomValidationError
from portal.models import UploadJob, Patient, Study, Instance, JobInstance
from portal.orthanc import OrthancArchive

log = logging.getLogger(__name__)


def process_once(settings, engine, archive):
    with Session(engine) as db:
        db.execute(
            update(UploadJob)
            .where(UploadJob.status == "processing", UploadJob.updated_at < time.time() - 600)
            .values(status="queued", updated_at=time.time())
        )
        candidate = db.scalar(
            select(UploadJob.id).where(UploadJob.status == "queued").order_by(UploadJob.created_at).limit(1)
        )
        if not candidate:
            db.commit()
            return False
        claimed = db.execute(
            update(UploadJob)
            .where(UploadJob.id == candidate, UploadJob.status == "queued")
            .values(status="processing", processed=0, error="", updated_at=time.time())
        )
        db.commit()
        if not claimed.rowcount:
            return False
        job = db.get(UploadJob, candidate)
        files = [settings.upload_dir / job.id / name for name in job.files]
        patient_id = job.patient_id
    try:
        items = validate_batch(
            files,
            settings.upload_dir / candidate / "expanded",
            settings.max_files,
            settings.max_upload_bytes,
            settings.max_instance_bytes,
        )
        with Session(engine) as db:
            job = db.get(UploadJob, candidate)
            patient = db.get(Patient, patient_id)
            observed = items[0]
            job.total = len(items)
            job.observed_id, job.observed_issuer, job.observed_name = (
                observed.patient_id[:64],
                observed.issuer[:64],
                observed.patient_name[:120],
            )
            matches = bool(
                patient.dicom_id
                and observed.patient_id == patient.dicom_id
                and observed.issuer == patient.issuer
            )
            # Validate the whole batch against portal state before sending any file to Orthanc.
            for item in items:
                study = db.get(Study, item.study_uid)
                if study and (
                    study.patient_id != patient_id
                    or (study.dicom_id, study.issuer) != (item.patient_id, item.issuer)
                ):
                    raise DicomValidationError("مطالعه قبلاً به پرونده یا هویت دیگری متصل شده است.")
                existing = db.get(Instance, item.sop_uid)
                if existing and (
                    existing.sha256 != item.sha256
                    or existing.study_uid != item.study_uid
                    or existing.series_uid != item.series_uid
                ):
                    raise DicomValidationError("شناسهٔ تصویر با محتوای متفاوت قبلاً ثبت شده است.")
                if db.scalar(
                    select(Instance.uid)
                    .where(Instance.series_uid == item.series_uid, Instance.study_uid != item.study_uid)
                    .limit(1)
                ):
                    raise DicomValidationError("شناسهٔ سری در مطالعهٔ دیگری استفاده شده است.")
            job.updated_at = time.time()
            db.commit()
        for index, item in enumerate(items, 1):
            archive_id = archive.put(item)
            with Session(engine) as db:
                study = db.get(Study, item.study_uid)
                if not study:
                    db.add(
                        Study(
                            uid=item.study_uid,
                            patient_id=patient_id,
                            dicom_id=item.patient_id,
                            issuer=item.issuer,
                            description=item.description,
                            modality=item.modality,
                            study_date=item.study_date,
                        )
                    )
                    db.flush()
                instance = db.get(Instance, item.sop_uid)
                if not instance:
                    db.add(
                        Instance(
                            uid=item.sop_uid,
                            study_uid=item.study_uid,
                            series_uid=item.series_uid,
                            sha256=item.sha256,
                            orthanc_id=archive_id,
                        )
                    )
                    db.flush()
                if not db.get(JobInstance, (candidate, item.sop_uid)):
                    db.add(JobInstance(job_id=candidate, instance_uid=item.sop_uid))
                job = db.get(UploadJob, candidate)
                job.processed, job.updated_at = index, time.time()
                db.commit()
        with Session(engine) as db:
            job = db.get(UploadJob, candidate)
            job.status, job.updated_at = ("ready" if matches else "needs_review"), time.time()
            audit(db, None, "upload_processed", candidate, job.status)
            db.commit()
    except Exception as exc:
        log.error("Upload %s failed: %s", candidate, type(exc).__name__)
        with Session(engine) as db:
            job = db.get(UploadJob, candidate)
            job.status, job.updated_at = "failed", time.time()
            job.error = (
                str(exc)
                if isinstance(exc, DicomValidationError)
                else "پردازش کامل نشد؛ اتصال آرشیو، فضای دیسک و فایل‌ها را بررسی و دوباره تلاش کنید."
            )
            audit(db, None, "upload_failed", candidate, job.error)
            db.commit()
    return True


def main():
    logging.basicConfig(level=logging.INFO)
    settings = Settings.from_env()
    engine = make_engine(settings.database_url)
    archive = OrthancArchive(settings)
    try:
        while True:
            if not process_once(settings, engine, archive):
                time.sleep(2)
    finally:
        archive.close()


if __name__ == "__main__":
    main()
