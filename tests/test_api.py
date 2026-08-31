from __future__ import annotations

import io

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.routes import document_routes


def test_readiness_and_about_are_public(client):
    ready = client.get("/health/ready")
    about = client.get("/about")

    assert ready.status_code == 200
    assert ready.json()["data"]["database"] == "ok"
    assert about.json()["data"]["developer"] == "Muhammad Ali Nawaz"
    assert "deterministic" in about.json()["data"]["processing"]
    assert "X-Request-ID" in ready.headers
    assert ready.headers["X-Content-Type-Options"] == "nosniff"


def test_real_file_upload_auto_processes_with_pkr_fixture(client):
    document = (
        b"INVOICE\nInvoice Number: KHI-2026-12\n"
        b"Bill To: Clifton Harbour Traders\nAmount Due: PKR 35,000.00\n"
        b"Due Date: 2026-09-01\n"
    )
    response = client.post(
        "/documents/upload",
        files={"file": ("invoice.txt", io.BytesIO(document), "text/plain")},
        data={"document_type": "auto", "auto_process": "true"},
    )

    assert response.status_code == 201
    job_id = response.json()["data"]["job_id"]
    payload = client.get(f"/documents/{job_id}").json()["data"]
    assert payload["state"] == "completed"
    assert payload["result"]["document_type"] == "invoice"
    assert payload["result"]["invoice"]["invoice_number"] == "KHI-2026-12"
    assert payload["job_status"] == "completed"

    download = client.get(f"/documents/{job_id}/download")
    assert download.status_code == 200
    assert b"KHI-2026-12" in download.content


def test_manual_processing_and_duplicate_protection(client):
    response = client.post(
        "/documents/upload",
        files={
            "file": (
                "contract.txt",
                b"Service Agreement with termination, confidentiality, and governing law.",
                "text/plain",
            )
        },
        data={"document_type": "contract", "auto_process": "false"},
    )
    job_id = response.json()["data"]["job_id"]
    assert response.json()["data"]["state"] == "uploaded"
    assert client.post(f"/documents/{job_id}/process").status_code == 200

    duplicate = client.post(f"/documents/{job_id}/process")
    assert duplicate.status_code == 400
    assert "already completed" in duplicate.json()["message"].lower()


def test_rejects_unsupported_empty_signature_and_mime_mismatch(client):
    unsupported = client.post(
        "/documents/upload",
        files={"file": ("malware.exe", b"not executable", "application/octet-stream")},
        data={"document_type": "auto"},
    )
    assert unsupported.status_code == 415

    empty = client.post(
        "/documents/upload",
        files={"file": ("empty.txt", b"", "text/plain")},
        data={"document_type": "auto"},
    )
    assert empty.status_code == 400

    fake_pdf = client.post(
        "/documents/upload",
        files={"file": ("fake.pdf", b"plain text", "application/pdf")},
        data={"document_type": "auto"},
    )
    assert fake_pdf.status_code == 415
    assert "does not match" in fake_pdf.json()["message"]

    wrong_mime = client.post(
        "/documents/upload",
        files={"file": ("notes.txt", b"Karachi project notes", "application/pdf")},
        data={"document_type": "auto"},
    )
    assert wrong_mime.status_code == 415


def test_validation_errors_are_sanitized_and_include_request_id(client):
    response = client.get("/documents/not-a-uuid")
    assert response.status_code == 422
    data = response.json()["data"]
    assert data["request_id"]
    assert data["errors"][0].keys() == {"location", "message", "type"}
    assert "input" not in data["errors"][0]


def test_database_failure_removes_written_upload(client, monkeypatch):
    storage = document_routes.settings.storage_dir
    before = {path.name for path in storage.iterdir() if path.name != ".gitkeep"}

    async def fail_commit(_: AsyncSession) -> None:
        raise RuntimeError("simulated database failure")

    monkeypatch.setattr(AsyncSession, "commit", fail_commit)
    with pytest.raises(RuntimeError, match="simulated database failure"):
        client.post(
            "/documents/upload",
            files={"file": ("orphan.txt", b"Karachi document", "text/plain")},
            data={"document_type": "auto", "auto_process": "false"},
        )

    after = {path.name for path in storage.iterdir() if path.name != ".gitkeep"}
    assert after == before
