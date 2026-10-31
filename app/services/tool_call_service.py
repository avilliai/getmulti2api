"""Tool Call Service directly ported from converseai2api."""

from __future__ import annotations

import copy
import json
import logging
import re
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("getmulti2api.tool_call_service")

_TC_BEGIN = "@@TOOL_CALL_BEGIN@@"
_TC_END = "@@TOOL_CALL_END@@"
_TC_PATTERN = re.compile(
    rf"{re.escape(_TC_BEGIN)}\s*(.*?)\s*{re.escape(_TC_END)}",
    re.DOTALL,
)


class ToolCallService:
    """Tool / Function Calling simulation service according to specifications."""

    def __init__(self):
        self.tc_begin = _TC_BEGIN
        self.tc_end = _TC_END
        self.tc_pattern = _TC_PATTERN

    def convert_tool_messages_to_user(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Normalize messages:
        - 'tool' role -> 'user' with [Tool Result] annotation
        """
        result = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            name = msg.get("name", "")
            if role == "tool":
                text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
                result.append({
                    "role": "user",
                    "content": f"[工具 {name} 返回结果]\n{text}\n请基于这个结果直接回复用户，不要再次调用工具。",
                })
            else:
                result.append({"role": role, "content": content})
        return result

    def annotate_tool_declarations(self, tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Inject required/optional markers into parameter descriptions."""
        annotated = copy.deepcopy(tools)
        for item in annotated:
            func = item.get("function", {})
            params = func.get("parameters", {})
            props = params.get("properties", {})
            required_set = set(params.get("required", []))
            for param_name, param_def in props.items():
                desc = param_def.get("description", "")
                tag = "【必填】" if param_name in required_set else "【可选】"
                if not desc.startswith("【"):
                    param_def["description"] = f"{tag} {desc}".strip()
        return annotated

    def build_tool_prompt(self, tools: List[Dict[str, Any]]) -> str:
        """Build injection system instructions that guide the model to output tool call syntax."""
        annotated = self.annotate_tool_declarations(tools)
        tool_json = json.dumps(annotated, ensure_ascii=False, indent=2)
        return (
            "你可以使用以下外部工具来帮助回答用户问题：\n"
            f"{tool_json}\n\n"
            "【工具调用规则】\n"
            "1. 仅当用户需求确实需要外部工具时才调用，常规闲聊或纯知识问答直接回答。\n"
            "2. 如果需要调用工具，请【严格】按照以下格式输出，不要有任何额外前缀或后缀代码块：\n"
            f"{self.tc_begin}\n"
            "{\n"
            '  "name": "工具名称",\n'
            '  "arguments": {\n'
            '    "参数名": "参数值"\n'
            "  }\n"
            "}\n"
            f"{self.tc_end}\n"
            "3. 可以在 @@TOOL_CALL_BEGIN@@ 之前附带对用户的简短说明文本（例如：好的，我来帮您查询...）。\n"
            "4. arguments 必须是合法的 JSON 对象，符合对应工具的参数定义。\n"
            "5. 一次只能输出一个或多个 @@TOOL_CALL_BEGIN@@ ... @@TOOL_CALL_END@@ 块。\n"
        )

    def parse_tool_calls(self, text: str) -> Tuple[List[Dict[str, Any]], str]:
        """Extract tool calls and clean residual text."""
        raw_matches = self.tc_pattern.findall(text)
        tool_calls: List[Dict[str, Any]] = []

        for raw in raw_matches:
            raw = raw.strip()
            try:
                data = json.loads(raw)
                name = data.get("name")
                args = data.get("arguments", {})
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except Exception:
                        pass
                if name:
                    tool_calls.append({
                        "id": f"call_{uuid.uuid4().hex[:12]}",
                        "type": "function",
                        "function": {
                            "name": name,
                            "arguments": json.dumps(args, ensure_ascii=False) if isinstance(args, dict) else str(args),
                        },
                    })
            except Exception as e:
                logger.warning(f"Failed to parse tool call JSON: {e}, raw: {raw}")

        clean_text = self.tc_pattern.sub("", text).strip()
        # Clean any remaining delimiter fragments
        clean_text = clean_text.replace(self.tc_begin, "").replace(self.tc_end, "").strip()
        return tool_calls, clean_text

    def make_tool_call_response(
        self,
        tool_calls: List[Dict[str, Any]],
        model: str,
        completion_id: str,
        content: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Format OpenAI-compatible standard tool completion response."""
        return {
            "id": completion_id,
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": content if content else None,
                        "tool_calls": tool_calls,
                    },
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "total_tokens": 150,
            },
        }

    def make_tool_call_sse(
        self,
        tool_calls: List[Dict[str, Any]],
        model: str,
        completion_id: str,
        content: Optional[str] = None,
    ) -> List[str]:
        """Format streaming OpenAI-compatible tool call SSE chunks."""
        chunks: List[str] = []
        now = int(time.time())

        def _sse(obj: dict) -> str:
            return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"

        if content:
            chunks.append(
                _sse({
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": now,
                    "model": model,
                    "choices": [{
                        "index": 0,
                        "delta": {"role": "assistant", "content": content},
                        "finish_reason": None,
                    }],
                })
            )

        delta_calls = []
        for i, tc in enumerate(tool_calls):
            delta_calls.append({
                "index": i,
                "id": tc.get("id"),
                "type": "function",
                "function": {
                    "name": tc["function"]["name"],
                    "arguments": tc["function"]["arguments"],
                },
            })

        chunks.append(
            _sse({
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": now,
                "model": model,
                "choices": [{
                    "index": 0,
                    "delta": {"tool_calls": delta_calls},
                    "finish_reason": "tool_calls",
                }],
            })
        )
        return chunks


tool_call_service = ToolCallService()