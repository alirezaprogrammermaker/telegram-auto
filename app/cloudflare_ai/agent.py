"""Generic tool-calling agent runtime on top of :class:`CloudflareAIProvider`.

The runtime is deliberately feature-agnostic so any module (linkdir query
generation, auto-reply, digests, …) can register tools and get a bounded
multi-turn loop with JSON-schema output for free.

Contract: :meth:`Agent.run` never raises. Failures are reported as
``AgentResult(ok=False, reason=<code>)`` so pipeline callers can degrade to
their non-AI behaviour with a single branch.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from app.cloudflare_ai.provider import (
    ChatResult,
    CloudflareAIProvider,
    JsonModeUnsupportedError,
    NoAccountsError,
    QuotaExhaustedError,
)

logger = logging.getLogger(__name__)

REASON_OK = "ok"
REASON_NO_ACCOUNTS = "no_accounts"
REASON_QUOTA_EXHAUSTED = "quota_exhausted"
REASON_PROVIDER_ERROR = "provider_error"
REASON_EMPTY_RESPONSE = "empty_response"
REASON_BAD_JSON = "bad_json"

_MAX_TOOL_RESULT_CHARS = 4000


@dataclass
class AgentTool:
    """A callable the model may invoke. ``parameters`` is a bare JSON Schema."""

    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[[dict[str, Any]], Any]

    def spec(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass
class ToolInvocation:
    name: str
    arguments: dict[str, Any]
    ok: bool
    result: str = ""
    error: str = ""
    salvaged: bool = False


@dataclass
class AgentResult:
    ok: bool
    reason: str = REASON_OK
    content: str = ""
    data: Any = None
    error: str = ""
    model: str = ""
    account_name: str = ""
    neurons: float = 0.0
    rounds: int = 0
    used_json_mode: bool = False
    invocations: list[ToolInvocation] = field(default_factory=list)

    def diagnostics(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "reason": self.reason,
            "model": self.model,
            "account": self.account_name,
            "neurons": round(self.neurons, 3),
            "rounds": self.rounds,
            "json_mode": self.used_json_mode,
            "tools_called": [
                {"name": inv.name, "ok": inv.ok, "salvaged": inv.salvaged}
                for inv in self.invocations
            ],
        }


def parse_json_object(text: str) -> Any:
    """Best-effort JSON extraction from model output (fences, prose wrappers)."""
    raw = (text or "").strip()
    if not raw:
        return None
    if raw.startswith("```"):
        body = raw.split("```")
        if len(body) >= 2:
            candidate = body[1]
            if candidate.lstrip().lower().startswith("json"):
                candidate = candidate.lstrip()[4:]
            raw = candidate.strip()
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        pass
    for opener, closer in (("{", "}"), ("[", "]")):
        start = raw.find(opener)
        end = raw.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(raw[start : end + 1])
            except (json.JSONDecodeError, ValueError):
                continue
    return None


def _coerce_arguments(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        parsed = parse_json_object(value)
        if isinstance(parsed, dict):
            return parsed
    return {}


def salvage_tool_calls(content: str, known_names: set[str]) -> list[dict[str, Any]]:
    """Recover tool calls gpt-oss emits as plain JSON text with empty tool_calls.

    See cloudflare/ai#574: the model answers with ``finish_reason="stop"`` and
    the forced call serialised into ``message.content``. Only names we actually
    offered are accepted — nothing is fabricated.
    """
    parsed = parse_json_object(content)
    candidates = parsed if isinstance(parsed, list) else [parsed]
    out: list[dict[str, Any]] = []
    for item in candidates:
        if not isinstance(item, dict):
            continue
        block = item.get("function") if isinstance(item.get("function"), dict) else item
        name = str(block.get("name") or "").strip()
        if name not in known_names:
            continue
        for key in ("arguments", "parameters", "args", "input"):
            if key in block:
                args = _coerce_arguments(block.get(key))
                break
        else:
            args = {}
        out.append({"name": name, "arguments": args})
    return out


class Agent:
    """Bounded tool-calling loop with optional JSON-schema final answer."""

    def __init__(
        self,
        provider: CloudflareAIProvider,
        *,
        system_prompt: str,
        tools: list[AgentTool] | None = None,
        max_tool_rounds: int = 4,
        response_schema: dict[str, Any] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        model: str | None = None,
    ) -> None:
        self.provider = provider
        self.system_prompt = system_prompt
        self.tools = {tool.name: tool for tool in (tools or [])}
        self.max_tool_rounds = max(0, int(max_tool_rounds))
        self.response_schema = response_schema
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.model = model

    def _chat(self, messages: list[dict[str, Any]], **kwargs: Any) -> ChatResult:
        return self.provider.chat(
            messages,
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            **kwargs,
        )

    def _run_tool(self, name: str, arguments: dict[str, Any], *, salvaged: bool) -> ToolInvocation:
        tool = self.tools.get(name)
        if tool is None:
            return ToolInvocation(
                name=name,
                arguments=arguments,
                ok=False,
                error="unknown tool",
                salvaged=salvaged,
            )
        try:
            output = tool.handler(arguments)
        except Exception as exc:  # noqa: BLE001 - tool errors feed back to the model
            logger.warning("agent tool %s failed: %s", name, exc)
            return ToolInvocation(
                name=name, arguments=arguments, ok=False, error=str(exc)[:200], salvaged=salvaged
            )
        if not isinstance(output, str):
            try:
                output = json.dumps(output, ensure_ascii=False)
            except (TypeError, ValueError):
                output = str(output)
        return ToolInvocation(
            name=name,
            arguments=arguments,
            ok=True,
            result=output[:_MAX_TOOL_RESULT_CHARS],
            salvaged=salvaged,
        )

    def _normalized_calls(self, result: ChatResult) -> list[tuple[dict[str, Any], bool]]:
        calls: list[tuple[dict[str, Any], bool]] = []
        for raw_call in result.tool_calls:
            fn = raw_call.get("function") if isinstance(raw_call.get("function"), dict) else raw_call
            name = str(fn.get("name") or "").strip()
            if not name:
                continue
            calls.append(
                (
                    {
                        "id": str(raw_call.get("id") or f"call_{len(calls)}"),
                        "name": name,
                        "arguments": _coerce_arguments(fn.get("arguments")),
                    },
                    False,
                )
            )
        if calls:
            return calls
        for idx, call in enumerate(salvage_tool_calls(result.content, set(self.tools))):
            calls.append(({"id": f"salvaged_{idx}", **call}, True))
        return calls

    def _finalize(
        self, messages: list[dict[str, Any]], state: dict[str, Any]
    ) -> tuple[ChatResult, bool]:
        """Ask for the final answer, preferring JSON mode, falling back to prose."""
        if self.response_schema is not None:
            try:
                result = self._chat(
                    messages,
                    response_format={
                        "type": "json_schema",
                        "json_schema": self.response_schema,
                    },
                )
                self._track(state, result)
                return result, True
            except JsonModeUnsupportedError as exc:
                logger.info("JSON mode unavailable, retrying with plain prompt: %s", exc)
                messages = messages + [
                    {
                        "role": "system",
                        "content": (
                            "Reply with a single raw JSON object matching this schema. "
                            "No prose, no markdown fences: "
                            + json.dumps(self.response_schema, ensure_ascii=False)
                        ),
                    }
                ]
        result = self._chat(messages)
        self._track(state, result)
        return result, False

    def _satisfies_schema(self, content: str) -> bool:
        """Cheap check so an already-conforming answer skips the extra round-trip."""
        if self.response_schema is None:
            return False
        parsed = parse_json_object(content)
        if not isinstance(parsed, (dict, list)):
            return False
        required = self.response_schema.get("required")
        if isinstance(required, list) and required:
            return isinstance(parsed, dict) and all(key in parsed for key in required)
        return True

    @staticmethod
    def _track(state: dict[str, Any], result: ChatResult) -> None:
        state["neurons"] = float(state.get("neurons") or 0.0) + result.neurons
        state["model"] = result.model
        state["account"] = result.account_name

    def run(self, user_prompt: str) -> AgentResult:
        """Execute the loop. Never raises; inspect ``AgentResult.ok``."""
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        tool_specs = [tool.spec() for tool in self.tools.values()]
        state: dict[str, Any] = {"neurons": 0.0, "model": "", "account": ""}
        invocations: list[ToolInvocation] = []
        rounds = 0
        direct: ChatResult | None = None

        try:
            while tool_specs and rounds < self.max_tool_rounds:
                result = self._chat(messages, tools=tool_specs)
                self._track(state, result)
                calls = self._normalized_calls(result)
                if not calls:
                    if result.content:
                        messages.append({"role": "assistant", "content": result.content})
                        direct = result
                    break

                rounds += 1
                messages.append(
                    {
                        "role": "assistant",
                        "content": result.content or "",
                        "tool_calls": [
                            {
                                "id": call["id"],
                                "type": "function",
                                "function": {
                                    "name": call["name"],
                                    "arguments": json.dumps(
                                        call["arguments"], ensure_ascii=False
                                    ),
                                },
                            }
                            for call, _ in calls
                        ],
                    }
                )
                for call, salvaged in calls:
                    invocation = self._run_tool(
                        call["name"], call["arguments"], salvaged=salvaged
                    )
                    invocations.append(invocation)
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call["id"],
                            "name": call["name"],
                            "content": invocation.result
                            if invocation.ok
                            else f"error: {invocation.error}",
                        }
                    )

            if direct is not None and (
                self.response_schema is None or self._satisfies_schema(direct.content)
            ):
                final, used_json_mode = direct, False
            else:
                final, used_json_mode = self._finalize(messages, state)
        except NoAccountsError as exc:
            return self._failure(REASON_NO_ACCOUNTS, exc, state, invocations, rounds)
        except QuotaExhaustedError as exc:
            return self._failure(REASON_QUOTA_EXHAUSTED, exc, state, invocations, rounds)
        except Exception as exc:  # noqa: BLE001 - agent must never break the pipeline
            return self._failure(REASON_PROVIDER_ERROR, exc, state, invocations, rounds)

        content = (final.content or "").strip()
        if not content:
            return self._failure(
                REASON_EMPTY_RESPONSE, "model returned no content", state, invocations, rounds
            )

        data = parse_json_object(content) if self.response_schema is not None else None
        if self.response_schema is not None and data is None:
            return self._failure(
                REASON_BAD_JSON, "model output was not valid JSON", state, invocations, rounds
            )

        return AgentResult(
            ok=True,
            content=content,
            data=data,
            model=str(state["model"]),
            account_name=str(state["account"]),
            neurons=float(state["neurons"]),
            rounds=rounds,
            used_json_mode=used_json_mode,
            invocations=invocations,
        )

    def _failure(
        self,
        reason: str,
        error: Any,
        state: dict[str, Any],
        invocations: list[ToolInvocation],
        rounds: int,
    ) -> AgentResult:
        message = str(error)[:300]
        logger.warning("agent run failed (%s): %s", reason, message)
        return AgentResult(
            ok=False,
            reason=reason,
            error=message,
            model=str(state.get("model") or ""),
            account_name=str(state.get("account") or ""),
            neurons=float(state.get("neurons") or 0.0),
            rounds=rounds,
            invocations=invocations,
        )
