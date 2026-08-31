from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.extended_models import DocumentArtifact, ProcessingState
from app.models import Job, JobStatus
from app.production_main import app
from app.routes import document_routes


def test_failure_is_sanitized_and_retry_is_deterministic(client, monkeypatch):
    upload = client.post(
        "/documents/upload",
        files={"file": ("retry.txt", b"INVOICE Amount Due PKR 500", "text/plain")},
        data={"document_type": "auto", "auto_process": "false"},
    )
    job_id = upload.json()["data"]["job_id"]
    real_processor = document_routes.process_document
    attempts = 0

    def flaky_processor(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("private parser detail: /srv/uploads/secret")
        return real_processor(*args, **kwargs)

    monkeypatch.setattr(document_routes, "process_document", flaky_processor)

    assert client.post(f"/documents/{job_id}/process").status_code == 200
    failed = client.get(f"/documents/{job_id}").json()["data"]
    assert failed["state"] == "failed"
    assert failed["job_status"] == "failed"
    assert failed["error"] == "Document processing failed"
    assert "secret" not in str(failed)

    assert client.post(f"/documents/{job_id}/process").status_code == 200
    completed = client.get(f"/documents/{job_id}").json()["data"]
    assert completed["state"] == "completed"
    assert attempts == 2


def test_source_download_cannot_escape_storage(client, tmp_path):
    upload = client.post(
        "/documents/upload",
        files={"file": ("source.txt", b"Karachi source document", "text/plain")},
        data={"document_type": "auto", "auto_process": "false"},
    )
    job_id = upload.json()["data"]["job_id"]
    outside = tmp_path / "outside.txt"
    outside.write_text("private", encoding="utf-8")

    async def redirect_source() -> None:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(DocumentArtifact).where(DocumentArtifact.job_id == job_id)
            )
            artifact = result.scalar_one()
            artifact.stored_path = str(outside.resolve())
            await db.commit()

    asyncio.run(redirect_source())
    response = client.get(f"/documents/{job_id}/download")
    assert response.status_code == 404
    assert "unavailable" in response.json()["message"].lower()


def test_startup_recovers_interrupted_job_and_allows_retry():
    with TestClient(app) as initial_client:
        upload = initial_client.post(
            "/documents/upload",
            files={
                "file": (
                    "interrupted.txt",
                    b"INVOICE Amount Due PKR 750",
                    "text/plain",
                )
            },
            data={"document_type": "auto", "auto_process": "false"},
        )
        job_id = upload.json()["data"]["job_id"]

    async def leave_interrupted_state() -> None:
        async with AsyncSessionLocal() as db:
            artifact_result = await db.execute(
                select(DocumentArtifact).where(DocumentArtifact.job_id == job_id)
            )
            job_result = await db.execute(select(Job).where(Job.id == job_id))
            artifact = artifact_result.scalar_one()
            job = job_result.scalar_one()
            artifact.state = ProcessingState.processing.value
            job.status = JobStatus.processing
            await db.commit()

    asyncio.run(leave_interrupted_state())

    with TestClient(app) as restarted_client:
        recovered = restarted_client.get(f"/documents/{job_id}").json()["data"]
        assert recovered["state"] == "failed"
        assert recovered["job_status"] == "failed"
        assert recovered["error"] == "Processing was interrupted; retry the document"

        retry = restarted_client.post(f"/documents/{job_id}/process")
        assert retry.status_code == 200
        completed = restarted_client.get(f"/documents/{job_id}").json()["data"]
        assert completed["state"] == "completed"
