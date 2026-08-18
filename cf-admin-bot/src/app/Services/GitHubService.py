"""GitHub REST helpers for admin-bot control plane."""
from __future__ import annotations

import asyncio
import base64
import json
from typing import Any

from js import console
from workers import fetch

_RETRYABLE = {408, 429, 500, 502, 503, 504}


class GitHubError(Exception):
    def __init__(self, message: str, *, status: int | None = None, body: Any = None):
        super().__init__(message)
        self.status = status
        self.body = body

    @property
    def is_retryable(self) -> bool:
        return self.status in _RETRYABLE

    @property
    def user_message(self) -> str:
        if self.status in {502, 503, 504} or "currently available" in str(self).lower():
            return "github_unavailable"
        if self.status == 401:
            return "github_unauthorized"
        if self.status == 403:
            return "github_forbidden"
        if "already exists" in str(self).lower():
            return "exists"
        return "error"


class GitHubService:
    def __init__(self, token: str, repo: str, *, branch: str = "master") -> None:
        self.token = token.strip()
        self.repo = repo.strip().strip("/")
        self.branch = branch.strip() or "master"
        self.api = "https://api.github.com"

    def _headers(self, *, json_body: bool = True) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "telegram-admin-bot",
        }
        if json_body:
            headers["Content-Type"] = "application/json"
        return headers

    async def _request_once(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        raw: bool = False,
    ) -> Any:
        if not self.token:
            raise GitHubError("GITHUB_TOKEN missing", status=401)
        if not self.repo:
            raise GitHubError("GITHUB_REPO missing", status=400)

        url = f"{self.api}{path}"
        kwargs: dict[str, Any] = {
            "method": method,
            "headers": self._headers(json_body=body is not None),
        }
        if body is not None:
            kwargs["body"] = json.dumps(body, ensure_ascii=False)

        try:
            resp = await fetch(url, **kwargs)
        except Exception as exc:
            raise GitHubError(f"GitHub network error: {exc}", status=503) from exc

        status = int(getattr(resp, "status", 0) or 0)
        text = await resp.text()
        data: Any = text
        if not raw:
            try:
                data = json.loads(text) if text else {}
            except Exception:
                data = {"raw": text}

        if status >= 400:
            message = ""
            if isinstance(data, dict):
                message = str(data.get("message") or data.get("error") or "")
            raise GitHubError(
                message or f"GitHub HTTP {status}",
                status=status,
                body=data,
            )
        return data

    async def _request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        raw: bool = False,
        retries: int = 4,
    ) -> Any:
        last: Exception | None = None
        for attempt in range(retries):
            try:
                return await self._request_once(
                    method, path, body=body, raw=raw
                )
            except GitHubError as exc:
                last = exc
                if not exc.is_retryable or attempt >= retries - 1:
                    raise
                delay = 1.5 * (2**attempt)
                console.error(
                    f"github retry {attempt + 1}/{retries} status={exc.status} wait={delay}s"
                )
                await asyncio.sleep(delay)
            except Exception as exc:
                last = exc
                if attempt >= retries - 1:
                    raise GitHubError(str(exc), status=503) from exc
                await asyncio.sleep(1.5 * (2**attempt))
        raise GitHubError(str(last or "github failed"), status=503)

    async def get_file_text(self, path: str) -> tuple[str, str]:
        """Return (content_text, sha)."""
        data = await self._request(
            "GET",
            f"/repos/{self.repo}/contents/{path}?ref={self.branch}",
        )
        if not isinstance(data, dict) or "content" not in data:
            raise GitHubError(f"unexpected contents response for {path}")
        encoded = str(data.get("content") or "").replace("\n", "")
        text = base64.b64decode(encoded.encode("ascii")).decode("utf-8")
        return text, str(data.get("sha") or "")

    async def get_json(self, path: str) -> tuple[Any, str]:
        text, sha = await self.get_file_text(path)
        return json.loads(text), sha

    async def commit_files(self, files: dict[str, str], message: str) -> dict[str, Any]:
        """Atomic multi-file commit via Git Data API (create/update)."""
        return await self.commit_tree_changes(
            {
                path: {"content": content}
                for path, content in files.items()
            },
            message,
        )

    async def commit_tree_changes(
        self,
        changes: dict[str, dict[str, str | None]],
        message: str,
    ) -> dict[str, Any]:
        """Create/update/delete paths in one commit.

        changes[path] = {"content": "..."} to write, or {"delete": True} to remove.
        """
        ref = await self._request(
            "GET", f"/repos/{self.repo}/git/ref/heads/{self.branch}"
        )
        head_sha = str((ref.get("object") or {}).get("sha") or "")
        if not head_sha:
            raise GitHubError("could not resolve branch HEAD")

        commit = await self._request(
            "GET", f"/repos/{self.repo}/git/commits/{head_sha}"
        )
        base_tree = str((commit.get("tree") or {}).get("sha") or "")
        if not base_tree:
            raise GitHubError("could not resolve base tree")

        tree_items = []
        for path, spec in changes.items():
            if spec.get("delete"):
                tree_items.append(
                    {
                        "path": path,
                        "mode": "100644",
                        "type": "blob",
                        "sha": None,
                    }
                )
                continue
            content = str(spec.get("content") or "")
            blob = await self._request(
                "POST",
                f"/repos/{self.repo}/git/blobs",
                body={"content": content, "encoding": "utf-8"},
            )
            blob_sha = str(blob.get("sha") or "")
            if not blob_sha:
                raise GitHubError(f"blob create failed for {path}")
            tree_items.append(
                {
                    "path": path,
                    "mode": "100644",
                    "type": "blob",
                    "sha": blob_sha,
                }
            )

        tree = await self._request(
            "POST",
            f"/repos/{self.repo}/git/trees",
            body={"base_tree": base_tree, "tree": tree_items},
        )
        tree_sha = str(tree.get("sha") or "")
        if not tree_sha:
            raise GitHubError("tree create failed")

        new_commit = await self._request(
            "POST",
            f"/repos/{self.repo}/git/commits",
            body={
                "message": message,
                "tree": tree_sha,
                "parents": [head_sha],
            },
        )
        new_sha = str(new_commit.get("sha") or "")
        if not new_sha:
            raise GitHubError("commit create failed")

        await self._request(
            "PATCH",
            f"/repos/{self.repo}/git/refs/heads/{self.branch}",
            body={"sha": new_sha, "force": False},
        )
        return {
            "sha": new_sha,
            "branch": self.branch,
            "files": list(changes.keys()),
        }

    async def delete_secret(self, name: str) -> None:
        """Best-effort delete of a repository Actions secret."""
        if not name:
            return
        try:
            await self._request(
                "DELETE",
                f"/repos/{self.repo}/actions/secrets/{name}",
            )
        except GitHubError as exc:
            # 404 = already gone
            if exc.status == 404:
                return
            raise

    async def dispatch_workflow(
        self, workflow_file: str, inputs: dict[str, str]
    ) -> None:
        await self._request(
            "POST",
            f"/repos/{self.repo}/actions/workflows/{workflow_file}/dispatches",
            body={"ref": self.branch, "inputs": inputs},
        )

    ACTIVE_RUN_STATUSES = frozenset(
        {"queued", "in_progress", "pending", "waiting", "requested"}
    )

    async def list_workflow_runs(
        self,
        workflow_file: str,
        *,
        event: str | None = "workflow_dispatch",
        status: str | None = None,
        per_page: int = 10,
    ) -> list[dict[str, Any]]:
        qs = [f"per_page={max(1, min(int(per_page), 30))}", f"branch={self.branch}"]
        if event:
            qs.append(f"event={event}")
        if status:
            qs.append(f"status={status}")
        data = await self._request(
            "GET",
            f"/repos/{self.repo}/actions/workflows/{workflow_file}/runs?"
            + "&".join(qs),
        )
        runs = data.get("workflow_runs") if isinstance(data, dict) else None
        if not isinstance(runs, list):
            return []
        return [r for r in runs if isinstance(r, dict)]

    async def latest_workflow_run(
        self, workflow_file: str, *, event: str | None = "workflow_dispatch"
    ) -> dict[str, Any] | None:
        runs = await self.list_workflow_runs(workflow_file, event=event, per_page=10)
        return runs[0] if runs else None

    async def find_active_run(
        self, workflow_file: str, *, event: str | None = None
    ) -> dict[str, Any] | None:
        runs = await self.list_workflow_runs(
            workflow_file, event=event, per_page=15
        )
        for run in runs:
            if str(run.get("status") or "") in self.ACTIVE_RUN_STATUSES:
                return run
        return None

    async def cancel_run(self, run_id: int | str) -> None:
        await self._request(
            "POST", f"/repos/{self.repo}/actions/runs/{run_id}/cancel"
        )

    async def wait_for_workflow_run(
        self,
        workflow_file: str,
        *,
        not_before_epoch: float | None = None,
        attempts: int = 8,
        delay_seconds: float = 2.0,
    ) -> dict[str, Any] | None:
        """workflow_dispatch returns 204; poll until a fresh run appears."""
        import time

        cutoff = not_before_epoch if not_before_epoch is not None else (time.time() - 30)
        for attempt in range(attempts):
            run = await self.latest_workflow_run(workflow_file)
            if run and run.get("id") is not None:
                created = str(run.get("created_at") or "")
                # Accept if created recently (ISO Zulu).
                try:
                    from datetime import datetime, timezone

                    created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                    if created_dt.timestamp() >= cutoff - 5:
                        return run
                except Exception:
                    if attempt >= 2:
                        return run
            await asyncio.sleep(delay_seconds * (1.2**attempt))
        return await self.latest_workflow_run(workflow_file)

    async def get_run(self, run_id: int | str) -> dict[str, Any]:
        data = await self._request(
            "GET", f"/repos/{self.repo}/actions/runs/{run_id}"
        )
        return data if isinstance(data, dict) else {}

    def log_safe_error(self, exc: Exception) -> None:
        if isinstance(exc, GitHubError):
            console.error(f"github error status={exc.status} msg={exc}")
        else:
            console.error(f"github error: {exc}")
