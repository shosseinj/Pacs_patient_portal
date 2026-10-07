import io
import os
import subprocess
import tarfile
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("missing", ["portal.dump", "orthanc.dump", "volumes.tar.gz"])
def test_restore_missing_file_never_reaches_database_drop(tmp_path, missing):
    bundle = tmp_path / "backup.tar.gz.age"
    with tarfile.open(bundle, "w:gz") as archive:
        for name in ["portal.dump", "orthanc.dump", "volumes.tar.gz"]:
            if name == missing:
                continue
            item = tarfile.TarInfo(name)
            item.size = 3
            archive.addfile(item, io.BytesIO(b"data"[:3]))
    key = tmp_path / "key"
    key.write_text("fixture only")
    executable = tmp_path / "bin"
    executable.mkdir()
    age = executable / "age"
    age.write_text('#!/usr/bin/env bash\ncat "${@: -1}"\n')
    age.chmod(0o755)
    docker = executable / "docker"
    docker.write_text(
        '#!/usr/bin/env bash\nprintf "%s " "$@" >> "$MOCK_DOCKER_LOG"\nprintf "\\n" >> "$MOCK_DOCKER_LOG"\ncat >/dev/null\nexit 0\n'
    )
    docker.chmod(0o755)
    log = tmp_path / "docker.log"
    result = subprocess.run(
        [
            "bash",
            str(ROOT / "scripts/restore.sh"),
            "--confirm",
            str(bundle),
            "--identity",
            str(key),
            "--replace-all-data",
        ],
        env={**os.environ, "PATH": str(executable) + ":" + os.environ["PATH"], "MOCK_DOCKER_LOG": str(log)},
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode != 0
    assert "DROP DATABASE" not in log.read_text()
