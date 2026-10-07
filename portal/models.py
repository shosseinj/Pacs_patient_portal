import time
from sqlalchemy import Boolean, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    display_name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(16))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Patient(Base):
    __tablename__ = "patients"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    record_number: Mapped[str] = mapped_column(String(64), unique=True)
    dicom_id: Mapped[str] = mapped_column(String(64), default="")
    issuer: Mapped[str] = mapped_column(String(64), default="")
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)


class SessionToken(Base):
    __tablename__ = "sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    csrf: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[float] = mapped_column(Float)


class LoginAttempt(Base):
    __tablename__ = "login_attempts"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    failures: Mapped[int] = mapped_column(Integer, default=0)
    window_start: Mapped[float] = mapped_column(Float, default=time.time)


class Study(Base):
    __tablename__ = "studies"
    uid: Mapped[str] = mapped_column(String(64), primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"))
    dicom_id: Mapped[str] = mapped_column(String(64))
    issuer: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(String(160), default="")
    modality: Mapped[str] = mapped_column(String(16))
    study_date: Mapped[str] = mapped_column(String(8), default="")
    published: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class Instance(Base):
    __tablename__ = "instances"
    uid: Mapped[str] = mapped_column(String(64), primary_key=True)
    study_uid: Mapped[str] = mapped_column(ForeignKey("studies.uid"))
    series_uid: Mapped[str] = mapped_column(String(64))
    sha256: Mapped[str] = mapped_column(String(64))
    orthanc_id: Mapped[str] = mapped_column(String(64))
    published: Mapped[bool] = mapped_column(Boolean, default=False)


class UploadJob(Base):
    __tablename__ = "upload_jobs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"))
    uploader_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(24), default="queued")
    files: Mapped[list] = mapped_column(JSON, default=list)
    source_names: Mapped[list] = mapped_column(JSON, default=list)
    total: Mapped[int] = mapped_column(Integer, default=0)
    processed: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str] = mapped_column(Text, default="")
    observed_id: Mapped[str] = mapped_column(String(64), default="")
    observed_issuer: Mapped[str] = mapped_column(String(64), default="")
    observed_name: Mapped[str] = mapped_column(String(120), default="")
    created_at: Mapped[float] = mapped_column(Float, default=time.time)
    updated_at: Mapped[float] = mapped_column(Float, default=time.time)


class JobInstance(Base):
    __tablename__ = "job_instances"
    job_id: Mapped[str] = mapped_column(ForeignKey("upload_jobs.id"), primary_key=True)
    instance_uid: Mapped[str] = mapped_column(ForeignKey("instances.uid"), primary_key=True)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(64))
    target: Mapped[str] = mapped_column(String(80), default="")
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[float] = mapped_column(Float, default=time.time)
