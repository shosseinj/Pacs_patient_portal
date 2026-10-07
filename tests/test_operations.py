import io
import tarfile
import pytest
from scripts.snapshot import export_volumes, import_volumes, verify_snapshot


def test_snapshot_roundtrip_and_removes_stale_files(tmp_path, monkeypatch):
    source = tmp_path / "source"
    for folder in ["orthanc", "uploads"]:
        (source / folder).mkdir(parents=True)
        (source / folder / "synthetic.bin").write_bytes(b"synthetic-only")
    target = tmp_path / "target"
    (target / "uploads").mkdir(parents=True)
    (target / "uploads" / "stale").write_text("stale")
    stream = io.BytesIO()
    export_volumes(source, stream)
    stream.seek(0)
    assert verify_snapshot(stream)
    stream.seek(0)
    # Chown is exercised in the real container; this test checks snapshot data/structure.
    monkeypatch.setattr("scripts.snapshot.os.chown", lambda *args: None)
    import_volumes(target, stream)
    assert (target / "orthanc" / "synthetic.bin").read_bytes() == b"synthetic-only"
    assert (target / "uploads" / "synthetic.bin").read_bytes() == b"synthetic-only"
    assert not (target / "uploads" / "stale").exists()


def test_empty_archive_and_staging_snapshot_is_valid(tmp_path):
    for name in ["orthanc", "uploads"]:
        (tmp_path / name).mkdir()
    stream = io.BytesIO()
    export_volumes(tmp_path, stream)
    stream.seek(0)
    assert verify_snapshot(stream)


@pytest.mark.parametrize(
    "name,kind", [("../escape", "file"), ("/absolute", "file"), ("uploads/link", "link")]
)
def test_unsafe_snapshot_is_rejected_before_existing_data_removed(tmp_path, name, kind):
    root = tmp_path / "target"
    (root / "orthanc").mkdir(parents=True)
    existing = root / "orthanc" / "keep"
    existing.write_text("keep")
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w:gz") as archive:
        member = tarfile.TarInfo(name)
        if kind == "link":
            member.type = tarfile.SYMTYPE
            member.linkname = "/etc/passwd"
        archive.addfile(member)
    stream.seek(0)
    with pytest.raises(ValueError):
        import_volumes(root, stream)
    assert existing.read_text() == "keep"
