"""API Key authentication dependency."""

from __future__ import annotations

from fastapi import Header, HTTPException, status
from app.core.config import settings


async def verify_api_key(authorization: str | None = Header(None)) -> str | None:
    expected_key = settings.API_KEY.strip()
    if not expected_key:
        return None  # Public access permitted

    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": {"message": "Missing Authorization header", "type": "auth_error"}}
        )

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or token.strip() != expected_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": {"message": "Invalid API key", "type": "auth_error"}}
        )

    return token
