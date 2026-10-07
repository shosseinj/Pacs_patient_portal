import copy
import httpx
import pytest
from sqlalchemy.orm import Session
from portal.models import Study, Instance
from tests.conftest import login
from tests.dicom_factory import STUDY, SERIES

SOP = SERIES + ".1"
HIDDEN = SERIES + ".2"
OTHER = STUDY + ".9"


def tag(value):
    return {"vr": "UI", "Value": [value]}


@pytest.fixture
def archive(app):
    with Session(app.state.engine) as db:
        db.add_all(
            [
                Study(
                    uid=STUDY,
                    patient_id=1,
                    dicom_id="DEMO001",
                    issuer="CLINIC",
                    modality="CT",
                    published=True,
                ),
                Study(
                    uid=OTHER, patient_id=2, dicom_id="OTHER", issuer="CLINIC", modality="CT", published=True
                ),
            ]
        )
        db.flush()
        db.add_all(
            [
                Instance(
                    uid=SOP, study_uid=STUDY, series_uid=SERIES, sha256="x", orthanc_id="a", published=True
                ),
                Instance(
                    uid=HIDDEN,
                    study_uid=STUDY,
                    series_uid=SERIES,
                    sha256="y",
                    orthanc_id="b",
                    published=False,
                ),
                Instance(
                    uid=OTHER + ".1",
                    study_uid=OTHER,
                    series_uid=OTHER + ".1",
                    sha256="z",
                    orthanc_id="c",
                    published=True,
                ),
            ]
        )
        db.commit()
    state = {
        "calls": [],
        "bulk": "http://127.0.0.1:8042/dicom-web/studies/"
        + STUDY
        + "/series/"
        + SERIES
        + "/instances/"
        + SOP
        + "/bulk/7fe00010",
    }

    def upstream(request):
        state["calls"].append(str(request.url))
        path = request.url.path
        if "/frames/" in path or "/bulk/" in path or path.endswith("/rendered"):
            return httpx.Response(
                200, content=b"synthetic-pixels", headers={"Content-Type": "application/octet-stream"}
            )
        if path.endswith("/studies"):
            return httpx.Response(
                200,
                json=[
                    {"0020000D": tag(STUDY), "00201208": {"vr": "IS", "Value": [99]}},
                    {"0020000D": tag(OTHER)},
                ],
            )
        if path.endswith("/series"):
            return httpx.Response(
                200,
                json=[
                    {
                        "0020000D": tag(STUDY),
                        "0020000E": tag(SERIES),
                        "00201209": {"vr": "IS", "Value": [99]},
                    },
                    {"0020000D": tag(STUDY), "0020000E": tag(SERIES + ".99")},
                ],
            )
        rows = [
            {
                "0020000D": tag(STUDY),
                "0020000E": tag(SERIES),
                "00080018": tag(SOP),
                "7FE00010": {"vr": "OW", "BulkDataURI": state["bulk"]},
            },
            {"0020000D": tag(STUDY), "0020000E": tag(SERIES), "00080018": tag(HIDDEN)},
        ]
        return httpx.Response(200, json=copy.deepcopy(rows))

    app.state.archive_transport = httpx.MockTransport(upstream)
    return state


def test_archive_requires_authenticated_session(client, archive):
    assert client.get("/dicom-web/studies").status_code == 401
    assert not archive["calls"]


def test_qido_shows_only_owned_released_studies(client, archive):
    login(client, "patient1")
    result = client.get("/dicom-web/studies")
    assert result.status_code == 200
    assert [r["0020000D"]["Value"][0] for r in result.json()] == [STUDY]
    assert result.json()[0]["00201208"]["Value"] == [1]


def test_series_filter_and_counts_exclude_unreleased_images(client, archive):
    login(client, "patient1")
    response = client.get(f"/dicom-web/studies/{STUDY}/series")
    assert response.status_code == 200 and len(response.json()) == 1
    assert response.json()[0]["00201209"]["Value"] == [1]


@pytest.mark.parametrize(
    "suffix", ["metadata", "series/" + SERIES + "/metadata", "series/" + SERIES + "/instances"]
)
def test_metadata_does_not_expose_unreleased_instances(client, archive, suffix):
    login(client, "patient1")
    result = client.get(f"/dicom-web/studies/{STUDY}/{suffix}")
    assert result.status_code == 200
    assert [r["00080018"]["Value"][0] for r in result.json()] == [SOP]
    assert result.json()[0]["7FE00010"]["BulkDataURI"].startswith("/dicom-web/")


@pytest.mark.parametrize("suffix", ["frames/1", "bulk/7fe00010", "rendered", "metadata", ""])
def test_another_patients_instance_cannot_be_requested(client, archive, suffix):
    login(client, "patient2")
    result = client.get(
        f"/dicom-web/studies/{STUDY}/series/{SERIES}/instances/{SOP}" + ("/" + suffix if suffix else "")
    )
    assert result.status_code == 404
    assert not archive["calls"]


def test_hidden_frame_denied_even_when_study_is_published(client, archive):
    login(client, "patient1")
    assert (
        client.get(f"/dicom-web/studies/{STUDY}/series/{SERIES}/instances/{HIDDEN}/frames/1").status_code
        == 404
    )
    assert not archive["calls"]


def test_released_frame_streams_and_has_no_store_header(client, archive):
    login(client, "patient1")
    response = client.get(f"/dicom-web/studies/{STUDY}/series/{SERIES}/instances/{SOP}/frames/1")
    assert response.status_code == 200 and response.content == b"synthetic-pixels"
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    "path",
    [
        "/dicom-web/system",
        "/dicom-web/studies/" + STUDY,
        "/dicom-web/studies/" + STUDY + "/series/" + SERIES,
        "/dicom-web/instances",
        "/dicom-web/studies/bad/metadata",
    ],
)
def test_unapproved_proxy_paths_fail_closed(client, archive, path):
    login(client)
    assert client.get(path).status_code == 404
    assert not archive["calls"]


def test_gateway_is_read_only(client, archive):
    login(client)
    assert client.post("/dicom-web/studies").status_code == 405
    assert not archive["calls"]


def test_external_bulk_url_is_rejected(client, archive):
    login(client, "patient1")
    archive["bulk"] = "https://external.example/stolen"
    assert client.get(f"/dicom-web/studies/{STUDY}/metadata").status_code == 502


def test_operator_can_review_unreleased_instances(client, archive):
    login(client)
    assert (
        client.get(f"/dicom-web/studies/{STUDY}/series/{SERIES}/instances/{HIDDEN}/frames/1").status_code
        == 200
    )
