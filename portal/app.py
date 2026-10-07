import secrets
import shutil
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from sqlalchemy import select, func, delete, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile
from starlette.middleware.trustedhost import TrustedHostMiddleware
from portal import auth
from portal.config import Settings
from portal.db import make_engine
from portal.models import (
    User,
    Patient,
    Study,
    Instance,
    UploadJob,
    JobInstance,
    SessionToken,
    LoginAttempt,
    AuditEvent,
)

ROOT = Path(__file__).parent
STATUSES = {
    "queued": "در صف پردازش",
    "processing": "در حال پردازش",
    "ready": "آمادهٔ تأیید",
    "needs_review": "نیازمند بررسی هویت",
    "failed": "ناموفق",
    "published": "منتشرشده",
}


def create_app(settings):
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = settings
    app.state.engine = engine = make_engine(settings.database_url)
    settings.upload_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    templates = Jinja2Templates(directory=ROOT / "templates")
    app.mount("/portal/static", StaticFiles(directory=ROOT / "static"), name="static")
    signer = URLSafeTimedSerializer(settings.secret, salt="login-csrf")
    allowed_hosts = [urlparse(settings.public_url).hostname, "localhost", "127.0.0.1"]
    if not settings.secure_cookies:
        allowed_hosts.append("testserver")
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)

    def render(request, name, user=None, token=None, status_code=200, **values):
        return templates.TemplateResponse(
            request=request,
            name=name + ".html",
            status_code=status_code,
            context={"user": user, "csrf": token.csrf if token else "", "statuses": STATUSES, **values},
        )

    def field(form, name, maximum=120, required=True, strip=True):
        value = form.get(name, "")
        if not isinstance(value, str):
            raise HTTPException(400, "فیلد نامعتبر است.")
        if strip:
            value = value.strip()
        if len(value) > maximum or (required and not value):
            raise HTTPException(400, f"مقدار {name} خالی یا بیش از حد طولانی است.")
        return value

    @app.middleware("http")
    async def security_headers(request, call_next):
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            if request.headers.get("origin") and request.headers["origin"] != settings.public_url:
                return JSONResponse({"detail": "درخواست از مبدأ دیگری مجاز نیست."}, status_code=403)
            length = request.headers.get("content-length", "")
            if length.isdigit() and int(length) > settings.max_upload_bytes + 10_000_000:
                return JSONResponse({"detail": "حجم درخواست بیش از سقف مجاز است."}, status_code=413)
        response = await call_next(request)
        response.headers.update(
            {
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "same-origin",
                "X-Frame-Options": "SAMEORIGIN",
            }
        )
        if request.url.path.startswith("/portal"):
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; frame-src 'self'; frame-ancestors 'self'; base-uri 'none'; form-action 'self'"
            )
        return response

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        if request.url.path.startswith(("/api", "/dicom-web")) or "application/json" in request.headers.get(
            "accept", ""
        ):
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
        return render(request, "error", status_code=exc.status_code, code=exc.status_code, message=exc.detail)

    @app.get("/health")
    def health():
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ok"}

    @app.get("/portal/login")
    def login_page(request: Request):
        value = signer.dumps(secrets.token_hex(32))
        dev_login = (
            not settings.secure_cookies
            and urlparse(settings.public_url).hostname in {"localhost", "127.0.0.1"}
            and settings.dev_login_username
            and settings.dev_login_password
        )
        response = render(
            request,
            "login",
            login_csrf=value,
            dev_username=settings.dev_login_username if dev_login else "",
            dev_password=settings.dev_login_password if dev_login else "",
        )
        response.set_cookie(
            "login_csrf",
            value,
            max_age=3600,
            httponly=True,
            secure=settings.secure_cookies,
            samesite="strict",
            path="/portal/login",
        )
        return response

    @app.post("/portal/login")
    async def login(request: Request):
        form = await request.form(max_files=0, max_fields=5)
        submitted = field(form, "csrf", 300)
        if not secrets.compare_digest(submitted, request.cookies.get("login_csrf", "")):
            raise HTTPException(403, "توکن ورود معتبر نیست.")
        try:
            signer.loads(submitted, max_age=3600)
        except (BadSignature, SignatureExpired):
            raise HTTPException(403, "صفحهٔ ورود منقضی شده است.")
        username, password = field(form, "username", 64).lower(), field(form, "password", 1024, strip=False)
        key = auth.token_hash(username + "|" + (request.client.host if request.client else "unknown"))
        with Session(engine) as db:
            attempt = db.get(LoginAttempt, key)
            if not attempt:
                attempt = LoginAttempt(key=key, failures=0, window_start=time.time())
                db.add(attempt)
            if attempt.window_start < time.time() - 900:
                attempt.window_start, attempt.failures = time.time(), 0
            if attempt.failures >= settings.login_limit:
                raise HTTPException(429, "تلاش‌های ورود زیاد است؛ ۱۵ دقیقه بعد دوباره تلاش کنید.")
            user = db.scalar(select(User).where(User.username == username))
            valid = auth.verify_password(user.password_hash if user else auth.DUMMY_HASH, password)
            if not valid or not user or not user.active:
                attempt.failures += 1
                db.commit()
                raise HTTPException(401, "نام کاربری یا گذرواژه نادرست است.")
            attempt.failures = 0
            db.execute(delete(SessionToken).where(SessionToken.expires_at < time.time()))
            old = db.get(SessionToken, auth.token_hash(request.cookies.get(auth.COOKIE, "")))
            if old:
                db.delete(old)
            raw = secrets.token_urlsafe(40)
            db.add(
                SessionToken(
                    token_hash=auth.token_hash(raw),
                    user_id=user.id,
                    csrf=secrets.token_hex(32),
                    expires_at=time.time() + settings.session_seconds,
                )
            )
            auth.audit(db, user.id, "login")
            db.commit()
        response = RedirectResponse("/portal", 303)
        response.set_cookie(
            auth.COOKIE,
            raw,
            max_age=settings.session_seconds,
            httponly=True,
            secure=settings.secure_cookies,
            samesite="lax",
            path="/",
        )
        response.delete_cookie("login_csrf", path="/portal/login")
        return response

    @app.post("/portal/logout")
    async def logout(request: Request):
        form = await request.form(max_files=0)
        with Session(engine) as db:
            user, token = auth.identity(request, db)
            auth.check_csrf(token, form)
            auth.audit(db, user.id, "logout")
            db.delete(token)
            db.commit()
        response = RedirectResponse("/portal/login", 303)
        response.delete_cookie(auth.COOKIE, path="/")
        return response

    @app.get("/api/session")
    def session_info(request: Request):
        with Session(engine) as db:
            user, _ = auth.identity(request, db)
            return {"role": user.role}

    @app.get("/portal")
    def home(request: Request):
        with Session(engine) as db:
            try:
                user, token = auth.identity(request, db)
            except HTTPException:
                return RedirectResponse("/portal/login", 303)
            if user.role == "patient":
                patient = db.scalar(select(Patient).where(Patient.user_id == user.id))
                studies = db.scalars(
                    select(Study)
                    .where(Study.patient_id == patient.id, Study.published.is_(True))
                    .order_by(Study.created_at.desc())
                ).all()
                return render(request, "patient", user, token, patient=patient, studies=studies, jobs=[])
            auth.staff(user)
            return render(
                request,
                "dashboard",
                user,
                token,
                patients=db.scalars(select(Patient).order_by(Patient.id.desc())).all(),
                jobs=db.scalars(select(UploadJob).order_by(UploadJob.created_at.desc()).limit(15)).all(),
                patient_count=db.scalar(select(func.count(Patient.id))),
                study_count=db.scalar(select(func.count(Study.uid))),
                pending=db.scalar(
                    select(func.count(UploadJob.id)).where(
                        UploadJob.status.in_(["queued", "processing", "ready", "needs_review"])
                    )
                ),
            )

    @app.get("/portal/patients/new")
    def patient_form(request: Request):
        with Session(engine) as db:
            user, token = auth.identity(request, db)
            auth.staff(user)
            return render(request, "patient_form", user, token)

    @app.post("/portal/patients/new")
    async def create_patient(request: Request):
        with Session(engine) as db:
            user, token = auth.identity(request, db)
            auth.staff(user)
            form = await request.form(max_files=0, max_fields=10)
            auth.check_csrf(token, form)
            name, record = field(form, "name"), field(form, "record_number", 64)
            new_user = User(
                username=auth.valid_username(field(form, "username", 64)),
                display_name=name,
                password_hash=auth.hash_password(field(form, "password", 1024, strip=False)),
                role="patient",
            )
            db.add(new_user)
            try:
                db.flush()
                patient = Patient(
                    name=name,
                    record_number=record,
                    dicom_id=field(form, "dicom_id", 64, False),
                    issuer=field(form, "issuer", 64, False),
                    user_id=new_user.id,
                )
                db.add(patient)
                db.flush()
                auth.audit(db, user.id, "patient_created", patient.id)
                target = patient.id
                db.commit()
            except IntegrityError:
                db.rollback()
                raise HTTPException(409, "نام کاربری یا شمارهٔ پرونده قبلاً ثبت شده است.")
        return RedirectResponse(f"/portal/patients/{target}", 303)

    @app.get("/portal/patients/{patient_id}")
    def patient_page(patient_id: int, request: Request):
        with Session(engine) as db:
            user, token = auth.identity(request, db)
            patient = db.get(Patient, patient_id)
            if not patient or (user.role == "patient" and patient.user_id != user.id):
                raise HTTPException(404, "پرونده پیدا نشد.")
            query = select(Study).where(Study.patient_id == patient.id).order_by(Study.created_at.desc())
            if user.role == "patient":
                query = query.where(Study.published.is_(True))
            jobs = (
                []
                if user.role == "patient"
                else db.scalars(
                    select(UploadJob)
                    .where(UploadJob.patient_id == patient.id)
                    .order_by(UploadJob.created_at.desc())
                    .limit(20)
                ).all()
            )
            return render(
                request, "patient", user, token, patient=patient, studies=db.scalars(query).all(), jobs=jobs
            )

    @app.post("/portal/uploads")
    async def upload(request: Request):
        with Session(engine) as db:
            user, token = auth.identity(request, db)
            auth.staff(user)
            form = await request.form(max_files=settings.max_files, max_fields=5, max_part_size=1024 * 1024)
            auth.check_csrf(token, form)
            try:
                patient_id = int(field(form, "patient_id", 12))
            except ValueError:
                raise HTTPException(400, "شمارهٔ پرونده نامعتبر است.")
            if not db.get(Patient, patient_id):
                raise HTTPException(404, "پرونده پیدا نشد.")
            active = db.scalar(
                select(func.count(UploadJob.id)).where(UploadJob.status.in_(["queued", "processing"]))
            )
            if active >= 5:
                raise HTTPException(429, "صف آپلود پر است؛ کمی بعد دوباره تلاش کنید.")
            files = form.getlist("files")
            if not files or not all(isinstance(f, UploadFile) for f in files):
                raise HTTPException(400, "حداقل یک فایل انتخاب کنید.")
            job_id = str(uuid.uuid4())
            directory = settings.upload_dir / job_id
            directory.mkdir(mode=0o700)
            names, sources, total = [], [], 0
            try:
                for file in files:
                    if Path(file.filename or "").name.upper() == "DICOMDIR":
                        continue
                    target = f"input-{len(names):06d}"
                    size = 0
                    with (directory / target).open("wb") as out:
                        while chunk := await file.read(1024 * 1024):
                            total += len(chunk)
                            size += len(chunk)
                            if total > settings.max_upload_bytes:
                                raise HTTPException(413, "حجم آپلود بیش از سقف مجاز است.")
                            out.write(chunk)
                    if not size:
                        raise HTTPException(400, "فایل خالی است.")
                    names.append(target)
                    sources.append(Path((file.filename or "file").replace("\\", "/")).name[:160])
                if not names:
                    raise HTTPException(400, "تصویر DICOM انتخاب نشده است.")
                job = UploadJob(
                    id=job_id, patient_id=patient_id, uploader_id=user.id, files=names, source_names=sources
                )
                db.add(job)
                auth.audit(db, user.id, "upload_queued", job_id)
                db.commit()
            except Exception:
                db.rollback()
                shutil.rmtree(directory, ignore_errors=True)
                raise
            finally:
                for file in files:
                    await file.close()
        if "application/json" in request.headers.get("accept", ""):
            return JSONResponse({"job_id": job_id}, 202)
        return RedirectResponse("/portal/jobs/" + job_id, 303)

    @app.get("/portal/jobs/{job_id}")
    def job_page(job_id: str, request: Request):
        with Session(engine) as db:
            user, token = auth.identity(request, db)
            auth.staff(user)
            job = db.get(UploadJob, job_id)
            if not job:
                raise HTTPException(404, "آپلود پیدا نشد.")
            studies = db.scalars(
                select(Study)
                .join(Instance, Instance.study_uid == Study.uid)
                .join(JobInstance, JobInstance.instance_uid == Instance.uid)
                .where(JobInstance.job_id == job.id)
                .distinct()
            ).all()
            return render(
                request, "job", user, token, job=job, patient=db.get(Patient, job.patient_id), studies=studies
            )

    @app.get("/api/jobs/{job_id}")
    def job_status(job_id: str, request: Request):
        with Session(engine) as db:
            user, _ = auth.identity(request, db)
            auth.staff(user)
            job = db.get(UploadJob, job_id)
            if not job:
                raise HTTPException(404, "آپلود پیدا نشد.")
            return {
                "status": job.status,
                "label": STATUSES.get(job.status, job.status),
                "processed": job.processed,
                "total": job.total,
                "error": job.error,
            }

    @app.post("/portal/jobs/{job_id}/publish")
    async def publish(job_id: str, request: Request):
        with Session(engine) as db:
            user, token = auth.identity(request, db)
            auth.staff(user)
            form = await request.form(max_files=0, max_fields=3)
            auth.check_csrf(token, form)
            job = db.scalar(select(UploadJob).where(UploadJob.id == job_id).with_for_update())
            if not job:
                raise HTTPException(404, "آپلود پیدا نشد.")
            if job.status not in {"ready", "needs_review"}:
                raise HTTPException(409, "این آپلود آمادهٔ انتشار نیست.")
            reason = field(form, "reason", 1000, False)
            if job.status == "needs_review":
                auth.staff(user, admin=True)
                if len(reason) < 12:
                    raise HTTPException(400, "علت تأیید هویت را با حداقل ۱۲ نویسه ثبت کنید.")
            instances = db.scalars(
                select(Instance).join(JobInstance).where(JobInstance.job_id == job_id)
            ).all()
            if not instances or len(instances) != job.total or job.processed != job.total:
                raise HTTPException(409, "پردازش تصاویر کامل نشده است.")
            for item in instances:
                study = db.get(Study, item.study_uid)
                if study.patient_id != job.patient_id:
                    raise HTTPException(409, "انتساب مطالعه ناسازگار است.")
                item.published, study.published = True, True
            job.status, job.updated_at = "published", time.time()
            auth.audit(db, user.id, "published", job_id, reason)
            db.commit()
        return RedirectResponse("/portal/jobs/" + job_id, 303)

    @app.post("/portal/jobs/{job_id}/retry")
    async def retry(job_id: str, request: Request):
        with Session(engine) as db:
            user, token = auth.identity(request, db)
            auth.staff(user)
            form = await request.form(max_files=0)
            auth.check_csrf(token, form)
            job = db.scalar(select(UploadJob).where(UploadJob.id == job_id).with_for_update())
            if not job or job.status != "failed":
                raise HTTPException(409, "فقط آپلود ناموفق قابل تلاش مجدد است.")
            if not all((settings.upload_dir / job.id / f).is_file() for f in job.files):
                raise HTTPException(409, "فایل موقت موجود نیست؛ دوباره آپلود کنید.")
            job.status, job.error, job.updated_at = "queued", "", time.time()
            auth.audit(db, user.id, "retry", job_id)
            db.commit()
        return RedirectResponse("/portal/jobs/" + job_id, 303)

    @app.get("/portal/studies/{uid}/view")
    def viewer(uid: str, request: Request):
        with Session(engine) as db:
            user, token = auth.identity(request, db)
            study = db.get(Study, uid)
            if not study:
                raise HTTPException(404, "مطالعه پیدا نشد.")
            patient = db.get(Patient, study.patient_id)
            if user.role == "patient" and (patient.user_id != user.id or not study.published):
                raise HTTPException(404, "مطالعه پیدا نشد.")
            auth.audit(db, user.id, "viewer_opened", uid)
            db.commit()
            return render(request, "viewer", user, token, study=study, patient=patient)

    @app.get("/portal/admin")
    def admin_page(request: Request):
        with Session(engine) as db:
            user, token = auth.identity(request, db)
            auth.staff(user, admin=True)
            return render(
                request,
                "admin",
                user,
                token,
                users=db.scalars(select(User).order_by(User.id)).all(),
                events=db.scalars(select(AuditEvent).order_by(AuditEvent.id.desc()).limit(100)).all(),
            )

    @app.post("/portal/admin/users")
    async def new_staff(request: Request):
        with Session(engine) as db:
            user, token = auth.identity(request, db)
            auth.staff(user, admin=True)
            form = await request.form(max_files=0, max_fields=6)
            auth.check_csrf(token, form)
            role = field(form, "role", 16)
            if role not in {"admin", "operator"}:
                raise HTTPException(400, "نقش نامعتبر است.")
            new = User(
                username=auth.valid_username(field(form, "username", 64)),
                display_name=field(form, "name"),
                password_hash=auth.hash_password(field(form, "password", 1024, strip=False)),
                role=role,
            )
            db.add(new)
            try:
                db.flush()
                auth.audit(db, user.id, "staff_created", new.id)
                db.commit()
            except IntegrityError:
                db.rollback()
                raise HTTPException(409, "نام کاربری تکراری است.")
        return RedirectResponse("/portal/admin", 303)

    from portal.gateway import attach_gateway

    attach_gateway(app)
    return app


def create_from_env():
    return create_app(Settings.from_env())
