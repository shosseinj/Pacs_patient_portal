# PACS Patient Portal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Deliver a runnable, tested self-hosted PACS package as ZIP, with operator ingestion and authorized patient viewing.
**Architecture:** FastAPI owns identity, release state and the DICOMweb access gateway; Orthanc owns the private archive. A separate worker processes durable staged jobs; OHIF uses the same-origin gateway.
**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy, pydicom, httpx, Argon2, Jinja, PostgreSQL, Orthanc, OHIF, Nginx, Docker Compose.
**Spec:** docs/superpowers/specs/2026-10-06-pacs-design.md

## Global Constraints
- Standalone package; no assumptions about unseen website code.
- One clinic; operator role can access that clinic's patients.
- Match PatientID and issuer, never only PatientName.
- Release instances individually and filter every patient-facing DICOMweb route.
- Fail closed on authentication, unsupported proxy paths, malformed identifiers and untrusted bulk URLs.
- No secrets, real patient files or local state in the deliverable.

## Review Focus
- A published study acquires new, unreviewed instances: earlier publication must not expose them.
- ZIP traversal, decompression limits and multiple patient identities.
- SOP conflicts after a worker restart or a partially completed import.
- CSRF, patient-to-patient metadata/frame access and session revocation.
- Correct private ingress, OHIF asset routing, persistent volumes and coherent backup.

### Task 1: DICOM ingestion validation
**Files:** portal/dicom.py, portal/config.py, tests/test_dicom.py, tests/dicom_factory.py.
**Interfaces:** consumes staged paths and limits; produces validated instance metadata including UID, patient identity, checksum and file path.
- [x] Write tests for valid files, bad/truncated pixel data, missing UID, SOP conflicts, mixed identities, ZIP traversal and extraction limits.
- [x] Run tests and observe assertion failures with the scaffold.
- [x] Implement `validate_batch(paths, expanded_dir, max_files, max_bytes, max_instance_bytes)` and typed validation errors.
- [x] Run the domain tests; commit.

### Task 2: Portal identity and roles
**Files:** portal/models.py, portal/db.py, portal/auth.py, portal/app.py, tests/conftest.py, tests/test_portal.py.
**Interfaces:** consumes settings and SQLAlchemy sessions; produces authenticated users, CSRF validation and patient/study/job routes.
- [x] Write HTTP tests for login, throttling, logout, CSRF and role restrictions; watch them fail.
- [x] Implement opaque DB sessions and password hashing, patient creation, upload staging and job state routes.
- [x] Run identity and upload tests; commit.

### Task 3: Worker and publication
**Files:** portal/worker.py, portal/orthanc.py, tests/test_worker.py.
**Interfaces:** consumes validated files and staged jobs; produces archived instance records, job-instance links, ready/review/failed states and audit events.
- [x] Write tests for identity quarantine, release, retry, duplicate/conflict detection, mixed batches and claim recovery; watch them fail.
- [x] Implement `process_once(settings, engine, archive)` plus lease recovery and transactional release routes.
- [x] Run worker, portal and domain tests; commit.

### Task 4: Authorized DICOMweb gateway
**Files:** portal/gateway.py, tests/test_gateway.py.
**Interfaces:** consumes current user plus released instance records; produces filtered DICOM JSON and authorized streaming image responses.
- [x] Write tests covering every path class, ownership, unreleased instances and unsafe bulk URLs; watch them fail.
- [x] Implement explicit read-only path grammar, JSON filtering, URI rewriting and streaming with cache protection.
- [x] Run the full pytest suite; commit.

### Task 5: UI and self-hosted operations
**Files:** portal/templates/*, portal/static/*, Dockerfile, compose.yaml, compose.production.yaml, deploy/*, scripts/*, README_FA.md, docs/*.
**Interfaces:** consumes tested portal routes and real upstream configuration; produces operator/admin/patient UI, deployment and maintenance commands.
- [x] Exercise page rendering, form submission and viewer embedding in HTTP/browser tests before completion.
- [x] Add Persian RTL UI, current locked dependencies, private Compose services, same-origin OHIF config, TLS option, setup, synthetic data and backup/restore scripts.
- [x] Validate configurations and scripts and execute browser smoke tests; commit.

### Task 6: Review and ZIP delivery
**Files:** tests/*, docs/TEST_REPORT_FA.md, docs/OPERATIONS_FA.md, final ZIP.
- [x] Run domain, HTTP, worker and gateway tests, lint, browser tests and real-component checks feasible in this environment.
- [x] Request one independent whole-project review; address important findings with reproducing tests.
- [x] Record actual coverage and limitations, verify ZIP integrity and exclude secrets/runtime files, save the ZIP and deliver it.
