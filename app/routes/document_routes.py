from __future__ import annotations

import asyncio
import logging
import shutil
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import AsyncSessionLocal, get_db
from app.extended_models import DocumentArtifact, ProcessingState
from app.models import Job, JobStatus
from app.schemas import APIResponse
from app.security import require_document_access
from app.services.document_processor import (
    DocumentProcessingError,
    ParserLimits,
    process_document,
    sha256_file,
    validate_document_file,
)

router = APIRouter(
    prefix="/documents",
    tags=["document processing"],
    dependencies=[Depends(require_document_access)],
)
logger = logging.getLogger(__name__)
settings = get_settings()


def _parser_limits() -> ParserLimits:
    return ParserLimits(
        max_text_bytes=settings.max_text_bytes,
        max_extracted_text_chars=settings.max_extracted_text_chars,
        max_pdf_pages=settings.max_pdf_pages,
        max_office_uncompressed_bytes=settings.max_office_uncompressed_bytes,
        max_office_compression_ratio=settings.max_office_compression_ratio,
        max_worksheets=settings.max_worksheets,
        max_rows=settings.max_rows,
        max_cells=settings.max_cells,
    )


def _safe_filename(filename: str | None) -> str:
    candidate = Path(filename or "document").name.strip()
    return candidate or "document"


async def _artifact_or_404(job_id: UUID, db: AsyncSession) -> DocumentArtifact:
    result = await db.execute(
        select(DocumentArtifact).where(DocumentArtifact.job_id == str(job_id))
    )
    artifact = result.scalar_one_or_none()
    if artifact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    return artifact


def _serialize_artifact(artifact: DocumentArtifact, job: Job | None = None) -> dict:
    data = {
        "id": artifact.id,
        "job_id": artifact.job_id,
        "filename": artifact.original_filename,
        "mime_type": artifact.mime_type,
        "extension": artifact.extension,
        "size_bytes": artifact.size_bytes,
        "sha256": artifact.sha256,
        "requested_type": artifact.requested_type,
        "state": artifact.state,
        "result": artifact.result,
        "error": artifact.error,
        "created_at": artifact.created_at.isoformat() if artifact.created_at else None,
        "updated_at": artifact.updated_at.isoformat() if artifact.updated_at else None,
    }
    if job is not None:
        data["job_status"] = job.status.value
    return data


def _public_processing_error(exc: Exception) -> tuple[str, str]:
    if isinstance(exc, DocumentProcessingError):
        return exc.code, exc.public_message
    return "processing_failed", "Document processing failed"


async def process_uploaded_document_task(job_id: UUID) -> None:
    """Claim and process one stored document in FastAPI's non-durable task runner."""

    async with AsyncSessionLocal() as db:
        claim = await db.execute(
            update(DocumentArtifact)
            .where(
                DocumentArtifact.job_id == str(job_id),
                DocumentArtifact.state.in_(
                    [ProcessingState.queued.value, ProcessingState.failed.value]
                ),
            )
            .values(
                state=ProcessingState.processing.value,
                error=None,
                updated_at=datetime.now(UTC),
            )
        )
        if claim.rowcount != 1:
            await db.rollback()
            logger.info("Document task was already claimed", extra={"job_id": str(job_id)})
            return

        artifact_result = await db.execute(
            select(DocumentArtifact).where(DocumentArtifact.job_id == str(job_id))
        )
        artifact = artifact_result.scalar_one_or_none()
        job_result = await db.execute(select(Job).where(Job.id == str(job_id)))
        job = job_result.scalar_one_or_none()
        if artifact is None or job is None:
            await db.rollback()
            logger.error("Processing target missing", extra={"job_id": str(job_id)})
            return

        job.status = JobStatus.processing
        await db.commit()

        try:
            extracted_text, result = await asyncio.to_thread(
                process_document,
                Path(artifact.stored_path),
                artifact.requested_type,
                limits=_parser_limits(),
            )
            payload = dict(job.payload or {})
            payload["processing_state"] = ProcessingState.completed.value
            payload["processing_result"] = result
            payload["file"] = {
                "filename": artifact.original_filename,
                "mime_type": artifact.mime_type,
                "size_bytes": artifact.size_bytes,
                "sha256": artifact.sha256,
            }
            artifact.extracted_text = extracted_text
            artifact.result = result
            artifact.error = None
            artifact.state = ProcessingState.completed.value
            artifact.updated_at = datetime.now(UTC)
            job.payload = payload
            job.status = JobStatus.completed
            await db.commit()
            logger.info("Document processing completed", extra={"job_id": str(job_id)})
        except Exception as exc:  # noqa: BLE001 - task boundary persists safe failure state
            error_code, public_message = _public_processing_error(exc)
            logger.exception(
                "Document processing failed",
                extra={"job_id": str(job_id), "error_code": error_code},
            )
            payload = dict(job.payload or {})
            payload["processing_state"] = ProcessingState.failed.value
            payload["processing_error_code"] = error_code
            artifact.result = None
            artifact.extracted_text = None
            artifact.state = ProcessingState.failed.value
            artifact.error = public_message
            artifact.updated_at = datetime.now(UTC)
            job.payload = payload
            job.status = JobStatus.failed
            await db.commit()


@router.post("/upload", response_model=APIResponse, status_code=status.HTTP_201_CREATED)
async def upload_file(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    document_type: str = Form(default="auto"),
    auto_process: bool = Form(default=True),
    db: AsyncSession = Depends(get_db),
) -> APIResponse:
    document_type = document_type.lower().strip()
    if document_type not in {"auto", "invoice", "contract"}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="document_type must be auto, invoice, or contract",
        )

    filename = _safe_filename(file.filename)
    extension = Path(filename).suffix.lower()
    if extension not in settings.extensions:
        allowed = ", ".join(sorted(settings.extensions))
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported file type. Allowed extensions: {allowed}",
        )

    job = Job(
        payload={
            "type": document_type,
            "content": {"filename": filename, "source": "file_upload"},
            "processing_state": (
                ProcessingState.queued.value if auto_process else ProcessingState.uploaded.value
            ),
        },
        status=JobStatus.pending,
    )
    db.add(job)
    await db.flush()

    destination_dir = settings.storage_dir / job.id
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / filename
    size = 0
    try:
        with destination.open("wb") as output:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > settings.upload_size_bytes:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"File exceeds {settings.max_upload_size_mb} MB limit",
                    )
                output.write(chunk)
        if size == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file is empty"
            )
        validate_document_file(
            destination,
            extension,
            supplied_mime=file.content_type,
            limits=_parser_limits(),
        )
    except DocumentProcessingError as exc:
        shutil.rmtree(destination_dir, ignore_errors=True)
        await db.rollback()
        code_status = (
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
            if exc.code == "resource_limit_exceeded"
            else status.HTTP_415_UNSUPPORTED_MEDIA_TYPE
        )
        raise HTTPException(status_code=code_status, detail=exc.public_message) from exc
    except Exception:
        shutil.rmtree(destination_dir, ignore_errors=True)
        await db.rollback()
        raise
    finally:
        await file.close()

    artifact = DocumentArtifact(
        job_id=job.id,
        original_filename=filename,
        stored_path=str(destination.resolve()),
        mime_type=file.content_type or "application/octet-stream",
        extension=extension,
        size_bytes=size,
        sha256=sha256_file(destination),
        requested_type=document_type,
        state=(ProcessingState.queued.value if auto_process else ProcessingState.uploaded.value),
    )
    try:
        db.add(artifact)
        await db.commit()
    except Exception:
        await db.rollback()
        shutil.rmtree(destination_dir, ignore_errors=True)
        raise

    if auto_process:
        background_tasks.add_task(process_uploaded_document_task, UUID(job.id))

    return APIResponse(
        message="Document uploaded and queued" if auto_process else "Document uploaded",
        data=_serialize_artifact(artifact, job),
    )


# Fixed paths must remain above /{job_id}; this prevents UUID route shadowing.
@router.get("/metrics/summary", response_model=APIResponse)
async def metrics_summary(db: AsyncSession = Depends(get_db)) -> APIResponse:
    result = await db.execute(
        select(DocumentArtifact.state, func.count(DocumentArtifact.id)).group_by(
            DocumentArtifact.state
        )
    )
    counts = {state: count for state, count in result.all()}
    return APIResponse(
        message="Document metrics fetched",
        data={
            "total": sum(counts.values()),
            "uploaded": counts.get(ProcessingState.uploaded.value, 0),
            "queued": counts.get(ProcessingState.queued.value, 0),
            "processing": counts.get(ProcessingState.processing.value, 0),
            "completed": counts.get(ProcessingState.completed.value, 0),
            "failed": counts.get(ProcessingState.failed.value, 0),
        },
    )


@router.get("", response_model=APIResponse)
async def list_documents(
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> APIResponse:
    result = await db.execute(
        select(DocumentArtifact, Job)
        .join(Job, Job.id == DocumentArtifact.job_id)
        .order_by(DocumentArtifact.created_at.desc())
        .limit(limit)
    )
    documents = [_serialize_artifact(artifact, job) for artifact, job in result.all()]
    return APIResponse(
        message="Documents fetched", data={"items": documents, "count": len(documents)}
    )


@router.post("/{job_id}/process", response_model=APIResponse)
async def process_file(
    job_id: UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> APIResponse:
    artifact = await _artifact_or_404(job_id, db)
    if artifact.state == ProcessingState.completed.value:
        raise HTTPException(status_code=400, detail="Document is already completed")
    if artifact.state in {ProcessingState.queued.value, ProcessingState.processing.value}:
        raise HTTPException(status_code=409, detail="Document is already queued or processing")

    claim = await db.execute(
        update(DocumentArtifact)
        .where(
            DocumentArtifact.job_id == str(job_id),
            DocumentArtifact.state.in_(
                [ProcessingState.uploaded.value, ProcessingState.failed.value]
            ),
        )
        .values(state=ProcessingState.queued.value, error=None, updated_at=datetime.now(UTC))
    )
    if claim.rowcount != 1:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Document could not be queued")
    await db.commit()
    background_tasks.add_task(process_uploaded_document_task, job_id)
    return APIResponse(
        message="Document processing queued",
        data={"job_id": str(job_id), "state": ProcessingState.queued.value},
    )


@router.get("/{job_id}", response_model=APIResponse)
async def document_status(job_id: UUID, db: AsyncSession = Depends(get_db)) -> APIResponse:
    artifact = await _artifact_or_404(job_id, db)
    job_result = await db.execute(select(Job).where(Job.id == str(job_id)))
    job = job_result.scalar_one_or_none()
    return APIResponse(message="Document status fetched", data=_serialize_artifact(artifact, job))


@router.get("/{job_id}/download")
async def download_original(job_id: UUID, db: AsyncSession = Depends(get_db)) -> FileResponse:
    artifact = await _artifact_or_404(job_id, db)
    storage_root = settings.storage_dir.resolve()
    path = Path(artifact.stored_path).resolve()
    if not path.is_relative_to(storage_root):
        logger.error("Stored source path escaped storage", extra={"job_id": str(job_id)})
        raise HTTPException(status_code=404, detail="Stored file is unavailable")
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Stored file is unavailable")
    return FileResponse(
        path=path, filename=artifact.original_filename, media_type=artifact.mime_type
    )
