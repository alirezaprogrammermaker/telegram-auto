"""Bridge API for link-directory D1 catalog."""
from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from app.Services.LinkDirCatalogService import LinkDirCatalogService
from app.Support.BridgeAuth import require_bridge_token
from config.bot import BotConfig
from workers import Response


def _json_body(data) -> dict:
    if hasattr(data, "to_py"):
        data = data.to_py()
    return data if isinstance(data, dict) else {}


class InternalLinkDirController:
    def __init__(self, env) -> None:
        self.config = BotConfig(env)
        self.svc = LinkDirCatalogService(self.config.db)

    async def handle(self, request, action: str) -> Response:
        denied = require_bridge_token(request, self.config)
        if denied is not None:
            return denied

        method = request.method.upper()
        action = (action or "").strip().strip("/")

        try:
            if action == "upsert" and method == "POST":
                return await self._upsert(request)
            if action == "items" and method == "GET":
                return await self._items(request)
            if action == "counts" and method == "GET":
                return Response.json({"ok": True, "counts": await self.svc.counts()})
            if action == "mark-stale" and method == "POST":
                return await self._mark_stale(request)
            if action == "export-promo" and method == "GET":
                return await self._export_promo(request)
            if action == "collectors/heartbeat" and method == "POST":
                return await self._heartbeat(request)
            if action == "jobs/claim" and method == "POST":
                return await self._claim(request)
            if action == "jobs/complete" and method == "POST":
                return await self._complete(request)
            if action == "jobs/enqueue" and method == "POST":
                return await self._enqueue(request)
            if action == "runs" and method == "POST":
                return await self._runs(request)
        except ValueError as exc:
            return Response.json({"ok": False, "error": str(exc)[:200]}, status=400)
        except Exception as exc:
            return Response.json(
                {"ok": False, "error": f"{type(exc).__name__}:{str(exc)[:180]}"},
                status=500,
            )

        return Response.json({"ok": False, "error": "not_found"}, status=404)

    async def _upsert(self, request) -> Response:
        data = _json_body(await request.json())
        items = data.get("items")
        if not isinstance(items, list):
            return Response.json({"ok": False, "error": "items_required"}, status=400)
        result = await self.svc.upsert_items(
            items,
            collector_id=str(data.get("collector_id") or "") or None,
            method=str(data.get("method") or "bridge"),
        )
        counts = await self.svc.counts()
        return Response.json({"ok": True, **result, "counts": counts})

    async def _items(self, request) -> Response:
        qs = parse_qs(urlparse(request.url).query)
        promo_raw = (qs.get("promo_ready") or [None])[0]
        promo_ready = None
        if promo_raw in {"1", "true", "yes"}:
            promo_ready = True
        elif promo_raw in {"0", "false", "no"}:
            promo_ready = False
        limit = int((qs.get("limit") or ["100"])[0] or 100)
        verdict = (qs.get("verdict") or [None])[0] or None
        status = (qs.get("status") or [None])[0] or None
        items = await self.svc.list_items(
            verdict=verdict,
            status=status,
            promo_ready=promo_ready,
            limit=limit,
        )
        return Response.json({"ok": True, "count": len(items), "items": items})

    async def _mark_stale(self, request) -> Response:
        data = _json_body(await request.json())
        hours = float(data.get("older_than_hours") or 72)
        result = await self.svc.mark_stale(older_than_hours=hours)
        return Response.json({"ok": True, **result, "counts": await self.svc.counts()})

    async def _export_promo(self, request) -> Response:
        qs = parse_qs(urlparse(request.url).query)
        limit = int((qs.get("limit") or ["200"])[0] or 200)
        payload = await self.svc.export_promo_ready(limit=limit)
        return Response.json({"ok": True, **payload})

    async def _heartbeat(self, request) -> Response:
        data = _json_body(await request.json())
        row = await self.svc.collector_heartbeat(data)
        return Response.json({"ok": True, "collector": row})

    async def _claim(self, request) -> Response:
        data = _json_body(await request.json())
        jobs = await self.svc.claim_jobs(
            owner=str(data.get("owner") or data.get("collector_id") or ""),
            limit=int(data.get("limit") or 5),
            lease_seconds=int(data.get("lease_seconds") or 900),
            job_type=str(data.get("job_type") or "") or None,
        )
        return Response.json({"ok": True, "jobs": jobs})

    async def _complete(self, request) -> Response:
        data = _json_body(await request.json())
        job = await self.svc.complete_job(data)
        return Response.json({"ok": True, "job": job})

    async def _enqueue(self, request) -> Response:
        data = _json_body(await request.json())
        result = await self.svc.enqueue_job(data)
        return Response.json({"ok": True, **result})

    async def _runs(self, request) -> Response:
        data = _json_body(await request.json())
        result = await self.svc.record_run(data)
        return Response.json({"ok": True, **result})
