"""Cloudflare Temporary Email Service (ported from converseai2api)."""

from __future__ import annotations

import logging
import random
import re
import string
import time
from typing import Optional, Tuple
import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class CloudflareEmailService:
    def __init__(self):
        self.worker_domain = settings.WORKER_DOMAIN
        self.email_domain = settings.EMAIL_DOMAIN
        self.admin_password = settings.ADMIN_PASSWORD
        self.proxy = settings.PROXY

    def _generate_random_name(self) -> str:
        letters1 = "".join(random.choices(string.ascii_lowercase, k=random.randint(4, 6)))
        numbers = "".join(random.choices(string.digits, k=random.randint(2, 4)))
        letters2 = "".join(random.choices(string.ascii_lowercase, k=random.randint(1, 3)))
        return letters1 + numbers + letters2

    def create_email(self) -> Tuple[Optional[str], Optional[str]]:
        """Create a new temp email on Cloudflare Worker. Returns (jwt, address)."""
        if not all([self.worker_domain, self.email_domain, self.admin_password]):
            logger.warning("Cloudflare temp email settings not configured.")
            return None, None

        url = f"https://{self.worker_domain}/admin/new_address"
        name = self._generate_random_name()
        payload = {
            "enablePrefix": True,
            "name": name,
            "domain": self.email_domain,
        }
        headers = {
            "x-admin-auth": self.admin_password,
            "Content-Type": "application/json",
        }

        try:
            with httpx.Client(timeout=15.0, proxy=self.proxy, verify=False) as client:
                res = client.post(url, json=payload, headers=headers)
                if res.status_code == 200:
                    data = res.json()
                    jwt = data.get("jwt")
                    address = data.get("address")
                    logger.info(f"[CF Email] Created temp address: {address}")
                    return jwt, address
                logger.error(f"[CF Email] Create address failed: {res.status_code} - {res.text}")
                return None, None
        except Exception as e:
            logger.error(f"[CF Email] Network error creating address: {e}")
            return None, None

    def fetch_emails(self, jwt: str) -> list[dict]:
        """Fetch emails for a given address JWT."""
        url = f"https://{self.worker_domain}/api/mails"
        headers = {
            "Authorization": f"Bearer {jwt}",
            "Content-Type": "application/json",
        }
        try:
            with httpx.Client(timeout=15.0, proxy=self.proxy, verify=False) as client:
                res = client.get(url, params={"limit": 10, "offset": 0}, headers=headers)
                if res.status_code == 200:
                    return res.json().get("results", [])
                return []
        except Exception as e:
            logger.error(f"[CF Email] Fetch mails error: {e}")
            return []

    def poll_verification_code(self, jwt: str, timeout: int = 60, interval: int = 3) -> Optional[str]:
        """Poll incoming emails for a 4-8 digit verification code or link."""
        start_time = time.time()
        while time.time() - start_time < timeout:
            emails = self.fetch_emails(jwt)
            for mail in emails:
                raw = mail.get("raw", "") or mail.get("body", "") or mail.get("text", "")
                # search for 6 digit code
                m = re.search(r'\b\d{4,8}\b', raw)
                if m:
                    return m.group(0)
            time.sleep(interval)
        return None
