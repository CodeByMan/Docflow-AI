from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.extended_models import DocumentArtifact, ProcessingState
from app.models import Job, JobStatus

INTERRUPTED_MESSAGE = "Processing was interrupted; retry the document"


async def recover_interrupted_jobs(db: AsyncSession) -> int:
    """Fail active states left behind by an earlier API process.

    BackgroundTasks are process-local. At application startup, no persisted
    queued or processing state can still have a live task in this architecture.
    """

    result = await db.execute(
        select(DocumentArtifact, Job)
        .join(Job, Job.id == DocumentArtifact.job_id)
        .where(
            DocumentArtifact.state.in_(
                [ProcessingState.queued.value, ProcessingState.processing.value]
            )
        )
    )
    interrupted = result.all()
    recovered_at = datetime.now(UTC)

    for artifact, job in interrupted:
        payload = dict(job.payload or {})
        payload["processing_state"] = ProcessingState.failed.value
        payload["processing_error_code"] = "processing_interrupted"
        artifact.state = ProcessingState.failed.value
        artifact.error = INTERRUPTED_MESSAGE
        artifact.result = None
        artifact.updated_at = recovered_at
        job.payload = payload
        job.status = JobStatus.failed

    if interrupted:
        await db.commit()
    return len(interrupted)
