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


def _collect_promo_profiles() -> list[tuple[str, dict[str, Any]]]:
    """Return (account_id, profile) for every promo_spread-capable account."""
    accounts_json = CONFIG_DIR / "accounts.json"
    if not accounts_json.exists():
        return []
    data = json.loads(accounts_json.read_text(encoding="utf-8"))
    rows = data.get("accounts") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return []

    out: list[tuple[str, dict[str, Any]]] = []
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
        if not isinstance(profile, dict):
            continue
        modules = profile.get("modules")
        promo_spread = modules.get("promo_spread") if isinstance(modules, dict) else None
        if isinstance(promo_spread, dict):
            out.append((account_id, profile))
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


def _enabled_sources(promo_spread: dict[str, Any]) -> list[str]:
    """Ad channels the operator already registered (empty groups are OK)."""
    sources: list[str] = []
    for route in migrate_routes(promo_spread):
        if not isinstance(route, dict):
            continue
        if not route.get("enabled", True):
            continue
        src = route.get("source")
        if not src:
            continue
        key = _route_source_key(str(src))
        if key and key not in sources:
            sources.append(key)
    return sources


def sync() -> int:
    """Attach promo_ready linkdir groups onto registered ad-channel routes.

    Destination groups come from the smart catalog. Source channels must already
    exist on promo profiles (registered via the admin bot). Discovery parent_seed
    is intentionally ignored — that was the old seed-channel model.
    """
    dry_run = _is_truthy(os.environ.get("DRY_RUN", "false"))
    rank_min = float(os.environ.get("PROMO_RANK_MIN", "0.5"))
    export_limit = int(os.environ.get("PROMO_EXPORT_LIMIT", "500"))
    threshold_members_can_send = _is_truthy(os.environ.get("PROMO_NEED_POSTABLE", "true"))
    fallback_source = os.environ.get("PROMO_SOURCE_FALLBACK", "").strip()
    fallback_key = _route_source_key(fallback_source) if fallback_source else ""

    profiles = _collect_promo_profiles()
    if not profiles:
        raise SystemExit(
            "No promo accounts found (config/accounts/*.json with promo_spread module)."
        )

    # account_id -> enabled ad sources (may be empty until operator registers a channel)
    sources_by_account: dict[str, list[str]] = {}
    for acc_id, profile in profiles:
        promo_spread = _ensure_promo_spread(profile)
        sources = _enabled_sources(promo_spread)
        if not sources and fallback_key:
            sources = [fallback_key]
        sources_by_account[acc_id] = sources

    eligible_accounts = [aid for aid, srcs in sources_by_account.items() if srcs]
    if not eligible_accounts:
        raise SystemExit(
            "No ad channels registered on promo accounts. "
            "Add one in the bot (تبلیغ → مسیرها → ➕ کانال تبلیغ) first."
        )

    payload = export_promo_ready(limit=export_limit)
    if not payload or not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        raise SystemExit(
            "export_promo_ready() returned no payload (bridge missing/unavailable?)."
        )

    candidates: list[dict[str, Any]] = []
    for it in payload["items"]:
        if not isinstance(it, dict):
            continue
        if not it.get("ref"):
            continue
        if bool(it.get("members_can_send")) is not True and threshold_members_can_send:
            continue
        try:
            rank_score = float(it.get("rank_score") or 0)
        except ValueError:
            rank_score = 0.0
        if rank_score < rank_min:
            continue
        candidates.append(it)

    candidates.sort(key=lambda x: float(x.get("rank_score") or 0), reverse=True)

    # acc_id -> source_key -> [group_ref...]
    assignments: dict[str, dict[str, list[str]]] = {acc: {} for acc in eligible_accounts}
    seen: set[tuple[str, str, str]] = set()

    for it in candidates:
        group_ref = str(it["ref"])
        group_norm = _group_norm_key(group_ref)
        shard_idx = _stable_bucket_index(group_norm, n=len(eligible_accounts))
        assigned_acc = eligible_accounts[shard_idx]
        sources = sources_by_account[assigned_acc]
        source_key = sources[
            _stable_bucket_index(f"{group_norm}:{assigned_acc}", n=len(sources))
        ]
        key = (assigned_acc, source_key, group_norm)
        if key in seen:
            continue
        seen.add(key)
        assignments[assigned_acc].setdefault(source_key, []).append(group_ref)

    changed_any = False
    profile_by_id = {aid: profile for aid, profile in profiles}

    for acc_id in eligible_accounts:
        profile = profile_by_id[acc_id]
        profile_path = ACCOUNTS_DIR / f"{acc_id}.json"
        profile_text = profile_path.read_text(encoding="utf-8")

        promo_spread = _ensure_promo_spread(profile)
        route_defs = migrate_routes(promo_spread)
        routes_by_source: dict[str, dict[str, Any]] = {}
        for r in route_defs:
            if not isinstance(r, dict):
                continue
            src = r.get("source")
            if not src:
                continue
            routes_by_source[_route_source_key(str(src))] = r

        mode_default = str(
            promo_spread.get("mode") or promo_spread.get("default_mode") or "forward"
        ).lower()
        if mode_default not in {"forward", "copy"}:
            mode_default = "forward"

        # Ensure every registered/fallback source exists even before groups arrive.
        for source_key in sources_by_account[acc_id]:
            if source_key not in routes_by_source:
                routes_by_source[source_key] = default_route(
                    source_key,
                    groups=[],
                    enabled=True,
                    paused=bool(promo_spread.get("paused", False)),
                    mode=mode_default,
                )

        for source_key, group_refs in (assignments.get(acc_id) or {}).items():
            if source_key not in routes_by_source:
                routes_by_source[source_key] = default_route(
                    source_key,
                    groups=[],
                    enabled=True,
                    paused=bool(promo_spread.get("paused", False)),
                    mode=mode_default,
                )
            _add_groups_to_route(routes_by_source[source_key], group_refs)

        updated_routes = sorted(
            routes_by_source.values(),
            key=lambda r: str(r.get("source") or ""),
        )
        promo_spread["routes"] = updated_routes
        promo_spread["auto_join"] = True

        new_text = json.dumps(profile, ensure_ascii=False, indent=2) + "\n"
        if new_text != profile_text:
            changed_any = True
            if not dry_run:
                profile_path.write_text(new_text, encoding="utf-8")

    if not changed_any:
        print("promo_group_sync: no config changes.")
        return 0

    print(
        f"promo_group_sync: updated promo routes for {len(eligible_accounts)} "
        f"account(s) (dry_run={dry_run})."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(sync())
