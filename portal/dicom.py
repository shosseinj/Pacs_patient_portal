from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import hashlib
import unicodedata
import zipfile
import pydicom
from pydicom.uid import UID


class DicomValidationError(ValueError):
    pass


@dataclass(frozen=True)
class DicomFile:
    path: Path
    study_uid: str
    series_uid: str
    sop_uid: str
    patient_id: str
    issuer: str
    patient_name: str
    modality: str
    description: str
    study_date: str
    sha256: str


def validate_batch(
    paths, expanded_dir, max_files=5000, max_bytes=2_000_000_000, max_instance_bytes=128_000_000
):
    expanded_dir = Path(expanded_dir)
    expanded_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    files = []
    total = 0
    try:
        for source in map(Path, paths):
            if zipfile.is_zipfile(source):
                with zipfile.ZipFile(source) as archive:
                    for entry in archive.infolist():
                        name = entry.filename.replace("\\", "/")
                        parts = PurePosixPath(name)
                        if parts.is_absolute() or ".." in parts.parts or ":" in name or "\x00" in name:
                            raise DicomValidationError("مسیر ناامن در فایل ZIP وجود دارد.")
                        if entry.is_dir():
                            continue
                        if parts.name.upper() == "DICOMDIR":
                            continue
                        if len(files) >= max_files or total + entry.file_size > max_bytes:
                            raise DicomValidationError("تعداد یا حجم فایل‌های استخراج‌شده بیش از سقف مجاز است.")
                        if entry.file_size > max_instance_bytes:
                            raise DicomValidationError("حجم یک تصویر از سقف مجاز بیشتر است.")
                        dest = expanded_dir / f"{len(files):06d}.dcm"
                        written = 0
                        with archive.open(entry) as src, dest.open("wb") as out:
                            while chunk := src.read(1024 * 1024):
                                written += len(chunk)
                                if written > max_instance_bytes or total + written > max_bytes:
                                    raise DicomValidationError("حجم استخراج از سقف مجاز بیشتر است.")
                                out.write(chunk)
                        total += written
                        files.append(dest)
            else:
                if source.name.upper() == "DICOMDIR":
                    continue
                size = source.stat().st_size
                if len(files) >= max_files or size > max_instance_bytes or total + size > max_bytes:
                    raise DicomValidationError("تعداد یا حجم تصاویر بیش از سقف مجاز است.")
                total += size
                files.append(source)
        if not files:
            raise DicomValidationError("هیچ تصویر DICOM در بسته پیدا نشد.")
        result = {}
        identities = set()
        study_identities = {}
        series_studies = {}
        for path in files:
            ds = pydicom.dcmread(path, force=False)
            uids = [
                str(ds.get(tag, "")) for tag in ["StudyInstanceUID", "SeriesInstanceUID", "SOPInstanceUID"]
            ]
            if not all(v and UID(v).is_valid for v in uids):
                raise DicomValidationError("شناسهٔ مطالعه، سری یا تصویر معتبر نیست.")
            if uids[1] in series_studies and series_studies[uids[1]] != uids[0]:
                raise DicomValidationError("شناسهٔ سری به دو مطالعهٔ متفاوت اشاره دارد.")
            series_studies[uids[1]] = uids[0]
            sop_class = str(ds.get("SOPClassUID", ""))
            if (
                not sop_class
                or not UID(sop_class).is_valid
                or str(ds.file_meta.get("MediaStorageSOPInstanceUID", "")) != uids[2]
                or str(ds.file_meta.get("MediaStorageSOPClassUID", "")) != sop_class
            ):
                raise DicomValidationError("شناسه‌های سربرگ و محتوای DICOM سازگار نیستند.")
            rows, cols = int(ds.get("Rows", 0)), int(ds.get("Columns", 0))
            pixel_tag = next(
                (k for k in ["PixelData", "FloatPixelData", "DoubleFloatPixelData"] if k in ds), None
            )
            if rows < 1 or cols < 1 or not pixel_tag or not ds[pixel_tag].value:
                raise DicomValidationError("فایل، تصویر DICOM دارای دادهٔ پیکسلی نیست.")
            syntax = UID(str(ds.file_meta.get("TransferSyntaxUID", "")))
            if not syntax.is_valid or not syntax.is_transfer_syntax:
                raise DicomValidationError("Transfer Syntax معتبر نیست.")
            samples = int(ds.get("SamplesPerPixel", 1))
            frames = int(ds.get("NumberOfFrames", 1))
            bits = {"FloatPixelData": 32, "DoubleFloatPixelData": 64}.get(
                pixel_tag, int(ds.get("BitsAllocated", 0))
            )
            if bits not in {1, 8, 16, 32, 64} or frames < 1 or samples not in {1, 3}:
                raise DicomValidationError("مشخصات پیکسلی معتبر نیست.")
            expected = (rows * cols * samples * frames * bits + 7) // 8
            if expected > max_instance_bytes:
                raise DicomValidationError("حجم پیکسل‌های بازشده بیش از سقف هر تصویر است.")
            if syntax.is_compressed:
                try:
                    # Decode each frame separately to bound multi-frame working memory.
                    from pydicom.pixels import iter_pixels

                    decoded = 0
                    for pixels in iter_pixels(ds):
                        if pixels.size != rows * cols * samples:
                            raise ValueError("Decoded dimensions disagree")
                        decoded += 1
                    if decoded != frames:
                        raise ValueError("Frame count disagrees")
                except Exception as exc:
                    raise DicomValidationError(
                        "تصویر فشرده خراب است یا رمزگشایی این Transfer Syntax پشتیبانی نمی‌شود."
                    ) from exc
            else:
                if str(ds.get("PhotometricInterpretation", "")) == "YBR_FULL_422":
                    expected = rows * cols * frames * 2 * (bits // 8)
                actual = len(ds[pixel_tag].value)
                if actual not in {expected, expected + (expected % 2)}:
                    raise DicomValidationError("دادهٔ پیکسلی ناقص یا ناسازگار است.")

            def normalize(value):
                return unicodedata.normalize("NFC", str(value)).strip()

            identity = (normalize(ds.get("PatientID", "")), normalize(ds.get("IssuerOfPatientID", "")))
            if any(len(part) > 64 for part in identity):
                raise DicomValidationError("شناسهٔ بیمار یا صادرکننده بیش از حد طولانی است.")
            identities.add(identity)
            if uids[0] in study_identities and study_identities[uids[0]] != identity:
                raise DicomValidationError("یک مطالعه به چند هویت متفاوت اشاره دارد.")
            study_identities[uids[0]] = identity
            checksum = hashlib.sha256(path.read_bytes()).hexdigest()
            item = DicomFile(
                path,
                *uids,
                *identity,
                normalize(ds.get("PatientName", "")),
                str(ds.get("Modality", "OT"))[:16],
                str(ds.get("StudyDescription", ""))[:160],
                str(ds.get("StudyDate", ""))[:8],
                checksum,
            )
            if item.sop_uid in result and result[item.sop_uid].sha256 != checksum:
                raise DicomValidationError("دو فایل متفاوت، شناسهٔ تصویر یکسان دارند.")
            result[item.sop_uid] = item
        if len(identities) > 1:
            raise DicomValidationError("بسته شامل تصاویر چند بیمار است؛ هر بیمار را جدا آپلود کنید.")
        return list(result.values())
    except DicomValidationError:
        raise
    except (
        OSError,
        ValueError,
        KeyError,
        EOFError,
        RuntimeError,
        zipfile.BadZipFile,
        pydicom.errors.InvalidDicomError,
    ) as exc:
        raise DicomValidationError("فایل DICOM یا ZIP خراب یا پشتیبانی‌نشده است.") from exc
