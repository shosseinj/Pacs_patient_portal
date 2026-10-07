# PACS Patient Portal — accepted scope

The user requested a self-hosted PACS with operator uploads and patient viewing, then explicitly requested building it and delivering all project files as ZIP after testing. No existing website repository was provided. Build a standalone, single-clinic Python portal which can later integrate with that website; do not claim integration with the unseen site.

## Architecture and boundaries
- FastAPI/Jinja portal with Persian RTL UI; PostgreSQL in Compose, SQLite for development/tests.
- Orthanc and DICOMweb internally; OHIF hosted on the same origin. Every medical-data request goes through the portal's authorization gateway.
- Portal tables track users, opaque sessions, patients, studies, instances, upload jobs, job-instance associations, and audit events.
- Queue processing is a separate sequential worker with durable jobs, staging, retry and recovery. Validate the whole batch before sending DICOM to Orthanc.
- Operator selects a patient and uploads Part 10 DICOM files or ZIP. One patient per batch; multiple studies are supported. Invalid DICOM, mixed patient identities, unsafe archives and conflicting SOP identifiers are rejected.
- PatientID + issuer is matched against the selected patient's known DICOM identity. Missing or differing identity puts a batch into review; only admin can approve it with a recorded reason. Names alone never establish identity.
- Only explicitly released instances appear for a patient. Gateway filters study/series/instance queries and metadata, checks instance/frame ownership, rewrites safe BulkDataURI values, blocks unknown routes and all writes. An unreleased extension to an already published study must remain invisible.
- Never bundle real medical data, actual secrets, live credentials, local database or runtime dependencies. Include source, locked dependency manifests, deployment configuration, operational scripts, tests, synthetic sample DICOM and documentation. First setup downloads public dependency/container artifacts.

## Observable acceptance criteria
- Login, logout, CSRF, expiry, role restrictions and login throttling work.
- An operator can create/select a patient, upload, see progress/results, publish verified images, and retry a failed job safely.
- A patient sees only their released studies. Another patient's JSON, instance, frame and bulk-data routes fail without contacting upstream for that resource.
- A wrong-identity upload remains hidden until recorded admin review. A mixed-patient ZIP and malformed/truncated files fail safely.
- Re-uploading identical SOP content is idempotent; different bytes for the same SOPInstanceUID fail.
- Restarting the worker can recover a stale claim. No incomplete batch is released.
- DICOMweb JSON cannot expose Orthanc's internal origin or point a browser at an arbitrary external bulk-data URL.
- Compose exposes only the frontend; PostgreSQL and Orthanc have private persistent volumes. Local binding is loopback; production TLS configuration is included.
- Backup pauses writers and preserves portal database, Orthanc index, files and staging coherently; restoration requires an explicit destructive-operation flag.
- Unit/integration/security tests and browser smoke tests are run. Real external-component coverage and any environment limitations are stated accurately in the test report.

## Deployment scope
The archive/viewer is for patient access. AI interpretation, RIS/LIS workflows, automatic scanner ingestion, multi-clinic tenancy and clinical diagnostic certification are future scope. No deployment or public publication is authorized by the ZIP request.
