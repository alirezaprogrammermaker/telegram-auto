"""Cloudflare Workers AI model catalog and aliases."""

from __future__ import annotations

from typing import Any

# Default: best general-purpose model from test-cloudflare-models benchmarks.
DEFAULT_MODEL = "@cf/openai/gpt-oss-120b"

MODEL_ALIASES: dict[str, str] = {
    "fast": "@cf/meta/llama-3.3-70b-instruct-fp8-fast",
    "quality": "@cf/openai/gpt-oss-120b",
    "code": "@cf/moonshotai/kimi-k2.7-code",
    "reasoning": "@cf/qwen/qwen3-30b-a3b-fp8",
    "budget": "@cf/mistralai/mistral-small-3.1-24b-instruct",
}

MODEL_CATALOG: list[dict[str, Any]] = [
    {
        "id": "@cf/openai/gpt-oss-120b",
        "label": "GPT-OSS 120B",
        "tier": "quality",
        "use_case": "Default general chat, Persian, translation",
    },
    {
        "id": "@cf/meta/llama-3.3-70b-instruct-fp8-fast",
        "label": "Llama 3.3 70B Fast",
        "tier": "fast",
        "use_case": "Low latency responses",
    },
    {
        "id": "@cf/moonshotai/kimi-k2.7-code",
        "label": "Kimi K2.7 Code",
        "tier": "code",
        "use_case": "Code generation and editing",
    },
    {
        "id": "@cf/qwen/qwen3-30b-a3b-fp8",
        "label": "Qwen3 30B",
        "tier": "reasoning",
        "use_case": "Reasoning and analysis",
    },
    {
        "id": "@cf/qwen/qwq-32b",
        "label": "QwQ 32B",
        "tier": "reasoning",
        "use_case": "Deep reasoning",
    },
    {
        "id": "@cf/mistralai/mistral-small-3.1-24b-instruct",
        "label": "Mistral Small 24B",
        "tier": "budget",
        "use_case": "Cost-efficient tasks",
    },
    {
        "id": "@cf/nvidia/nemotron-3-120b-a12b",
        "label": "Nemotron 3 120B",
        "tier": "tools",
        "use_case": "Function calling",
    },
    {
        "id": "@cf/meta/llama-4-scout-17b-16e-instruct",
        "label": "Llama 4 Scout 17B",
        "tier": "general",
        "use_case": "General purpose",
    },
    {
        "id": "@cf/deepseek-ai/deepseek-r1-distill-qwen-32b",
        "label": "DeepSeek R1 32B",
        "tier": "reasoning",
        "use_case": "Reasoning distill",
    },
    {
        "id": "@cf/openai/gpt-oss-20b",
        "label": "GPT-OSS 20B",
        "tier": "general",
        "use_case": "Smaller general model",
    },
]

KNOWN_MODEL_IDS = {entry["id"] for entry in MODEL_CATALOG} | set(MODEL_ALIASES.values())


def resolve_model_id(value: str) -> str:
    """Resolve alias (quality, fast, …) or full model id."""
    text = (value or "").strip()
    if not text:
        return DEFAULT_MODEL
    alias = MODEL_ALIASES.get(text.lower())
    if alias:
        return alias
    if text.startswith("@cf/") or "/" in text:
        return text
    return text


def model_label(model_id: str) -> str:
    for entry in MODEL_CATALOG:
        if entry["id"] == model_id:
            return str(entry["label"])
    return model_id


def list_models_text() -> str:
    lines = ["Available models:"]
    for entry in MODEL_CATALOG:
        default_mark = " (default)" if entry["id"] == DEFAULT_MODEL else ""
        lines.append(
            f"• `{entry['id']}` — {entry['label']}{default_mark}\n  {entry['use_case']}"
        )
    lines.append("")
    lines.append("Aliases: " + ", ".join(f"`{k}`" for k in sorted(MODEL_ALIASES)))
    return "\n".join(lines)
