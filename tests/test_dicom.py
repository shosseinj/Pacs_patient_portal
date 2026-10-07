import zipfile
import pytest
from portal.dicom import validate_batch, DicomValidationError
from tests.dicom_factory import make_dicom, SERIES


def test_valid_instances_have_patient_identity_and_checksums(tmp_path):
    a = make_dicom(tmp_path / "a.dcm")
    b = make_dicom(tmp_path / "b.dcm", sop_uid=SERIES + ".2")
    items = validate_batch([a, b], tmp_path / "expanded")
    assert len(items) == 2
    assert items[0].patient_id == "DEMO001"
    assert items[0].issuer == "CLINIC"
    assert len(items[0].sha256) == 64


@pytest.mark.parametrize("bad", ["not-dicom", "missing-study", "truncated-pixels"])
def test_invalid_images_are_rejected(tmp_path, bad):
    a = tmp_path / "a.dcm"
    if bad == "not-dicom":
        a.write_bytes(b"not a medical image")
    elif bad == "missing-study":
        make_dicom(a, missing_study=True)
    else:
        make_dicom(a, pixel=b"\0\0")
    with pytest.raises(DicomValidationError):
        validate_batch([a], tmp_path / "expanded")


def test_mixed_patient_batch_is_rejected_before_storage(tmp_path):
    a = make_dicom(tmp_path / "a.dcm")
    b = make_dicom(tmp_path / "b.dcm", patient_id="OTHER", sop_uid=SERIES + ".2")
    with pytest.raises(DicomValidationError):
        validate_batch([a, b], tmp_path / "expanded")


def test_conflicting_sop_bytes_are_rejected(tmp_path):
    a = make_dicom(tmp_path / "a.dcm")
    b = make_dicom(tmp_path / "b.dcm", pixel=b"\x01\0" * 16)
    with pytest.raises(DicomValidationError):
        validate_batch([a, b], tmp_path / "expanded")


def test_identical_duplicate_is_deduplicated(tmp_path):
    a = make_dicom(tmp_path / "a.dcm")
    b = tmp_path / "copy.dcm"
    b.write_bytes(a.read_bytes())
    assert len(validate_batch([a, b], tmp_path / "expanded")) == 1


@pytest.mark.parametrize(
    "name", ["../escape.dcm", "/absolute.dcm", "folder/../../escape.dcm", "..\\escape.dcm"]
)
def test_zip_cannot_escape_staging(tmp_path, name):
    z = tmp_path / "input.zip"
    with zipfile.ZipFile(z, "w") as out:
        out.writestr(name, b"bad")
    with pytest.raises(DicomValidationError):
        validate_batch([z], tmp_path / "expanded")
    assert not (tmp_path / "escape.dcm").exists()


def test_expansion_limit_is_enforced(tmp_path):
    z = tmp_path / "input.zip"
    with zipfile.ZipFile(z, "w", compression=zipfile.ZIP_DEFLATED) as out:
        out.writestr("big.dcm", b"0" * 10000)
    with pytest.raises(DicomValidationError):
        validate_batch([z], tmp_path / "expanded", max_bytes=1000)


def test_zip_of_dicom_files_is_supported(tmp_path):
    a = make_dicom(tmp_path / "a.dcm")
    z = tmp_path / "input.zip"
    with zipfile.ZipFile(z, "w") as out:
        out.write(a, "images/a.dcm")
    assert len(validate_batch([z], tmp_path / "expanded")) == 1
