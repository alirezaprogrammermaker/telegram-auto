"""GitHub REST helpers for admin-bot control plane."""
from __future__ import annotations

import base64
import json
from typing import Any

from js import console
from workers import fetch


class GitHubError(Exception):
    def __init__(self, message: str, *, status: int | None = None, body: Any = None):
        super().__init__(message)
        self.status = status
        self.body = body


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

    async def _request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        raw: bool = False,
    ) -> Any:
        if not self.token:
            raise GitHubError("GITHUB_TOKEN missing")
        if not self.repo:
            raise GitHubError("GITHUB_REPO missing")

        url = f"{self.api}{path}"
        kwargs: dict[str, Any] = {
            "method": method,
            "headers": self._headers(json_body=body is not None),
        }
        if body is not None:
            kwargs["body"] = json.dumps(body, ensure_ascii=False)

        resp = await fetch(url, **kwargs)
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
        """Atomic multi-file commit via Git Data API."""
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
        for path, content in files.items():
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
        return {"sha": new_sha, "branch": self.branch, "files": list(files.keys())}

    async def dispatch_workflow(
        self, workflow_file: str, inputs: dict[str, str]
    ) -> None:
        await self._request(
            "POST",
            f"/repos/{self.repo}/actions/workflows/{workflow_file}/dispatches",
            body={"ref": self.branch, "inputs": inputs},
        )

    async def latest_workflow_run(
        self, workflow_file: str, *, event: str = "workflow_dispatch"
    ) -> dict[str, Any] | None:
        data = await self._request(
            "GET",
            f"/repos/{self.repo}/actions/workflows/{workflow_file}/runs"
            f"?event={event}&per_page=5&branch={self.branch}",
        )
        runs = data.get("workflow_runs") if isinstance(data, dict) else None
        if not isinstance(runs, list) or not runs:
            return None
        first = runs[0]
        return first if isinstance(first, dict) else None

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
