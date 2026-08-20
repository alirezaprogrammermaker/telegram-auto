"""Full experimental pipeline: search → snowball → rerank → export.

Keeps a living catalog without touching production promo modules.

Usage:
  python -m experiments.linkdir_finders.pipeline once
  python -m experiments.linkdir_finders.pipeline once --steps search,rerank
  python -m experiments.linkdir_finders.pipeline once --account-id linkdir1
  python -m experiments.linkdir_finders.pipeline loop
  python -m experiments.linkdir_finders.pipeline loop --every-hours 8
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import time
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from experiments.linkdir_finders.catalog import LinkDirCatalog
from experiments.linkdir_finders.method_snowball import run_snowball
from experiments.linkdir_finders.method_telegram_search import run_search
from experiments.linkdir_finders.refresh_ranks import run_rerank
from experiments.linkdir_finders.settings import load_config
from experiments.linkdir_finders.tg import (
    connect_client,
    safe_disconnect,
    setup_logging,
    setup_stdio,
)

logger = logging.getLogger("linkdir_finders.pipeline")


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _heartbeat(
    *,
    collector_id: str | None,
    session: str | None,
    status: str,
    budgets: dict[str, Any] | None = None,
    meta: dict[str, Any] | None = None,
) -> None:
    if not collector_id:
        return
    try:
        from app.linkdir_bridge import collector_heartbeat, is_available

        if not is_available():
            return
        collector_heartbeat(
            {
                "id": collector_id,
                "session_name": session,
                "label": collector_id,
                "enabled": True,
                "status": status,
                "budgets": budgets or {},
                "last_run_at": _utc_now() if status in {"idle", "circuit"} else None,
                "meta": meta or {},
            }
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("collector heartbeat failed: %s", exc)


async def run_once(
    *,
    steps: list[str],
    session: str | None = None,
    account_id: str | None = None,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    config = cfg or load_config()
    pipe = config.get("pipeline") or {}
    cat_cfg = config.get("catalog") or {}
    collector_id = (account_id or os.environ.get("ACCOUNT_ID") or "").strip() or None
    sessions = list(config.get("sessions") or [])
    if session:
        sessions = [session]
    if not sessions:
        sessions = [config.get("session_name") or "easy_seen"]

    # Rotate: use first reachable session
    client = None
    used_session = None
    last_exc: Exception | None = None
    for sess in sessions:
        try:
            client, _ = await connect_client(
                session=sess,
                retries=int(pipe.get("connect_retries") or 8),
                retry_sleep=float(pipe.get("retry_sleep") or 15),
            )
            used_session = sess
            break
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            logger.warning("session %s unavailable: %s", sess, type(exc).__name__)
    if client is None:
        raise RuntimeError(f"no session connected: {last_exc}")

    summary: dict[str, Any] = {
        "at": _utc_now(),
        "session": used_session,
        "collector_id": collector_id,
        "account_id": collector_id,
        "steps": steps,
        "results": {},
        "ok": True,
        "errors": [],
    }
    _heartbeat(
        collector_id=collector_id,
        session=used_session,
        status="running",
        meta={"steps": steps},
    )

    try:
        if "search" in steps:
            try:
                summary["results"]["search"] = await run_search(
                    session=used_session,
                    cfg=config,
                    client=client,
                    own_client=False,
                    write_catalog=True,
                    collector_id=collector_id,
                )
            except Exception as exc:  # noqa: BLE001
                summary["ok"] = False
                summary["errors"].append(f"search:{type(exc).__name__}:{exc}")
                logger.exception("search step failed")

        if "snowball" in steps:
            try:
                summary["results"]["snowball"] = await run_snowball(
                    session=used_session,
                    cfg=config,
                    client=client,
                    own_client=False,
                    collector_id=collector_id,
                )
            except Exception as exc:  # noqa: BLE001
                summary["ok"] = False
                summary["errors"].append(f"snowball:{type(exc).__name__}:{exc}")
                logger.exception("snowball step failed")

        if "rerank" in steps:
            try:
                summary["results"]["rerank"] = await run_rerank(
                    session=used_session,
                    cfg=config,
                    client=client,
                    own_client=False,
                    collector_id=collector_id,
                )
            except Exception as exc:  # noqa: BLE001
                summary["ok"] = False
                summary["errors"].append(f"rerank:{type(exc).__name__}:{exc}")
                logger.exception("rerank step failed")

        # Always refresh export at end
        catalog = LinkDirCatalog(collector_id=collector_id)
        stale_n = catalog.mark_stale(
            older_than_hours=float(cat_cfg.get("stale_hours") or 72)
        )
        export_path = catalog.export_promo_ready(
            limit=int(cat_cfg.get("promo_limit") or 200)
        )
        summary["stale_marked"] = stale_n
        summary["promo_export"] = str(export_path)
        summary["catalog_counts"] = catalog.counts()
        catalog.record_pipeline_run(
            {
                "at": summary["at"],
                "session": used_session,
                "collector_id": collector_id,
                "account_id": collector_id,
                "steps": steps,
                "ok": summary["ok"],
                "errors": summary["errors"],
                "catalog_counts": summary["catalog_counts"],
            }
        )
        status = "idle" if summary["ok"] else "idle"
        _heartbeat(
            collector_id=collector_id,
            session=used_session,
            status=status,
            meta={"ok": summary["ok"], "errors": summary["errors"][:5]},
        )
        return summary
    except Exception:
        _heartbeat(
            collector_id=collector_id,
            session=used_session,
            status="circuit",
            meta={"error": "pipeline_crash"},
        )
        raise
    finally:
        await safe_disconnect(client)


async def run_loop(
    *,
    every_hours: float,
    steps: list[str],
    session: str | None = None,
    account_id: str | None = None,
) -> None:
    cfg = load_config()
    while True:
        started = time.time()
        logger.info("=== pipeline cycle start steps=%s ===", steps)
        try:
            summary = await run_once(
                steps=steps, session=session, account_id=account_id, cfg=cfg
            )
            print(json.dumps(summary, ensure_ascii=False, indent=2))
        except Exception as exc:  # noqa: BLE001
            logger.exception("pipeline cycle failed: %s", exc)
        elapsed = time.time() - started
        sleep_s = max(60.0, every_hours * 3600.0 - elapsed)
        logger.info("sleeping %.1f hours until next cycle", sleep_s / 3600.0)
        await asyncio.sleep(sleep_s)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Linkdir catalog pipeline (experiment)")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add_common(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--session", default=None)
        sp.add_argument(
            "--account-id",
            default=None,
            help="Collector/account id for D1 heartbeat + per-account safety",
        )
        sp.add_argument(
            "--steps",
            default=None,
            help="Comma list: search,snowball,rerank (default from config)",
        )
        sp.add_argument("--verbose", action="store_true")

    p_once = sub.add_parser("once", help="Run one full/partial cycle")
    add_common(p_once)

    p_loop = sub.add_parser("loop", help="Run forever on an interval")
    add_common(p_loop)
    p_loop.add_argument(
        "--every-hours",
        type=float,
        default=None,
        help="Hours between cycles (default config.pipeline.loop_hours)",
    )
    return p


def overlay_account_profile(cfg: dict[str, Any], account_id: str | None) -> dict[str, Any]:
    """Apply per-account query_set / role from config/accounts/<id>.json."""
    aid = (account_id or "").strip()
    if not aid:
        return cfg
    try:
        from app.accounts import load_account_profile
    except Exception:
        return cfg
    profile = load_account_profile(aid)
    if not profile:
        return cfg
    mod = ((profile.get("modules") or {}).get("linkdir_collect") or {})
    query_set = str(mod.get("query_set") or "").strip().lower()
    if not query_set:
        return cfg
    out = deepcopy(cfg)
    out.setdefault("search", {})["query_set"] = query_set
    from experiments.linkdir_finders.job_queue import queries_for_set

    queries = queries_for_set(out, query_set)
    if queries:
        out["queries"] = queries
    return out


def _parse_steps(raw: str | None, cfg: dict[str, Any]) -> list[str]:
    if raw:
        steps = [s.strip() for s in raw.split(",") if s.strip()]
    else:
        steps = list(
            (cfg.get("pipeline") or {}).get("steps") or ["search", "snowball", "rerank"]
        )
    allowed = {"search", "snowball", "rerank"}
    bad = [s for s in steps if s not in allowed]
    if bad:
        raise SystemExit(f"unknown steps: {bad} (allowed: {sorted(allowed)})")
    return steps


def main() -> None:
    setup_stdio()
    args = build_parser().parse_args()
    setup_logging(verbose=args.verbose)
    cfg = load_config()
    account_id = args.account_id or os.environ.get("ACCOUNT_ID")
    cfg = overlay_account_profile(cfg, account_id)
    steps = _parse_steps(args.steps, cfg)

    if args.cmd == "once":
        summary = asyncio.run(
            run_once(
                steps=steps,
                session=args.session,
                account_id=account_id,
                cfg=cfg,
            )
        )
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        raise SystemExit(0 if summary.get("ok") else 1)

    if args.cmd == "loop":
        every = args.every_hours
        if every is None:
            every = float((cfg.get("pipeline") or {}).get("loop_hours") or 12)
        asyncio.run(
            run_loop(
                every_hours=every,
                steps=steps,
                session=args.session,
                account_id=account_id,
            )
        )


if __name__ == "__main__":
    main()
