from pathlib import Path
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import CTImageStorage, ExplicitVRLittleEndian

STUDY = "1.2.826.0.1.3680043.10.543.100"
SERIES = STUDY + ".1"


def make_dicom(
    path: Path,
    patient_id="DEMO001",
    study_uid=STUDY,
    sop_uid=None,
    issuer="CLINIC",
    pixel=b"\x00\x00" * 16,
    missing_study=False,
):
    sop_uid = sop_uid or SERIES + ".1"
    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = CTImageStorage
    meta.MediaStorageSOPInstanceUID = sop_uid
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    meta.ImplementationClassUID = "1.2.826.0.1.3680043.10.543.1"
    ds = FileDataset(str(path), {}, file_meta=meta, preamble=b"\0" * 128)
    ds.SOPClassUID = CTImageStorage
    ds.SOPInstanceUID = sop_uid
    if not missing_study:
        ds.StudyInstanceUID = study_uid
    ds.SeriesInstanceUID = study_uid + ".1"
    ds.PatientID = patient_id
    ds.IssuerOfPatientID = issuer
    ds.PatientName = "Synthetic^Patient"
    ds.StudyDate = "20261006"
    ds.StudyDescription = "Synthetic CT phantom - not clinical"
    ds.Modality = "CT"
    ds.Rows = 4
    ds.Columns = 4
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.BitsAllocated = 16
    ds.BitsStored = 12
    ds.HighBit = 11
    ds.PixelRepresentation = 0
    ds.PixelSpacing = [1, 1]
    ds.ImagePositionPatient = [0, 0, 0]
    ds.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
    ds.InstanceNumber = 1
    ds.PixelData = pixel
    ds.save_as(path, enforce_file_format=True)
    return path
