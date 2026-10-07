"""Validate tar paths and required bundle files without loading data in RAM."""

import sys
import tarfile
from pathlib import PurePosixPath

REQUIRED = {"portal.dump", "orthanc.dump", "volumes.tar.gz"}


def validate_bundle(stream):
    files = {}
    with tarfile.open(fileobj=stream, mode="r|gz") as archive:
        for member in archive:
            path = PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts or not (member.isfile() or member.isdir()):
                raise ValueError("Unsafe backup path or link")
            if member.isfile():
                name = str(path)
                if name in files:
                    raise ValueError("Duplicate backup entry")
                files[name] = member.size
    if any(files.get(name, 0) <= 0 for name in REQUIRED):
        raise ValueError("Backup lacks required nonempty database dumps or volume snapshot")
    return files


if __name__ == "__main__":
    validate_bundle(sys.stdin.buffer)
    print("Backup structure checked", file=sys.stderr)
