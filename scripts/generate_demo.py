"""Create synthetic data only: no actual patient or clinical information."""

import argparse
import math
import struct
import zipfile
from pathlib import Path
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import CTImageStorage, ExplicitVRLittleEndian


def generate(output, patient_id="DEMO001", slices=8):
    output.mkdir(parents=True, exist_ok=True)
    study = "1.2.826.0.1.3680043.10.543.9001"
    series = study + ".1"
    paths = []
    for index in range(slices):
        sop = series + "." + str(index + 1)
        meta = FileMetaDataset()
        meta.MediaStorageSOPClassUID, meta.MediaStorageSOPInstanceUID = CTImageStorage, sop
        meta.TransferSyntaxUID = ExplicitVRLittleEndian
        meta.ImplementationClassUID = "1.2.826.0.1.3680043.10.543.1"
        file = output / f"phantom-{index + 1:03d}.dcm"
        ds = FileDataset(str(file), {}, file_meta=meta, preamble=b"\0" * 128)
        ds.SOPClassUID, ds.SOPInstanceUID, ds.StudyInstanceUID, ds.SeriesInstanceUID = (
            CTImageStorage,
            sop,
            study,
            series,
        )
        ds.PatientID, ds.IssuerOfPatientID, ds.PatientName = patient_id, "DEMO", "Synthetic^Phantom"
        ds.PatientBirthDate, ds.PatientSex = "20000101", "O"
        ds.StudyDescription = "SYNTHETIC CT PHANTOM - NOT CLINICAL"
        ds.SeriesDescription = "Generated test pixels only"
        ds.StudyDate, ds.StudyTime, ds.Modality = "20261006", "120000", "CT"
        ds.AccessionNumber, ds.StudyID, ds.SeriesNumber, ds.InstanceNumber = "SYNTHETIC", "1", 1, index + 1
        ds.Rows, ds.Columns, ds.SamplesPerPixel = 128, 128, 1
        ds.PhotometricInterpretation = "MONOCHROME2"
        ds.BitsAllocated, ds.BitsStored, ds.HighBit, ds.PixelRepresentation = 16, 16, 15, 1
        ds.ImagePositionPatient = [0, 0, index * 2]
        ds.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
        ds.PixelSpacing, ds.SliceThickness, ds.SpacingBetweenSlices = [1, 1], 2, 2
        ds.FrameOfReferenceUID = study + ".2"
        ds.RescaleSlope, ds.RescaleIntercept = 1, 0
        ds.WindowCenter, ds.WindowWidth = 40, 400
        pixels = []
        for y in range(128):
            for x in range(128):
                radius = math.hypot(x - 64, y - 64)
                pixels.append(
                    -1000
                    if radius > 50
                    else (800 if radius < 12 + index else int(30 + 120 * math.sin(x / 13)))
                )
        ds.PixelData = struct.pack("<" + str(len(pixels)) + "h", *pixels)
        ds.save_as(file, enforce_file_format=True)
        paths.append(file)
    with zipfile.ZipFile(output / "demo-study.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for file in paths:
            archive.write(file, file.name)
    return paths


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("examples/synthetic"))
    args = parser.parse_args()
    generate(args.output)
    print("Synthetic DICOM generated. Patient ID: DEMO001; issuer: DEMO. No real patient data.")
