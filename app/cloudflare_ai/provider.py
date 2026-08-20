"""Cloudflare Workers AI provider with automatic account rotation."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from app.cloudflare_ai.models import resolve_model_id
from app.cloudflare_ai.store import DAILY_NEURON_LIMIT, CloudflareAIStore

logger = logging.getLogger(__name__)

BASE_URL = "https://api.cloudflare.com/client/v4/accounts"

# Agent loops multiply this per tool round, so keep it well under a CI step budget.
DEFAULT_TIMEOUT = 60.0

_JSON_MODE_ERROR_MARKERS = (
    "json mode",
    "json_schema",
    "response_format",
    "schema",
)


class CloudflareAIError(RuntimeError):
    """Base error for Cloudflare AI provider failures."""


class NoAccountsError(CloudflareAIError):
    """No usable account is configured in the store."""


class QuotaExhaustedError(CloudflareAIError):
    """Every usable account hit its daily neuron limit."""


class JsonModeUnsupportedError(CloudflareAIError):
    """The model or gateway refused the requested ``response_format``."""


@dataclass
class ChatResult:
    content: str
    model: str
    account_name: str
    neurons: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    raw: dict[str, Any] | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    finish_reason: str = ""


class CloudflareAIProvider:
    """OpenAI-compatible chat completions with round-robin account failover."""

    def __init__(
        self,
        store: CloudflareAIStore | None = None,
        *,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        timeout: float | None = None,
    ) -> None:
        self.store = store or CloudflareAIStore()
        cfg = self.store.config()
        self.model = resolve_model_id(model or self.store.default_model())
        self.max_tokens = int(max_tokens if max_tokens is not None else cfg.get("max_tokens") or 4096)
        self.temperature = float(
            temperature if temperature is not None else cfg.get("temperature") or 0.7
        )
        self.timeout = float(
            timeout if timeout is not None else cfg.get("timeout") or DEFAULT_TIMEOUT
        )
        self._current_idx = 0

    def _ordered_accounts(self) -> list[dict[str, Any]]:
        return self.store.usable_accounts()

    def _endpoint(self, account: dict[str, Any]) -> str:
        return f"{BASE_URL}/{account['account_id']}/ai/v1/chat/completions"

    def _headers(self, account: dict[str, Any]) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {account['api_token']}",
            "Content-Type": "application/json",
            "User-Agent": "telegram-auto-cloudflare-ai/1.0",
        }

    @staticmethod
    def _should_rotate(status_code: int, body: dict[str, Any] | None) -> bool:
        if status_code == 429:
            return True
        if status_code == 400 and body:
            errors = body.get("errors") or []
            if errors and isinstance(errors[0], dict):
                msg = str(errors[0].get("message") or "").lower()
                if "neurons" in msg or "limit" in msg or "quota" in msg:
                    return True
        if body and body.get("success") is False:
            return True
        return False

    @staticmethod
    def _extract_content(result: dict[str, Any]) -> str:
        """Extract assistant text from OpenAI-compatible or reasoning-model payloads."""
        choices = result.get("choices") or []
        if not choices or not isinstance(choices[0], dict):
            return ""
        message = choices[0].get("message") or {}
        if not isinstance(message, dict):
            return ""
        for key in ("content", "reasoning_content", "reasoning"):
            value = message.get(key)
            if value is None:
                continue
            text = str(value).strip()
            if text and text.lower() != "none":
                return text
        return ""

    @staticmethod
    def _extract_tool_calls(result: dict[str, Any]) -> list[dict[str, Any]]:
        choices = result.get("choices") or []
        if not choices or not isinstance(choices[0], dict):
            return []
        message = choices[0].get("message") or {}
        if not isinstance(message, dict):
            return []
        calls = message.get("tool_calls")
        return [call for call in calls if isinstance(call, dict)] if isinstance(calls, list) else []

    @staticmethod
    def _extract_finish_reason(result: dict[str, Any]) -> str:
        choices = result.get("choices") or []
        if not choices or not isinstance(choices[0], dict):
            return ""
        return str(choices[0].get("finish_reason") or "")

    @classmethod
    def _is_json_mode_error(cls, body: dict[str, Any] | None, raw: str) -> bool:
        text = (cls._extract_error(body) if body else raw or "").lower()
        return any(marker in text for marker in _JSON_MODE_ERROR_MARKERS)

    @staticmethod
    def _extract_error(body: dict[str, Any] | None) -> str:
        if not body:
            return "unknown error"
        errors = body.get("errors") or []
        if errors and isinstance(errors[0], dict):
            return str(errors[0].get("message") or body)
        return str(body)

    def _post_json(self, url: str, headers: dict[str, str], payload: dict[str, Any]) -> tuple[int, dict[str, Any] | None, str]:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST", headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                parsed = json.loads(raw) if raw else {}
                return resp.status, parsed if isinstance(parsed, dict) else None, raw
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                parsed = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                parsed = None
            return exc.code, parsed if isinstance(parsed, dict) else None, raw
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            return 0, None, str(exc)

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> ChatResult:
        """Send a chat completion, rotating accounts on quota errors.

        ``response_format`` takes a bare JSON Schema envelope
        (``{"type": "json_schema", "json_schema": {...}}``); when the gateway
        rejects it, :class:`JsonModeUnsupportedError` is raised without burning
        the account so the caller can retry with plain prompting.
        """
        model_id = resolve_model_id(model or self.model)
        payload: dict[str, Any] = {
            "model": model_id,
            "messages": messages,
            "max_tokens": int(max_tokens if max_tokens is not None else self.max_tokens),
            "temperature": float(temperature if temperature is not None else self.temperature),
        }
        if tools:
            payload["tools"] = tools
            if tool_choice is not None:
                payload["tool_choice"] = tool_choice
        if response_format is not None:
            payload["response_format"] = response_format

        accounts = self._ordered_accounts()
        if not accounts:
            raise NoAccountsError(
                "No usable Cloudflare AI accounts. Add accounts via `/cfai add` or seed script."
            )

        if self._current_idx >= len(accounts):
            self._current_idx = 0

        attempts = 0
        last_error = "unknown error"
        quota_hits = 0
        idx = self._current_idx

        while attempts < len(accounts):
            account = accounts[idx]
            name = str(account.get("name") or "")
            status, body, raw = self._post_json(
                self._endpoint(account),
                self._headers(account),
                payload,
            )

            if status == 200 and body:
                if "result" in body and "success" in body:
                    if not body.get("success"):
                        last_error = self._extract_error(body)
                        if response_format is not None and self._is_json_mode_error(body, raw):
                            raise JsonModeUnsupportedError(last_error)
                        self.store.mark_used(name, error=last_error, exhausted=True)
                        idx = (idx + 1) % len(accounts)
                        attempts += 1
                        continue
                    result = body.get("result") or {}
                else:
                    result = body

                usage = result.get("usage") or {}
                neurons = float(usage.get("neurons") or 0)
                content = self._extract_content(result)

                self.store.mark_used(name, neurons=neurons)
                self._current_idx = idx
                return ChatResult(
                    content=content,
                    model=model_id,
                    account_name=name,
                    neurons=neurons,
                    prompt_tokens=int(usage.get("prompt_tokens") or 0),
                    completion_tokens=int(usage.get("completion_tokens") or 0),
                    raw=result if isinstance(result, dict) else None,
                    tool_calls=self._extract_tool_calls(result),
                    finish_reason=self._extract_finish_reason(result),
                )

            if response_format is not None and self._is_json_mode_error(body, raw):
                raise JsonModeUnsupportedError(
                    self._extract_error(body) if body else raw or f"HTTP {status}"
                )

            if status == 0:
                # Transport failure (timeout, DNS, reset): the account is fine,
                # so try the next one instead of aborting the whole run.
                last_error = raw or "transport error"
                logger.warning("cloudflare AI transport error on %s: %s", name, last_error)
                self.store.mark_used(name, error=last_error)
                idx = (idx + 1) % len(accounts)
                attempts += 1
                continue

            if self._should_rotate(status, body):
                last_error = self._extract_error(body) if body else raw
                quota_hits += 1
                self.store.mark_used(name, error=last_error, exhausted=True)
                idx = (idx + 1) % len(accounts)
                attempts += 1
                continue

            last_error = self._extract_error(body) if body else raw or f"HTTP {status}"
            self.store.mark_used(name, error=last_error)
            raise CloudflareAIError(f"Cloudflare AI request failed ({status}): {last_error}")

        if quota_hits == 0:
            raise CloudflareAIError(
                f"All {len(accounts)} Cloudflare AI accounts failed to respond. "
                f"Last error: {last_error}"
            )

        raise QuotaExhaustedError(
            "All Cloudflare AI accounts have reached their daily limit "
            f"(~{DAILY_NEURON_LIMIT:,} neurons/day each). "
            "Limits reset at midnight UTC. Last error: "
            f"{last_error}"
        )

    def test_account(
        self,
        account_name: str,
        *,
        model: str | None = None,
        prompt: str = "Reply with exactly: OK",
    ) -> ChatResult:
        account = self.store.get_account(account_name)
        if not account:
            raise ValueError(f"account not found: {account_name}")

        model_id = resolve_model_id(model or self.model)
        payload = {
            "model": model_id,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 32,
            "temperature": 0.0,
        }
        status, body, raw = self._post_json(
            self._endpoint(account),
            self._headers(account),
            payload,
        )

        if status != 200 or not body:
            error = self._extract_error(body) if body else raw or f"HTTP {status}"
            self.store.mark_used(account_name, error=error, exhausted=self._should_rotate(status, body))
            raise RuntimeError(f"Test failed ({status}): {error}")

        if "result" in body and "success" in body:
            if not body.get("success"):
                error = self._extract_error(body)
                self.store.mark_used(account_name, error=error, exhausted=True)
                raise RuntimeError(f"Test failed: {error}")
            result = body.get("result") or {}
        else:
            result = body

        usage = result.get("usage") or {}
        neurons = float(usage.get("neurons") or 0)
        content = self._extract_content(result)

        self.store.mark_used(account_name, neurons=neurons)
        return ChatResult(
            content=content,
            model=model_id,
            account_name=account_name,
            neurons=neurons,
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
            raw=result if isinstance(result, dict) else None,
        )

    def status(self) -> dict[str, Any]:
        accounts = self._ordered_accounts()
        current = accounts[self._current_idx]["name"] if accounts else None
        summary = self.store.status_summary()
        summary["current_account"] = current
        summary["model"] = self.model
        return summary
