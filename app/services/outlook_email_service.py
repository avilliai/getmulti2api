"""Outlook account pool service for using valid Outlook accounts."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import httpx

from app.core.config import resolve_project_path, settings

logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class OutlookAccount:
    address: str
    password: str
    client_id: str
    refresh_token: str


class OutlookEmailService:
    def __init__(self):
        self.account_file = resolve_project_path(settings.OUTLOOK_ACCOUNT_FILE)
        self.pointer_file = resolve_project_path("data/outlook_pointer.json")
        self._accounts: list[OutlookAccount] = []
        self._current_index: int = 0
        self._load_accounts()
        self._load_pointer()

    def _load_accounts(self) -> None:
        if not self.account_file.is_file():
            logger.warning(f"Outlook account file not found: {self.account_file}")
            return

        lines = self.account_file.read_text(encoding="utf-8-sig", errors="ignore").splitlines()
        accounts: list[OutlookAccount] = []
        for raw_line in lines:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("----")
            if len(parts) >= 4 and all(part.strip() for part in parts[:4]):
                address, password, client_id, refresh_token = (p.strip() for p in parts[:4])
                if "@" in address:
                    accounts.append(OutlookAccount(address, password, client_id, refresh_token))

        self._accounts = accounts
        logger.info(f"Loaded {len(self._accounts)} valid Outlook accounts from {self.account_file.name}")

    def _load_pointer(self) -> None:
        if self.pointer_file.is_file():
            try:
                data = json.loads(self.pointer_file.read_text(encoding="utf-8"))
                self._current_index = int(data.get("index", 0))
            except Exception:
                self._current_index = 0
        else:
            self._current_index = 0

    def _save_pointer(self) -> None:
        try:
            self.pointer_file.parent.mkdir(parents=True, exist_ok=True)
            self.pointer_file.write_text(
                json.dumps({"index": self._current_index}, indent=2),
                encoding="utf-8"
            )
        except Exception as e:
            logger.warning(f"Failed to save outlook pointer: {e}")

    def get_next_account(self) -> Optional[OutlookAccount]:
        """Get the next Outlook account from the pool and advance the pointer."""
        if not self._accounts:
            return None

        idx = self._current_index % len(self._accounts)
        account = self._accounts[idx]
        self._current_index = idx + 1
        self._save_pointer()
        return account

    @property
    def total_accounts(self) -> int:
        return len(self._accounts)

    @property
    def current_index(self) -> int:
        return self._current_index
