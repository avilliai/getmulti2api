"""Account Pool Manager for Multi AI."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
import httpx

from app.core.config import resolve_project_path, settings
from app.core.exceptions import AccountPoolExhaustedError
from app.services.multi_register import MultiRegisterService

logger = logging.getLogger(__name__)


class AccountManager:
    def __init__(self):
        self.account_file = resolve_project_path(settings.ACCOUNT_FILE)
        self.register_service = MultiRegisterService()
        self._accounts: List[Dict[str, Any]] = []
        self._lock = asyncio.Lock()
        self._rr_index = 0
        self._load_accounts()

    def _load_accounts(self) -> None:
        if self.account_file.is_file():
            try:
                content = self.account_file.read_text(encoding="utf-8")
                self._accounts = json.loads(content)
                logger.info(f"Loaded {len(self._accounts)} accounts from {self.account_file}")
            except Exception as e:
                logger.error(f"Failed to load accounts file: {e}")
                self._accounts = []
        else:
            self._accounts = []

    def _save_accounts(self) -> None:
        try:
            self.account_file.parent.mkdir(parents=True, exist_ok=True)
            self.account_file.write_text(
                json.dumps(self._accounts, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
        except Exception as e:
            logger.error(f"Failed to save accounts: {e}")

    def refresh_firebase_token(self, account: Dict[str, Any]) -> bool:
        """Refresh id_token using refresh_token via Firebase securetoken endpoint."""
        refresh_token = account.get("refresh_token")
        if not refresh_token:
            return False

        url = f"https://securetoken.googleapis.com/v1/token?key={settings.FIREBASE_API_KEY}"
        payload = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token
        }

        try:
            with httpx.Client(timeout=15.0, proxy=settings.PROXY) as client:
                resp = client.post(url, data=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    new_id_token = data.get("id_token")
                    expires_in = int(data.get("expires_in", "3600"))
                    account["id_token"] = new_id_token
                    account["token_expires_at"] = time.time() + expires_in
                    logger.info(f"[Account Pool] Refreshed id_token for {account.get('email')}")
                    return True
                logger.warning(f"[Account Pool] Token refresh failed for {account.get('email')}: {resp.status_code} {resp.text}")
                return False
        except Exception as e:
            logger.error(f"[Account Pool] Error refreshing token: {e}")
            return False

    async def get_healthy_account(self) -> Dict[str, Any]:
        """Select a healthy active account, automatically refreshing token if needed."""
        async with self._lock:
            now = time.time()
            active_accounts = [
                a for a in self._accounts
                if a.get("status") == "active" and a.get("rate_limited_until", 0) <= now
            ]

            # If no active accounts and auto-register enabled, register a new one immediately
            if not active_accounts and settings.AUTO_REGISTER_ON_EMPTY:
                logger.info("[Account Pool] No active accounts. Auto-registering new account...")
                try:
                    new_acc = self.register_service.register_account(provider="cf_mail")
                    self._accounts.append(new_acc)
                    self._save_accounts()
                    active_accounts.append(new_acc)
                except Exception as e:
                    logger.error(f"[Account Pool] Auto-register failed: {e}")

            if not active_accounts:
                raise AccountPoolExhaustedError("All accounts are disabled, rate-limited, or pool is empty.")

            # Pick account via round-robin / LRU
            self._rr_index = (self._rr_index + 1) % len(active_accounts)
            selected = active_accounts[self._rr_index]

            # Check if id_token needs refresh (refresh 5 minutes before expiration)
            expires_at = selected.get("token_expires_at", 0)
            if expires_at - now < 300:
                success = self.refresh_firebase_token(selected)
                if success:
                    self._save_accounts()

            selected["last_used_at"] = now
            return selected

    async def report_success(self, account_id: str, prompt_tokens: int = 0, completion_tokens: int = 0) -> None:
        """Record successful request and token counts."""
        async with self._lock:
            for acc in self._accounts:
                if acc.get("id") == account_id:
                    acc["consecutive_failures"] = 0
                    acc["total_requests"] = acc.get("total_requests", 0) + 1
                    acc["prompt_tokens"] = acc.get("prompt_tokens", 0) + prompt_tokens
                    acc["completion_tokens"] = acc.get("completion_tokens", 0) + completion_tokens
                    acc["total_tokens"] = acc.get("total_tokens", 0) + prompt_tokens + completion_tokens
                    acc["last_used_at"] = time.time()
                    self._save_accounts()
                    break

    async def report_failure(self, account_id: str, error_msg: str = "") -> None:
        """Record failure and trigger cooldown or disable account if failure limit reached."""
        async with self._lock:
            now = time.time()
            for acc in self._accounts:
                if acc.get("id") == account_id:
                    failures = acc.get("consecutive_failures", 0) + 1
                    acc["consecutive_failures"] = failures
                    acc["last_error"] = error_msg
                    acc["rate_limited_until"] = now + settings.ACCOUNT_COOLDOWN_SECONDS

                    if failures >= settings.ACCOUNT_FAILURE_LIMIT:
                        acc["status"] = "disabled"
                        logger.warning(f"[Account Pool] Account {acc.get('email')} disabled after {failures} consecutive failures.")
                    else:
                        logger.warning(f"[Account Pool] Account {acc.get('email')} in cooldown until {now + settings.ACCOUNT_COOLDOWN_SECONDS}.")

                    self._save_accounts()
                    break

    async def add_account(self, account_data: Dict[str, Any]) -> None:
        async with self._lock:
            self._accounts.append(account_data)
            self._save_accounts()

    async def delete_account(self, account_id: str) -> bool:
        async with self._lock:
            orig_len = len(self._accounts)
            self._accounts = [a for a in self._accounts if a.get("id") != account_id and a.get("email") != account_id]
            if len(self._accounts) < orig_len:
                self._save_accounts()
                return True
            return False

    def list_accounts(self) -> List[Dict[str, Any]]:
        return list(self._accounts)

    def get_pool_stats(self) -> Dict[str, Any]:
        total = len(self._accounts)
        active = sum(1 for a in self._accounts if a.get("status") == "active")
        disabled = sum(1 for a in self._accounts if a.get("status") == "disabled")
        total_tokens = sum(a.get("total_tokens", 0) for a in self._accounts)
        total_requests = sum(a.get("total_requests", 0) for a in self._accounts)
        return {
            "total_accounts": total,
            "active_accounts": active,
            "disabled_accounts": disabled,
            "total_tokens": total_tokens,
            "total_requests": total_requests
        }


account_manager = AccountManager()
