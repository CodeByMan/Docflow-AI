from __future__ import annotations

import hmac

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader

from app.config import Settings, get_settings

api_key_header = APIKeyHeader(name="X-DocFlow-Key", auto_error=False)


async def require_document_access(
    supplied_key: str | None = Security(api_key_header),
    settings: Settings = Depends(get_settings),
) -> None:
    """Allow explicit local mode or require the configured hosted access key."""

    if settings.deployment_mode == "local":
        return

    expected = settings.docflow_api_key.get_secret_value() if settings.docflow_api_key else ""
    if not supplied_key or not hmac.compare_digest(supplied_key, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="A valid document access key is required",
            headers={"WWW-Authenticate": "ApiKey"},
        )
