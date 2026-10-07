import hashlib
import httpx
from portal.dicom import DicomValidationError


class OrthancArchive:
    def __init__(self, settings):
        self.client = httpx.Client(
            base_url=settings.orthanc_url,
            auth=(settings.orthanc_user, settings.orthanc_password),
            timeout=120,
            follow_redirects=False,
            trust_env=False,
        )

    def close(self):
        self.client.close()

    def put(self, item):
        # Checking the archive also protects recovery after a crash between archive and DB writes.
        response = self.client.post(
            "/tools/find", json={"Level": "Instance", "Query": {"SOPInstanceUID": item.sop_uid}}
        )
        response.raise_for_status()
        found = response.json()
        if found:
            if len(found) != 1:
                raise DicomValidationError("آرشیو دارای چند تصویر با شناسهٔ یکسان است.")
            original = self.client.get("/instances/" + found[0] + "/file")
            original.raise_for_status()
            if hashlib.sha256(original.content).hexdigest() != item.sha256:
                raise DicomValidationError("شناسهٔ تصویر در آرشیو با محتوای متفاوت وجود دارد.")
            return found[0]
        response = self.client.post(
            "/instances", content=item.path.read_bytes(), headers={"Content-Type": "application/dicom"}
        )
        response.raise_for_status()
        result = response.json()
        if result.get("Status") not in {"Success", "AlreadyStored"} or not result.get("ID"):
            raise RuntimeError("Unexpected archive response")
        return result["ID"]
