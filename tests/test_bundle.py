import io
import tarfile
import pytest
from scripts.validate_bundle import validate_bundle


class BoundedRead(io.BytesIO):
    def read(self, size=-1):
        assert 0 <= size <= 10240, "Validator must read the bundle in bounded chunks"
        return super().read(size)


def bundle(files):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w:gz") as archive:
        for name in files:
            item = tarfile.TarInfo(name)
            item.size = 1
            archive.addfile(item, io.BytesIO(b"x"))
    return BoundedRead(stream.getvalue())


def test_bundle_is_streamed_and_requires_three_data_files():
    result = validate_bundle(bundle(["./portal.dump", "orthanc.dump", "volumes.tar.gz", "config.env"]))
    assert result["portal.dump"] == 1 and result["orthanc.dump"] == 1 and result["volumes.tar.gz"] == 1


@pytest.mark.parametrize(
    "files",
    [
        ["orthanc.dump", "volumes.tar.gz"],
        ["portal.dump", "volumes.tar.gz"],
        ["portal.dump", "orthanc.dump"],
        ["../escape", "portal.dump", "orthanc.dump", "volumes.tar.gz"],
    ],
)
def test_bundle_missing_data_or_unsafe_path_is_rejected(files):
    with pytest.raises(ValueError):
        validate_bundle(bundle(files))
