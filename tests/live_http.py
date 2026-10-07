"""End-to-end HTTP test against real portal + worker + Orthanc + OHIF + gateway.
Only run against the isolated fixture users described in TEST_REPORT_FA.md.
"""

import json
import os
import re
import time
from pathlib import Path
import httpx

BASE = os.environ["PACS_TEST_URL"]
PASSWORD = os.environ["PACS_TEST_PASSWORD"]
STUDY = "1.2.826.0.1.3680043.10.543.9001"
SERIES = STUDY + ".1"


def csrf(client):
    response = client.get("/portal")
    return re.search(r'name="csrf" value="([^"]+)"', response.text).group(1)


def login(client, name):
    response = client.get("/portal/login")
    token = re.search(r'name="csrf" value="([^"]+)"', response.text).group(1)
    assert (
        client.post("/portal/login", data={"csrf": token, "username": name, "password": PASSWORD}).status_code
        == 303
    )


def client():
    return httpx.Client(base_url=BASE, trust_env=False, timeout=120)


def main():
    with client() as operator, client() as patient, client() as other:
        login(operator, "operator.live")
        login(patient, "patient.live")
        login(other, "other.live")
        archive_url = os.getenv("PACS_TEST_ARCHIVE_URL")
        if archive_url:
            assert httpx.get(archive_url + "/system", trust_env=False).status_code == 401
        assert patient.get("/dicom-web/studies/" + STUDY + "/metadata").status_code == 404
        file = Path(__file__).parent.parent / "examples/synthetic/demo-study.zip"
        response = operator.post(
            "/portal/uploads",
            data={"csrf": csrf(operator), "patient_id": "1"},
            files={"files": ("demo.zip", file.read_bytes(), "application/zip")},
            headers={"Accept": "application/json"},
        )
        assert response.status_code == 202, response.text
        job = response.json()["job_id"]
        for _ in range(150):
            state = operator.get("/api/jobs/" + job).json()
            if state["status"] not in {"queued", "processing"}:
                break
            time.sleep(0.2)
        assert state["status"] == "ready" and state["processed"] == 8, state
        assert patient.get("/dicom-web/studies/" + STUDY + "/metadata").status_code == 404
        assert (
            operator.post("/portal/jobs/" + job + "/publish", data={"csrf": csrf(operator)}).status_code
            == 303
        )
        studies = patient.get("/dicom-web/studies").json()
        assert len(studies) == 1 and studies[0]["00201208"]["Value"] == [8]
        metadata = patient.get("/dicom-web/studies/" + STUDY + "/metadata")
        assert metadata.status_code == 200, metadata.text
        instances = metadata.json()
        assert len(instances) == 8
        for instance in instances:
            sop = instance["00080018"]["Value"][0]
            frame = f"/dicom-web/studies/{STUDY}/series/{SERIES}/instances/{sop}/frames/1"
            result = patient.get(
                frame, headers={"Accept": 'multipart/related; type="application/octet-stream"'}
            )
            assert result.status_code == 200 and len(result.content) > 32768, (
                result.status_code,
                result.text[:200],
            )
            assert result.headers["cache-control"] == "no-store"
            assert other.get(frame).status_code == 404
            if "7FE00010" in instance:
                uri = instance["7FE00010"].get("BulkDataURI")
                if uri:
                    assert uri.startswith("/dicom-web/"), uri
                    assert patient.get(uri).status_code == 200
                    assert other.get(uri).status_code == 404
        assert other.get("/dicom-web/studies").json() == []
        assert other.get("/dicom-web/studies/" + STUDY + "/metadata").status_code == 404
        assert other.get("/portal/studies/" + STUDY + "/view").status_code == 404
        assert patient.get("/portal/studies/" + STUDY + "/view").status_code == 200
        assert patient.get("/viewer").status_code == 200
        assert patient.get("/app-config.js").status_code == 200
        assert "qidoRoot" in patient.get("/app-config.js").text
        assert patient.post("/portal/logout", data={"csrf": csrf(patient)}).status_code == 303
        assert patient.get("/api/session").status_code == 401
        assert patient.get("/dicom-web/studies").status_code == 401
        result = {
            "passed": True,
            "images": len(instances),
            "tests": [
                "real upload/import/release",
                "DICOMweb QIDO/metadata/frames/bulk",
                "other patient denial",
                "OHIF HTML/config served",
                "logout revocation",
                "archive requires auth",
            ],
        }
        print(json.dumps(result))
        output = os.getenv("PACS_TEST_ARTIFACTS")
        if output:
            Path(output).mkdir(parents=True, exist_ok=True)
            (Path(output) / "live-http-result.json").write_text(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
