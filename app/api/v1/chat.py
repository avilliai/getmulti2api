"""OpenAI-compatible Chat Completions API route with Function Calling."""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any, AsyncGenerator, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.core.dependencies import ApiKeyDep
from app.services.multi_client import multi_client
from app.services.tool_call_service import tool_call_service

logger = logging.getLogger(__name__)
router = APIRouter()


class ChatCompletionRequest(BaseModel):
    model: str = "auto"
    messages: List[Dict[str, Any]]
    stream: Optional[bool] = False
    temperature: Optional[float] = 0.7
    top_p: Optional[float] = 1.0
    tools: Optional[List[Dict[str, Any]]] = None
    tool_choice: Optional[Any] = "auto"

    class Config:
        extra = "allow"


def _format_stream_chunk(
    content: str,
    model: str,
    completion_id: str,
    finish_reason: Optional[str] = None,
) -> str:
    chunk = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": {"content": content} if content else {},
                "finish_reason": finish_reason,
            }
        ],
    }
    return f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"


def _build_injection_messages(
    messages: List[Dict[str, Any]],
    tool_sys_prompt: str,
) -> List[Dict[str, Any]]:
    """Inject tool call instructions into messages."""
    clean_messages = tool_call_service.convert_tool_messages_to_user(messages)

    system_contents: List[str] = []
    other_messages: List[Dict[str, Any]] = []

    for msg in clean_messages:
        if msg.get("role") == "system":
            c = msg.get("content")
            if c:
                system_contents.append(str(c))
        else:
            other_messages.append(dict(msg))

    combined_sys = tool_sys_prompt
    if system_contents:
        sep = "\n\n"
        combined_sys = sep.join(system_contents) + sep + tool_sys_prompt

    if not other_messages:
        return [{"role": "user", "content": combined_sys}]

    first_msg = other_messages[0]
    if first_msg.get("role") == "user":
        orig_content = first_msg.get("content", "")
        first_msg["content"] = f"{combined_sys}\n\n[User]\n{orig_content}"
        return other_messages
    else:
        return [{"role": "user", "content": combined_sys}] + other_messages


@router.post("/chat/completions")
async def chat_completions(
    req: ChatCompletionRequest,
    _: ApiKeyDep,
    raw_request: Request,
):
    """
    OpenAI-compatible /v1/chat/completions endpoint.
    Supports Function Calling (tool_calls), SSE streaming, and account pooling.
    """
    raw_body = await raw_request.json()
    tools = raw_body.get("tools") or req.tools or []
    tool_choice = raw_body.get("tool_choice") or req.tool_choice or "auto"

    has_tools = bool(tools) and tool_choice != "none"
    tool_sys_prompt = ""
    if has_tools:
        tool_sys_prompt = tool_call_service.build_tool_prompt(tools)

    model = req.model or "auto"
    upstream_model = model[3:] if model.startswith("gb/") else model
    completion_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"

    if has_tools:
        upstream_messages = _build_injection_messages(req.messages, tool_sys_prompt)
    else:
        upstream_messages = req.messages

    if req.stream:
        return StreamingResponse(
            _stream_chat_response(
                model=model,
                upstream_model=upstream_model,
                messages=upstream_messages,
                completion_id=completion_id,
                has_tools=has_tools,
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    else:
        return await _non_stream_chat_response(
            model=model,
            upstream_model=upstream_model,
            messages=upstream_messages,
            completion_id=completion_id,
            has_tools=has_tools,
        )


async def _non_stream_chat_response(
    model: str,
    upstream_model: str,
    messages: List[Dict[str, Any]],
    completion_id: str,
    has_tools: bool = False,
) -> JSONResponse:
    """Handle non-streaming completion with tool calling support."""
    resp = await multi_client.chat_completion(model=upstream_model, messages=messages)
    resp["model"] = model
    content = resp.get("choices", [{}])[0].get("message", {}).get("content", "")

    if has_tools:
        tool_calls, cleaned_content = tool_call_service.parse_tool_calls(content)
        if tool_calls:
            fc_resp = tool_call_service.make_tool_call_response(
                tool_calls=tool_calls,
                model=model,
                completion_id=completion_id,
                content=cleaned_content,
            )
            return JSONResponse(content=fc_resp)

    resp["id"] = completion_id
    return JSONResponse(content=resp)


async def _stream_chat_response(
    model: str,
    upstream_model: str,
    messages: List[Dict[str, Any]],
    completion_id: str,
    has_tools: bool = False,
) -> AsyncGenerator[str, None]:
    """Handle streaming SSE chunks with tool calling parsing."""
    accumulated: List[str] = []
    is_tool_call_candidate = False

    try:
        async for chunk_str in multi_client.stream_chat(model=upstream_model, messages=messages):
            if not chunk_str.startswith("data:"):
                continue
            data_part = chunk_str[5:].strip()
            if data_part == "[DONE]":
                break

            try:
                data = json.loads(data_part)
                delta = data.get("choices", [{}])[0].get("delta", {})
                content = delta.get("content", "")
            except Exception:
                content = ""

            if not content:
                continue

            if has_tools:
                accumulated.append(content)
                buffer = "".join(accumulated)

                if "@@TOOL_CALL_BEGIN@@" in buffer:
                    is_tool_call_candidate = True
                    continue

                if not is_tool_call_candidate:
                    if any(
                        "@@TOOL_CALL_BEGIN@@".startswith(buffer[-i:])
                        for i in range(1, len("@@TOOL_CALL_BEGIN@@"))
                    ):
                        continue
                    yield _format_stream_chunk(content, model, completion_id)
            else:
                yield _format_stream_chunk(content, model, completion_id)

        if has_tools and is_tool_call_candidate:
            full_text = "".join(accumulated)
            tool_calls, cleaned = tool_call_service.parse_tool_calls(full_text)

            if tool_calls:
                for sse in tool_call_service.make_tool_call_sse(
                    tool_calls=tool_calls,
                    model=model,
                    completion_id=completion_id,
                    content=cleaned,
                ):
                    yield sse
                yield "data: [DONE]\n\n"
                return
            else:
                if full_text:
                    yield _format_stream_chunk(full_text, model, completion_id)

        yield _format_stream_chunk("", model, completion_id, finish_reason="stop")
        yield "data: [DONE]\n\n"

    except Exception as e:
        logger.error(f"Stream error: {e}")
        yield _format_stream_chunk(f"Error: {e}", model, completion_id, finish_reason="stop")
        yield "data: [DONE]\n\n"