"""FastAPI dependencies."""

from __future__ import annotations

from typing import Annotated
from fastapi import Depends
from app.core.auth import verify_api_key

ApiKeyDep = Annotated[str | None, Depends(verify_api_key)]
