"""Account registration API route."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.core.dependencies import ApiKeyDep
from app.core.exceptions import RegistrationError
from app.services.account_manager import account_manager
from app.services.multi_register import MultiRegisterService

logger = logging.getLogger(__name__)
router = APIRouter()
register_service = MultiRegisterService()


class RegisterRequest(BaseModel):
    provider: Optional[str] = "cf_mail"  # 'cf_mail', 'outlook', or 'random'
    email: Optional[str] = None
    password: Optional[str] = None


@router.post("/register")
async def register_account(
    req: RegisterRequest,
    _: ApiKeyDep
) -> Dict[str, Any]:
    """
    Register a new Multi AI account and add it to the pool.
    - provider: 'cf_mail' (Cloudflare temp email), 'outlook' (Outlook pool), or 'random'
    """
    try:
        account_data = register_service.register_account(
            provider=req.provider or "cf_mail",
            email=req.email,
            password=req.password
        )
        await account_manager.add_account(account_data)

        # Return safe account representation (hide raw refresh token)
        safe_acc = dict(account_data)
        if "refresh_token" in safe_acc:
            safe_acc["refresh_token"] = safe_acc["refresh_token"][:10] + "..."

        return {
            "success": True,
            "message": "Account registered and added to pool successfully",
            "account": safe_acc
        }
    except RegistrationError as e:
        raise HTTPException(status_code=400, detail={"error": {"message": str(e), "type": "registration_error"}})
    except Exception as e:
        logger.error(f"Registration error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail={"error": {"message": str(e), "type": "server_error"}})


@router.get("/register")
async def register_account_get(
    _: ApiKeyDep,
    provider: str = Query("cf_mail", description="Provider: cf_mail, outlook, or random")
) -> Dict[str, Any]:
    """Convenience GET endpoint to quickly trigger registration."""
    return await register_account(RegisterRequest(provider=provider), _)
