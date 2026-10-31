"""OpenAI-compatible Models API route with multi-tier & free filtering."""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Query
from app.core.dependencies import ApiKeyDep
from app.services.multi_client import multi_client

router = APIRouter()

# 精准匹配 GetMulti 官方的 13 款主流免费模型（以及 openrouter/free 路由）
FREE_MODEL_REGISTRY = [
    {
        "id": "nvidia/nemotron-3-ultra-550b-a55b:free",
        "name": "Nemotron 3 Ultra",
        "vendor": "NVIDIA",
        "context": "1000K",
        "tag": "Free",
        "description": "NVIDIA Flagship Free Model 550B MoE"
    },
    {
        "id": "nvidia/nemotron-3.5-super-vl:free",
        "name": "Nemotron 3.5 Super VL",
        "vendor": "NVIDIA",
        "context": "1000K",
        "tag": "Free",
        "description": "NVIDIA Vision-Language Super Model"
    },
    {
        "id": "nvidia/nemotron-3.5-lightning:free",
        "name": "Nemotron 3.5 Lightning",
        "vendor": "NVIDIA",
        "context": "1000K",
        "tag": "Free",
        "description": "NVIDIA High-Speed Reasoning Model"
    },
    {
        "id": "dots-studio/dots-3-note-preview:free",
        "name": "Dots3-Note Preview",
        "vendor": "Dots Studio",
        "context": "512K",
        "tag": "Free",
        "description": "Dots Studio Long-form Note & Knowledge Model"
    },
    {
        "id": "thinkingmachines/inkling:free",
        "name": "Inkling",
        "vendor": "Thinkingmachines",
        "context": "1049K",
        "tag": "Free",
        "description": "Thinking Machines 1M Context Reasoning"
    },
    {
        "id": "thinkingmachines/inkling-small:free",
        "name": "Inkling Small",
        "vendor": "Thinkingmachines",
        "context": "1049K",
        "tag": "Free",
        "description": "Thinking Machines Lightweight Fast Model"
    },
    {
        "id": "cohere/north-mini-code:free",
        "name": "North Mini Code",
        "vendor": "Cohere",
        "context": "256K",
        "tag": "Free",
        "description": "Cohere Coding & Technical Reasoning"
    },
    {
        "id": "recursive/flint-v1.0:free",
        "name": "Flint",
        "vendor": "Recursive",
        "context": "262K",
        "tag": "Free",
        "description": "Recursive Flint v1.0 High-Intelligence Model"
    },
    {
        "id": "xingchen-agi/xing4.0-29b-a4b:free",
        "name": "Xing4.0 29B A4B",
        "vendor": "Xingchen Agi",
        "context": "262K",
        "tag": "Free",
        "description": "XingChen Advanced Chinese/Multilingual MoE"
    },
    {
        "id": "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
        "name": "Nemotron 3 Nano Omni",
        "vendor": "NVIDIA",
        "context": "256K",
        "tag": "Free",
        "description": "NVIDIA Omni Multimodal & Reasoning"
    },
    {
        "id": "liquid/lfm-2.5-2.6b:free",
        "name": "LFM2.5-2.6B",
        "vendor": "Liquid",
        "context": "66K",
        "tag": "Free",
        "description": "Liquid AI Liquid Foundation Model"
    },
    {
        "id": "google/gemma-4-26b-a4b-it:free",
        "name": "Gemma 4 26B A4B",
        "vendor": "Google",
        "context": "262K",
        "tag": "Free",
        "description": "Google Gemma 4 Efficient 26B"
    },
    {
        "id": "google/gemma-4-31b-it:free",
        "name": "Gemma 4 31B",
        "vendor": "Google",
        "context": "262K",
        "tag": "Free",
        "description": "Google Gemma 4 Dense 31B"
    },
    {
        "id": "openrouter/free",
        "name": "Free Models Router",
        "vendor": "OpenRouter",
        "context": "200K",
        "tag": "Free",
        "description": "Auto-routed free models"
    }
]


def _prefix_model_id(model_id: str) -> str:
    if not model_id:
        return model_id
    if model_id.startswith("gb/"):
        return model_id
    return f"gb/{model_id}"


def _format_context(ctx_num: Any) -> str:
    try:
        n = int(ctx_num)
        if n >= 1000000:
            return f"{round(n / 1000)}K"
        elif n >= 1000:
            return f"{round(n / 1024)}K"
        return str(n)
    except Exception:
        return "128K"


@router.get("/models")
async def list_models(
    _: ApiKeyDep,
    free_only: bool = Query(True, description="Default True: return only 100% available free models matching official UI. Set free_only=false to list all 400+ models.")
) -> Dict[str, Any]:
    """
    OpenAI-compatible /v1/models endpoint.
    - 默认 free_only=True 返回完全对齐官网界面的 13 款免费精选模型 + 智能路由
    - 设置 free_only=False 返回上游全量 412 个模型
    """
    now = int(time.time())
    bootstrap_models = await multi_client.get_bootstrap_models()

    if free_only:
        # Build quick map from upstream bootstrap
        upstream_map = {m.get("id"): m for m in bootstrap_models} if bootstrap_models else {}
        models_data = []

        for item in FREE_MODEL_REGISTRY:
            m_id = item["id"]
            up = upstream_map.get(m_id, {})
            ctx = _format_context(up.get("contextLength")) if up.get("contextLength") else item["context"]
            
            models_data.append({
                "id": _prefix_model_id(m_id),
                "object": "model",
                "created": up.get("created", now),
                "owned_by": item["vendor"],
                "name": item["name"],
                "context_window": ctx,
                "is_free": True,
                "description": up.get("description") or item["description"],
                "permission": [],
                "root": _prefix_model_id(m_id),
                "parent": None
            })

        return {
            "object": "list",
            "data": models_data
        }

    # All upstream models
    models_data = []
    for m in bootstrap_models:
        model_id = m.get("id")
        if not model_id:
            continue
        vendor = model_id.split("/")[0].title() if "/" in model_id else "Multi-AI"
        pricing = m.get("pricing", {})
        is_free = (pricing.get("prompt") == "0" and pricing.get("completion") == "0") or ":free" in model_id

        models_data.append({
            "id": _prefix_model_id(model_id),
            "object": "model",
            "created": m.get("created", now),
            "owned_by": vendor,
            "name": m.get("name", model_id),
            "context_window": _format_context(m.get("contextLength")),
            "is_free": is_free,
            "permission": [],
            "root": _prefix_model_id(model_id),
            "parent": None
        })

    return {
        "object": "list",
        "data": models_data
    }