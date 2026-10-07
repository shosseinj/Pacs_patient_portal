import json
import re
from urllib.parse import urlsplit
import httpx
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from portal.auth import identity
from portal.models import Patient, Study, Instance

UID = r"[0-9]+(?:\.[0-9]+)*"
BASE = rf"studies/({UID})"
SERIES = BASE + rf"/series/({UID})"
INSTANCE = SERIES + rf"/instances/({UID})"
PATTERNS = [
    ("studies", r"studies"),
    ("series", BASE + r"/series"),
    ("instances", SERIES + r"/instances"),
    ("metadata", BASE + r"/metadata"),
    ("metadata", SERIES + r"/metadata"),
    ("metadata", INSTANCE + r"/metadata"),
    ("binary", INSTANCE),
    ("binary", INSTANCE + r"/frames/([1-9][0-9]*(?:,[1-9][0-9]*)*)(?:/rendered)?"),
    ("binary", INSTANCE + r"/rendered"),
    ("binary", INSTANCE + r"/bulk/([a-zA-Z0-9_-]+(?:/[a-zA-Z0-9_-]+)*)"),
]
QUERY_KEYS = {
    "includefield",
    "limit",
    "offset",
    "StudyInstanceUID",
    "SeriesInstanceUID",
    "SOPInstanceUID",
    "PatientID",
    "PatientName",
    "AccessionNumber",
    "StudyDate",
    "ModalitiesInStudy",
    "Modality",
    "StudyDescription",
    "fuzzymatching",
    "viewport",
    "quality",
    "window",
}


def classify(path):
    if len(path) > 1024:
        raise HTTPException(404, "مسیر مجاز نیست.")
    for kind, pattern in PATTERNS:
        match = re.fullmatch(pattern, path)
        if match:
            groups = match.groups()
            uids = groups[:3] if kind == "binary" else groups
            if any(
                len(uid) > 64 or any(len(part) > 1 and part.startswith("0") for part in uid.split("."))
                for uid in uids
            ):
                raise HTTPException(404, "شناسه نامعتبر است.")
            return kind, groups
    raise HTTPException(404, "مسیر مجاز نیست.")


def value(row, tag):
    items = row.get(tag, {}).get("Value", [])
    return str(items[0]) if items else ""


def attach_gateway(app):
    @app.get("/dicom-web/{path:path}")
    async def gateway(path: str, request: Request):
        settings = app.state.settings
        with Session(app.state.engine) as db:
            user, _ = identity(request, db)
            kind, groups = classify(path)
            query = select(Instance).join(Study).join(Patient)
            if user.role == "patient":
                query = query.where(
                    Patient.user_id == user.id, Study.published.is_(True), Instance.published.is_(True)
                )
            elif user.role not in {"admin", "operator"}:
                raise HTTPException(403, "دسترسی مجاز نیست.")
            if groups:
                query = query.where(Instance.study_uid == groups[0])
            if len(groups) >= 2:
                query = query.where(Instance.series_uid == groups[1])
            if len(groups) >= 3:
                query = query.where(Instance.uid == groups[2])
            allowed = {i.uid: (i.study_uid, i.series_uid) for i in db.scalars(query).all()}
        if groups and not allowed:
            raise HTTPException(404, "تصویر پیدا نشد.")
        if not allowed:
            return JSONResponse([])
        params = [(k, v) for k, v in request.query_params.multi_items() if k in QUERY_KEYS]
        offset, limit = 0, 10000
        if kind != "binary":
            try:
                offset = max(0, int(request.query_params.get("offset", "0")))
                limit = min(10000, max(1, int(request.query_params.get("limit", "10000"))))
            except ValueError:
                raise HTTPException(400, "صفحه‌بندی نامعتبر است.")
            params = [(k, v) for k, v in params if k not in {"offset", "limit"}]
        accept = request.headers.get("accept", "*/*")[:256] if kind == "binary" else "application/dicom+json"
        client = httpx.AsyncClient(
            base_url=settings.orthanc_url,
            auth=(settings.orthanc_user, settings.orthanc_password),
            timeout=120,
            follow_redirects=False,
            trust_env=False,
            transport=getattr(app.state, "archive_transport", None),
        )
        try:
            upstream = await client.send(
                client.build_request("GET", "/dicom-web/" + path, params=params, headers={"Accept": accept}),
                stream=True,
            )
        except httpx.HTTPError:
            await client.aclose()
            raise HTTPException(502, "آرشیو در دسترس نیست.")
        if upstream.status_code not in {200, 206}:
            status = 404 if upstream.status_code == 404 else 502
            await upstream.aclose()
            await client.aclose()
            raise HTTPException(status, "تصاویر از آرشیو دریافت نشدند.")
        if kind == "binary":

            async def stream():
                try:
                    async for chunk in upstream.aiter_bytes():
                        yield chunk
                finally:
                    await upstream.aclose()
                    await client.aclose()

            return StreamingResponse(
                stream(),
                status_code=upstream.status_code,
                headers={
                    "Content-Type": upstream.headers.get("content-type", "application/octet-stream"),
                    "Cache-Control": "no-store",
                    "X-Content-Type-Options": "nosniff",
                },
            )
        try:
            content = bytearray()
            async for chunk in upstream.aiter_bytes():
                content.extend(chunk)
                if len(content) > 64_000_000:
                    raise ValueError("Metadata too large")
            rows = json.loads(content)
            if not isinstance(rows, list):
                raise ValueError("Not an array")
            studies = {pair[0] for pair in allowed.values()}
            series = {pair[1] for pair in allowed.values()}
            filtered = []
            for row in rows:
                if not isinstance(row, dict):
                    raise ValueError("Invalid record")
                if kind == "studies":
                    uid = value(row, "0020000D")
                    keep = uid in studies
                    if keep:
                        visible = [pair for pair in allowed.values() if pair[0] == uid]
                        row["00201208"] = {"vr": "IS", "Value": [len(visible)]}
                        row["00201206"] = {"vr": "IS", "Value": [len({pair[1] for pair in visible})]}
                elif kind == "series":
                    uid = value(row, "0020000E")
                    keep = uid in series and value(row, "0020000D") in studies
                    if keep:
                        row["00201209"] = {
                            "vr": "IS",
                            "Value": [sum(pair[1] == uid for pair in allowed.values())],
                        }
                else:
                    uid = value(row, "00080018")
                    keep = uid in allowed and allowed[uid] == (value(row, "0020000D"), value(row, "0020000E"))
                if keep:
                    rewrite_bulk(row, settings, allowed)
                    filtered.append(row)
            return JSONResponse(filtered[offset : offset + limit], media_type="application/dicom+json")
        except (ValueError, TypeError, KeyError, httpx.HTTPError):
            raise HTTPException(502, "پاسخ متادیتای آرشیو معتبر نیست.")
        finally:
            await upstream.aclose()
            await client.aclose()


def rewrite_bulk(node, settings, allowed):
    if isinstance(node, list):
        for item in node:
            rewrite_bulk(item, settings, allowed)
    elif isinstance(node, dict):
        for key, item in list(node.items()):
            if key == "BulkDataURI":
                parsed, base = urlsplit(item), urlsplit(settings.orthanc_url)
                if parsed.scheme and (parsed.scheme != base.scheme or parsed.netloc != base.netloc):
                    raise ValueError("Untrusted bulk origin")
                if parsed.netloc and parsed.netloc != base.netloc:
                    raise ValueError("Untrusted bulk host")
                if parsed.query or parsed.fragment or not parsed.path.startswith("/dicom-web/"):
                    raise ValueError("Untrusted bulk path")
                try:
                    kind, groups = classify(parsed.path[len("/dicom-web/") :])
                except HTTPException as exc:
                    raise ValueError("Untrusted bulk path") from exc
                if (
                    kind != "binary"
                    or len(groups) < 3
                    or groups[2] not in allowed
                    or allowed[groups[2]] != groups[:2]
                ):
                    raise ValueError("Bulk URI outside allowed instance")
                node[key] = parsed.path
            else:
                rewrite_bulk(item, settings, allowed)
