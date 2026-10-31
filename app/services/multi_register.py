"""Multi AI Registration Service."""

from __future__ import annotations

import logging
import random
import secrets
import string
import time
import uuid
from typing import Any, Dict, Optional, Tuple
import httpx

from app.core.config import settings
from app.core.exceptions import RegistrationError
from app.services.cf_email_service import CloudflareEmailService
from app.services.outlook_email_service import OutlookEmailService

logger = logging.getLogger(__name__)


def generate_secure_password(length: int = 16) -> str:
    """Generate a strong password matching standard complexity requirements."""
    chars = string.ascii_letters + string.digits + "!@#$%^&*"
    # Ensure at least 1 uppercase, 1 lowercase, 1 digit, 1 special
    pwd = [
        secrets.choice(string.ascii_uppercase),
        secrets.choice(string.ascii_lowercase),
        secrets.choice(string.digits),
        secrets.choice("!@#$%^&*")
    ]
    pwd += [secrets.choice(chars) for _ in range(length - 4)]
    random.shuffle(pwd)
    return "".join(pwd)


class MultiRegisterService:
    def __init__(self):
        self.cf_service = CloudflareEmailService()
        self.outlook_service = OutlookEmailService()
        self.firebase_api_key = settings.FIREBASE_API_KEY
        self.base_url = settings.MULTI_BASE_URL.rstrip("/")
        self.proxy = settings.PROXY

    def _firebase_signup(self, email: str, password: str) -> Dict[str, Any]:
        """Sign up with email and password via Firebase Auth REST API."""
        url = f"https://identitytoolkit.googleapis.com/v1/accounts:signUp?key={self.firebase_api_key}"
        payload = {
            "email": email,
            "password": password,
            "returnSecureToken": True
        }
        with httpx.Client(timeout=20.0, proxy=self.proxy) as client:
            resp = client.post(url, json=payload)
            if resp.status_code != 200:
                raise RegistrationError(f"Firebase signUp failed ({resp.status_code}): {resp.text}")
            return resp.json()

    def _multi_register(self, id_token: str) -> Tuple[Dict[str, Any], Optional[str]]:
        """Call Multi backend /api/auth/register with firebaseToken."""
        url = f"{self.base_url}/api/auth/register"
        payload = {"firebaseToken": id_token}
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
        }
        with httpx.Client(timeout=25.0, proxy=self.proxy, follow_redirects=True) as client:
            resp = client.post(url, json=payload, headers=headers)
            if resp.status_code not in (200, 201):
                raise RegistrationError(f"Multi register failed ({resp.status_code}): {resp.text}")

            multi_cookie = client.cookies.get("multi_auth")
            data = resp.json() if resp.text else {}
            return data, multi_cookie

    def register_account(
        self,
        provider: str = "cf_mail",
        email: Optional[str] = None,
        password: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Register a new account on web.getmulti.ai.
        provider: 'cf_mail', 'outlook', or 'random'
        """
        chosen_provider = provider.lower()
        target_email = email
        target_password = password or generate_secure_password(16)

        # 1. Determine email address
        if not target_email:
            if chosen_provider == "cf_mail":
                jwt, address = self.cf_service.create_email()
                if not address:
                    logger.warning("CF temp mail creation failed, falling back to random/outlook")
                    chosen_provider = "random"
                else:
                    target_email = address

            if chosen_provider == "outlook":
                outlook_acc = self.outlook_service.get_next_account()
                if outlook_acc:
                    target_email = outlook_acc.address
                else:
                    logger.warning("No Outlook accounts available, falling back to random")
                    chosen_provider = "random"

            if chosen_provider == "random":
                rand_id = uuid.uuid4().hex[:10]
                target_email = f"user_{rand_id}@test"

        logger.info(f"Registering new account with {chosen_provider}: {target_email}")

        # 2. Firebase sign up
        fb_data = self._firebase_signup(target_email, target_password)
        id_token = fb_data.get("idToken")
        refresh_token = fb_data.get("refreshToken")
        local_id = fb_data.get("localId")
        expires_in = int(fb_data.get("expiresIn", "3600"))

        if not id_token:
            raise RegistrationError("Firebase did not return an idToken")

        # 3. Multi backend registration
        multi_data, multi_cookie = self._multi_register(id_token)
        user_info = multi_data.get("user", {})
        user_id = user_info.get("id", local_id)
        display_name = user_info.get("displayName", target_email.split("@")[0])

        now = time.time()
        account_record = {
            "id": f"acc_{uuid.uuid4().hex[:10]}",
            "email": target_email,
            "password": target_password,
            "firebase_uid": local_id,
            "id_token": id_token,
            "refresh_token": refresh_token,
            "token_expires_at": now + expires_in,
            "multi_cookie": multi_cookie,
            "user_id": user_id,
            "display_name": display_name,
            "provider": chosen_provider,
            "status": "active",
            "consecutive_failures": 0,
            "total_requests": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "created_at": now,
            "last_used_at": 0.0,
            "rate_limited_until": 0.0,
        }

        logger.info(f"Successfully registered Multi account: {target_email} (user_id: {user_id})")
        return account_record
