import io
import numpy as np
import pydicom
import pytest
from PIL import Image
from pydicom.encaps import encapsulate
from pydicom.uid import JPEGBaseline8Bit, RLELossless
from portal.dicom import DicomValidationError, validate_batch
from tests.dicom_factory import make_dicom, STUDY, SERIES


def jpeg_file(tmp_path, content):
    file = make_dicom(tmp_path / "jpeg.dcm")
    ds = pydicom.dcmread(file)
    ds.file_meta.TransferSyntaxUID = JPEGBaseline8Bit
    ds.BitsAllocated, ds.BitsStored, ds.HighBit = 8, 8, 7
    ds.PixelData = encapsulate([content])
    ds["PixelData"].VR = "OB"
    ds["PixelData"].is_undefined_length = True
    ds.save_as(file, enforce_file_format=True)
    return file


def test_corrupt_compressed_frame_is_rejected(tmp_path):
    file = jpeg_file(tmp_path, b"this is not JPEG data")
    with pytest.raises(DicomValidationError):
        validate_batch([file], tmp_path / "out")


def test_valid_jpeg_frame_can_be_validated(tmp_path):
    stream = io.BytesIO()
    Image.fromarray(np.arange(16, dtype=np.uint8).reshape(4, 4)).save(stream, format="JPEG")
    file = jpeg_file(tmp_path, stream.getvalue())
    assert len(validate_batch([file], tmp_path / "out")) == 1


def test_valid_rle_frame_can_be_validated(tmp_path):
    file = make_dicom(tmp_path / "rle.dcm")
    ds = pydicom.dcmread(file)
    ds.compress(RLELossless)
    ds.save_as(file, enforce_file_format=True)
    assert len(validate_batch([file], tmp_path / "out")) == 1


def test_series_uid_cannot_belong_to_two_studies_in_same_batch(tmp_path):
    first = make_dicom(tmp_path / "first.dcm")
    second = make_dicom(tmp_path / "second.dcm", study_uid=STUDY + ".2", sop_uid=SERIES + ".22")
    ds = pydicom.dcmread(second)
    ds.SeriesInstanceUID = SERIES
    ds.save_as(second, enforce_file_format=True)
    with pytest.raises(DicomValidationError):
        validate_batch([first, second], tmp_path / "out")


def test_compressed_expansion_is_bounded_before_decoding(tmp_path):
    file = jpeg_file(tmp_path, b"not important")
    ds = pydicom.dcmread(file)
    ds.Rows = 65535
    ds.Columns = 65535
    ds.save_as(file, enforce_file_format=True)
    with pytest.raises(DicomValidationError):
        validate_batch([file], tmp_path / "out", max_instance_bytes=1000000)
