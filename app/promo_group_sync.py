from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from app.linkdir_bridge import export_promo_ready
from modules.channel_forward.refs import display_ref, normalize_ref
from modules.promo_spread.routes import default_route, migrate_routes


ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
ACCOUNTS_DIR = CONFIG_DIR / "accounts"


def _is_truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _stable_bucket_index(text: str, *, n: int) -> int:
    # Deterministic sharding: same group → same promo account(s) across runs.
    h = hashlib.sha1(text.encode("utf-8")).hexdigest()
    return int(h, 16) % max(1, n)


def _collect_promo_account_ids() -> list[str]:
    accounts_json = CONFIG_DIR / "accounts.json"
    if not accounts_json.exists():
        return []
    data = json.loads(accounts_json.read_text(encoding="utf-8"))
    rows = data.get("accounts") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return []

    out: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        account_id = str(row.get("id") or "").strip()
        if not account_id:
            continue
        profile_path = ACCOUNTS_DIR / f"{account_id}.json"
        if not profile_path.exists():
            continue
        try:
            profile = json.loads(profile_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        modules = profile.get("modules") if isinstance(profile, dict) else None
        promo_spread = modules.get("promo_spread") if isinstance(modules, dict) else None
        if isinstance(promo_spread, dict):
            out.append(account_id)
    return out


def _ensure_promo_spread(profile: dict[str, Any]) -> dict[str, Any]:
    modules = profile.setdefault("modules", {})
    if not isinstance(modules, dict):
        raise ValueError("profile.modules must be an object")
    promo_spread = modules.get("promo_spread")
    if not isinstance(promo_spread, dict):
        promo_spread = {}
        modules["promo_spread"] = promo_spread
    return promo_spread


def _route_source_key(source: str) -> str:
    # promo_spread routes store a stable "display_ref" form as `source`.
    return display_ref(source)


def _group_norm_key(group_ref: str) -> str:
    return str(normalize_ref(group_ref))


def _add_groups_to_route(route: dict[str, Any], new_groups: list[str]) -> None:
    groups = route.setdefault("groups", [])
    if not isinstance(groups, list):
        route["groups"] = groups = []

    existing_norm = {_group_norm_key(g) for g in groups if isinstance(g, str)}
    for g in new_groups:
        if not isinstance(g, str):
            continue
        nk = _group_norm_key(g)
        if nk in existing_norm:
            continue
        groups.append(g)
        existing_norm.add(nk)


def sync() -> int:
    dry_run = _is_truthy(os.environ.get("DRY_RUN", "false"))
    rank_min = float(os.environ.get("PROMO_RANK_MIN", "0.5"))
    export_limit = int(os.environ.get("PROMO_EXPORT_LIMIT", "500"))
    threshold_members_can_send = _is_truthy(os.environ.get("PROMO_NEED_POSTABLE", "true"))
    fallback_source = os.environ.get("PROMO_SOURCE_FALLBACK", "").strip()

    promo_account_ids = _collect_promo_account_ids()
    if not promo_account_ids:
        raise SystemExit("No promo accounts found (config/accounts/*.json with promo_spread module).")

    payload = export_promo_ready(limit=export_limit)
    if not payload or not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        raise SystemExit("export_promo_ready() returned no payload (bridge missing/unavailable?).")

    items = payload["items"]

    # 1) Filter candidates.
    candidates: list[dict[str, Any]] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        if not it.get("ref"):
            continue
        if bool(it.get("members_can_send")) is not True and threshold_members_can_send:
            # Only take postable groups when configured.
            continue
        try:
            rank_score = float(it.get("rank_score") or 0)
        except ValueError:
            rank_score = 0.0
        if rank_score < rank_min:
            continue
        candidates.append(it)

    # Sort so higher-rank groups get applied first (helps when routes are already crowded).
    candidates.sort(key=lambda x: float(x.get("rank_score") or 0), reverse=True)

    # 2) Shard groups across promo accounts (one group only to one promo).
    #    Also create route buckets per (promo_account, source_channel).
    assignments: dict[str, dict[str, list[str]]] = {
        acc: {} for acc in promo_account_ids
    }  # acc_id -> source_key -> [group_ref...]
    seen_in_account_source: dict[tuple[str, str, str], bool] = {}

    for it in candidates:
        group_ref = str(it["ref"])
        source_ref = str(it.get("parent_seed") or it.get("source") or fallback_source or "").strip()
        if not source_ref:
            continue
        source_key = _route_source_key(source_ref)

        group_norm = _group_norm_key(group_ref)
        shard_idx = _stable_bucket_index(group_norm, n=len(promo_account_ids))
        assigned_acc = promo_account_ids[shard_idx]

        # Dedupe within (promo, source).
        key = (assigned_acc, source_key, group_norm)
        if seen_in_account_source.get(key):
            continue
        seen_in_account_source[key] = True
        assignments.setdefault(assigned_acc, {}).setdefault(source_key, []).append(group_ref)

    # 3) Patch config/accounts/<promo_id>.json routes lists.
    changed_any = False
    for acc_id in promo_account_ids:
        profile_path = ACCOUNTS_DIR / f"{acc_id}.json"
        if not profile_path.exists():
            continue

        profile_text = profile_path.read_text(encoding="utf-8")
        profile = json.loads(profile_text)
        if not isinstance(profile, dict):
            continue

        promo_spread = _ensure_promo_spread(profile)
        route_defs = migrate_routes(promo_spread)

        # Index by route source.
        routes_by_source: dict[str, dict[str, Any]] = {}
        for r in route_defs:
            if not isinstance(r, dict):
                continue
            src = r.get("source")
            if not src:
                continue
            routes_by_source[_route_source_key(str(src))] = r

        new_for_acc = assignments.get(acc_id) or {}
        if not new_for_acc:
            continue

        mode_default = str(promo_spread.get("mode") or promo_spread.get("default_mode") or "forward").lower()
        if mode_default not in {"forward", "copy"}:
            mode_default = "forward"

        for source_key, group_refs in new_for_acc.items():
            if source_key not in routes_by_source:
                # Create a route for this source channel.
                routes_by_source[source_key] = default_route(
                    source_key,
                    groups=[],
                    enabled=True,
                    paused=bool(promo_spread.get("paused", False)),
                    mode=mode_default,
                )
            _add_groups_to_route(routes_by_source[source_key], group_refs)

        # Write back.
        # Keep deterministic route order: existing order first, then new sources.
        # Since dict ordering is stable (Py3.7+), we just rebuild list from routes_by_source
        # with a stable sort by source string.
        updated_routes = sorted(
            routes_by_source.values(),
            key=lambda r: str(r.get("source") or ""),
        )
        promo_spread["routes"] = updated_routes

        new_text = json.dumps(profile, ensure_ascii=False, indent=2) + "\n"
        if new_text != profile_text:
            changed_any = True
            if not dry_run:
                profile_path.write_text(new_text, encoding="utf-8")

    if not changed_any:
        print("promo_group_sync: no config changes.")
        return 0

    print(f"promo_group_sync: updated promo routes (dry_run={dry_run}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(sync())

