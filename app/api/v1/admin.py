"""Admin management routes."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.core.dependencies import ApiKeyDep
from app.services.account_manager import account_manager
from app.services.multi_register import MultiRegisterService

logger = logging.getLogger(__name__)
router = APIRouter()
register_service = MultiRegisterService()


class BatchRegisterRequest(BaseModel):
    count: int = 1
    provider: str = "cf_mail"  # 'cf_mail', 'outlook', or 'random'


@router.get("/admin/stats")
async def get_stats(_: ApiKeyDep) -> Dict[str, Any]:
    """Get pool statistics."""
    return account_manager.get_pool_stats()


@router.get("/admin/accounts")
async def get_accounts(_: ApiKeyDep) -> List[Dict[str, Any]]:
    """List all accounts in the pool with masked credentials."""
    accounts = account_manager.list_accounts()
    safe_list = []
    for acc in accounts:
        item = dict(acc)
        if "password" in item:
            item["password"] = "******"
        if "refresh_token" in item and item["refresh_token"]:
            item["refresh_token"] = item["refresh_token"][:8] + "..."
        if "id_token" in item and item["id_token"]:
            item["id_token"] = item["id_token"][:12] + "..."
        safe_list.append(item)
    return safe_list


@router.post("/admin/accounts/batch-register")
async def batch_register(req: BatchRegisterRequest, _: ApiKeyDep) -> Dict[str, Any]:
    """Batch register multiple accounts into the pool."""
    registered = []
    errors = []
    for i in range(req.count):
        try:
            acc = register_service.register_account(provider=req.provider)
            await account_manager.add_account(acc)
            registered.append(acc.get("email"))
        except Exception as e:
            errors.append(str(e))

    return {
        "success": len(registered) > 0,
        "requested": req.count,
        "registered_count": len(registered),
        "registered_emails": registered,
        "errors": errors
    }


@router.delete("/admin/accounts/{account_id}")
async def delete_account(account_id: str, _: ApiKeyDep) -> Dict[str, Any]:
    """Remove an account from the pool."""
    deleted = await account_manager.delete_account(account_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Account not found")
    return {"success": True, "message": f"Account {account_id} removed from pool"}


@router.post("/admin/accounts/{account_id}/refresh")
async def force_refresh_token(account_id: str, _: ApiKeyDep) -> Dict[str, Any]:
    """Force refresh Firebase token for a specific account."""
    accounts = account_manager.list_accounts()
    target = next((a for a in accounts if a.get("id") == account_id or a.get("email") == account_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="Account not found")

    refreshed = account_manager.refresh_firebase_token(target)
    if not refreshed:
        raise HTTPException(status_code=500, detail="Token refresh failed")

    account_manager._save_accounts()
    return {"success": True, "message": f"Token refreshed for {target.get('email')}"}
