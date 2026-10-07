"""Coherent volume export/import, called only by maintenance containers."""

import argparse
import os
import shutil
import sys
import tarfile
from pathlib import Path, PurePosixPath

ROOT = Path("/snapshot")


def export_volumes(root, stream):
    with tarfile.open(fileobj=stream, mode="w|gz") as archive:
        for name in ["orthanc", "uploads"]:
            archive.add(root / name, arcname=name)


def check_member(member):
    path = PurePosixPath(member.name)
    if (
        path.is_absolute()
        or ".." in path.parts
        or not path.parts
        or path.parts[0] not in {"orthanc", "uploads"}
        or not (member.isfile() or member.isdir())
    ):
        raise ValueError("Unsafe snapshot entry")
    return path.parts[0]


def verify_snapshot(stream):
    roots = set()
    with tarfile.open(fileobj=stream, mode="r|gz") as archive:
        for member in archive:
            roots.add(check_member(member))
    if roots != {"orthanc", "uploads"}:
        raise ValueError("Snapshot lacks required volume roots")
    return True


def import_volumes(root, stream):
    # Validate an incoming stream fully before removing existing data.
    import tempfile

    with tempfile.TemporaryFile() as spool:
        shutil.copyfileobj(stream, spool)
        spool.seek(0)
        with tarfile.open(fileobj=spool, mode="r:gz") as archive:
            members = archive.getmembers()
            for member in members:
                check_member(member)
            if {check_member(m) for m in members} != {"orthanc", "uploads"}:
                raise ValueError("Snapshot lacks required volume roots")
            for name in ["orthanc", "uploads"]:
                folder = root / name
                folder.mkdir(parents=True, exist_ok=True)
                for item in folder.iterdir():
                    if item.is_dir() and not item.is_symlink():
                        shutil.rmtree(item)
                    else:
                        item.unlink()
            archive.extractall(root, members=members, filter="data")
    for folder, directories, files in os.walk(root / "uploads"):
        os.chown(folder, 10001, 10001)
        for name in directories + files:
            os.chown(Path(folder) / name, 10001, 10001)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["export", "import", "verify"])
    args = parser.parse_args()
    if args.action == "export":
        export_volumes(ROOT, sys.stdout.buffer)
    elif args.action == "import":
        import_volumes(ROOT, sys.stdin.buffer)
    else:
        verify_snapshot(sys.stdin.buffer)
