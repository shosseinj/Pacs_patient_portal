# Architecture and dependency notes

The portal is the authorization boundary. Orthanc and PostgreSQL stay on the private Compose network. Patients never receive archive credentials. Opaque session tokens are hashed in the DB; passwords use Argon2id. All mutating HTML requests require CSRF; origin checks supplement those tokens.

A durable staged job validates the full batch, checks PatientID + Issuer, rejects UID/content conflicts, then imports via private Orthanc REST. Explicit release sets each linked instance's published flag. DICOMweb JSON is filtered against those flags, including metadata and series counts. Bulk URLs are restricted to the same internal archive origin and an authorized instance, then rewritten to the public gateway. Broad study/series binary retrieval is unavailable because it can include unreleased instances.

One clinic and one sequential worker are supported. A stale processing lease is recovered after 600 seconds. SQLite is used for isolated tests; Compose uses PostgreSQL. Named volumes preserve archive and job data. An encrypted, paused-writer snapshot coordinates the portal DB, archive index and archive files.

Upstream primary documentation used for the configuration:

- Orthanc Docker: https://orthanc.uclouvain.be/book/users/docker-orthancteam.html
- Orthanc security: https://orthanc.uclouvain.be/book/faq/security.html
- Orthanc backup: https://orthanc.uclouvain.be/book/faq/backup.html
- Orthanc DICOMweb: https://orthanc.uclouvain.be/book/plugins/dicomweb.html
- OHIF Docker: https://docs.ohif.org/deployment/docker/
- OHIF DICOMweb: https://docs.ohif.org/configuration/dataSources/dicom-web/

Orthanc and OHIF images are referenced, not redistributed inside this source ZIP. Their licenses and those of PostgreSQL, Nginx and Python dependencies remain their own. Portal code is supplied under the adjacent MIT LICENSE. Consult upstream licenses before modifying or redistributing upstream components.
