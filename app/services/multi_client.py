"""Client for interacting with upstream Multi AI API."""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any, AsyncGenerator, Dict, List, Optional
import httpx

from app.core.config import settings
from app.core.exceptions import UpstreamMultiError
from app.services.account_manager import account_manager

logger = logging.getLogger(__name__)


class MultiClient:
    def __init__(self):
        self.base_url = settings.MULTI_BASE_URL.rstrip("/")
        self.proxy = settings.PROXY
        self.timeout = settings.REQUEST_TIMEOUT
        self._cached_models: List[Dict[str, Any]] = []
        self._models_cached_at: float = 0.0

    async def get_bootstrap_models(self, id_token: Optional[str] = None) -> List[Dict[str, Any]]:
        """Fetch models from /api/bootstrap and cache for 10 minutes."""
        now = time.time()
        if self._cached_models and (now - self._models_cached_at < 600):
            return self._cached_models

        token = id_token
        if not token:
            try:
                acc = await account_manager.get_healthy_account()
                token = acc.get("id_token")
            except Exception:
                pass

        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"

        url = f"{self.base_url}/api/bootstrap?include=models,config,settings"
        try:
            async with httpx.AsyncClient(timeout=20.0, proxy=self.proxy) as client:
                resp = client.get(url, headers=headers)
                resp = await resp
                if resp.status_code == 200:
                    data = resp.json()
                    models = data.get("models", {}).get("models", [])
                    if models:
                        self._cached_models = models
                        self._models_cached_at = now
                        return models
        except Exception as e:
            logger.warning(f"Failed to fetch bootstrap models: {e}")

        return self._cached_models

    def _prepare_payload(self, model: str, messages: List[Dict[str, Any]], stream: bool = True) -> Dict[str, Any]:
        """Convert OpenAI chat messages and model into Multi AI format."""
        target_model = model or settings.DEFAULT_MODEL
        # Check if freeMode should be enabled
        is_free = target_model.endswith(":free") or settings.FREE_MODE

        return {
            "modelId": target_model,
            "modelSlug": target_model,
            "tool": "compare",
            "purpose": "chat",
            "freeMode": is_free,
            "webSearch": False,
            "toolContextToken": None,
            "messages": messages
        }

    async def stream_chat(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        request_id: Optional[str] = None
    ) -> AsyncGenerator[str, None]:
        """Stream SSE chunks from Multi AI, formatted for OpenAI clients."""
        account = await account_manager.get_healthy_account()
        id_token = account.get("id_token")
        acc_id = account.get("id")

        payload = self._prepare_payload(model, messages, stream=True)
        req_id = request_id or str(uuid.uuid4())

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {id_token}",
            "X-Request-Id": req_id,
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
        }
        cookies = {}
        if account.get("multi_cookie"):
            cookies["multi_auth"] = account["multi_cookie"]

        chat_url = f"{self.base_url}/api/chat"
        gen_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
        created_ts = int(time.time())

        total_prompt_tokens = 0
        total_completion_tokens = 0

        try:
            async with httpx.AsyncClient(timeout=self.timeout, proxy=self.proxy) as client:
                async with client.stream("POST", chat_url, json=payload, headers=headers, cookies=cookies) as resp:
                    if resp.status_code != 200:
                        error_body = await resp.aread()
                        error_text = error_body.decode("utf-8", errors="ignore")
                        logger.error(f"Multi /api/chat error ({resp.status_code}): {error_text}")
                        await account_manager.report_failure(acc_id, f"HTTP {resp.status_code}: {error_text[:100]}")
                        raise UpstreamMultiError(f"Multi API error {resp.status_code}: {error_text}", status_code=resp.status_code)

                    # Initial empty role chunk
                    init_chunk = {
                        "id": gen_id,
                        "object": "chat.completion.chunk",
                        "created": created_ts,
                        "model": model,
                        "choices": [{
                            "index": 0,
                            "delta": {"role": "assistant", "content": ""},
                            "finish_reason": None
                        }]
                    }
                    yield f"data: {json.dumps(init_chunk)}\n\n"

                    async for line in resp.aiter_lines():
                        if not line or not line.strip():
                            continue

                        # Skip keep-alive comments like ": OPENROUTER PROCESSING"
                        if line.startswith(":"):
                            continue

                        if line.startswith("data:"):
                            data_str = line[5:].strip()
                            if data_str == "[DONE]":
                                break

                            try:
                                chunk_json = json.loads(data_str)
                                choices = chunk_json.get("choices", [])
                                if not choices:
                                    continue

                                delta = choices[0].get("delta", {})
                                finish_reason = choices[0].get("finish_reason")
                                content = delta.get("content", "")
                                reasoning = delta.get("reasoning", "")

                                # Usage tracking if present
                                if "usage" in chunk_json:
                                    usage = chunk_json["usage"]
                                    total_prompt_tokens = usage.get("prompt_tokens", total_prompt_tokens)
                                    total_completion_tokens = usage.get("completion_tokens", total_completion_tokens)

                                # Build standard OpenAI delta
                                out_delta: Dict[str, Any] = {}
                                if content:
                                    out_delta["content"] = content
                                if reasoning:
                                    out_delta["reasoning_content"] = reasoning

                                if out_delta or finish_reason:
                                    out_chunk = {
                                        "id": gen_id,
                                        "object": "chat.completion.chunk",
                                        "created": created_ts,
                                        "model": model,
                                        "choices": [{
                                            "index": 0,
                                            "delta": out_delta,
                                            "finish_reason": finish_reason
                                        }]
                                    }
                                    yield f"data: {json.dumps(out_chunk)}\n\n"

                            except json.JSONDecodeError:
                                continue

                    # Final DONE
                    yield "data: [DONE]\n\n"
                    await account_manager.report_success(acc_id, total_prompt_tokens, total_completion_tokens)

        except GeneratorExit:
            # Client disconnected early or generator closed normally
            return
        except Exception as e:
            if not isinstance(e, UpstreamMultiError):
                await account_manager.report_failure(acc_id, str(e))
            raise

    async def chat_completion(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        request_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Accumulate streaming response and return standard OpenAI completion JSON."""
        accumulated_content = []
        accumulated_reasoning = []
        finish_reason = "stop"
        gen_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
        created_ts = int(time.time())

        async for chunk_str in self.stream_chat(model, messages, request_id):
            if not chunk_str.startswith("data:"):
                continue
            data_part = chunk_str[5:].strip()
            if data_part == "[DONE]":
                break
            try:
                data = json.loads(data_part)
                choices = data.get("choices", [])
                if choices:
                    delta = choices[0].get("delta", {})
                    if "content" in delta and delta["content"]:
                        accumulated_content.append(delta["content"])
                    if "reasoning_content" in delta and delta["reasoning_content"]:
                        accumulated_reasoning.append(delta["reasoning_content"])
                    if choices[0].get("finish_reason"):
                        finish_reason = choices[0]["finish_reason"]
            except Exception:
                pass

        full_content = "".join(accumulated_content)
        full_reasoning = "".join(accumulated_reasoning)

        message: Dict[str, Any] = {
            "role": "assistant",
            "content": full_content
        }
        if full_reasoning:
            message["reasoning_content"] = full_reasoning

        return {
            "id": gen_id,
            "object": "chat.completion",
            "created": created_ts,
            "model": model,
            "choices": [{
                "index": 0,
                "message": message,
                "finish_reason": finish_reason
            }],
            "usage": {
                "prompt_tokens": len(" ".join(m.get("content", "") for m in messages).split()),
                "completion_tokens": len(full_content.split()),
                "total_tokens": len(" ".join(m.get("content", "") for m in messages).split()) + len(full_content.split())
            }
        }


multi_client = MultiClient()
