from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from app.linkdir_bridge import export_promo_ready
from app.promo_exclusivity import (
    claim_group,
    find_overlaps,
    is_active_promo_profile,
    reconcile_exclusive_profiles,
    rightful_owner,
    stable_bucket_index,
)
from app.promo_exclusivity import _iter_route_groups as _iter_route_groups_safe
from modules.channel_forward.refs import display_ref, normalize_ref
from modules.promo_spread.routes import default_route, migrate_routes


ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
ACCOUNTS_DIR = CONFIG_DIR / "accounts"


def _is_truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


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
        if isinstance(promo_spread, dict) and is_active_promo_profile(account_id, profile):
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

    Critical invariant: each group is owned by at most one promo account.
    New catalog groups are claimed via stable hash; existing overlaps are
    reconciled afterwards (remove from losers / move to rightful owner).
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

    # Sorted so hash ownership is stable regardless of accounts.json order.
    eligible_accounts = sorted(
        aid for aid, srcs in sources_by_account.items() if srcs
    )
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

    profile_by_id = {aid: profile for aid, profile in profiles}

    # Ensure every registered/fallback source exists even before groups arrive.
    for acc_id in eligible_accounts:
        profile = profile_by_id[acc_id]
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

        for source_key in sources_by_account[acc_id]:
            if source_key not in routes_by_source:
                routes_by_source[source_key] = default_route(
                    source_key,
                    groups=[],
                    enabled=True,
                    paused=bool(promo_spread.get("paused", False)),
                    mode=mode_default,
                )
        promo_spread["routes"] = sorted(
            routes_by_source.values(),
            key=lambda r: str(r.get("source") or ""),
        )
        promo_spread["auto_join"] = True

    claimed = 0
    skipped_owned = 0
    # Index existing exclusive ownership so a new promo account never steals
    # groups already held by another account.
    already_owned: dict[str, str] = {}
    for acc_id, profile in profiles:
        for _src, _raw, nk in _iter_route_groups_safe(profile):
            already_owned.setdefault(nk, acc_id)

    for it in candidates:
        group_ref = str(it["ref"])
        try:
            group_norm = _group_norm_key(group_ref)
        except Exception:
            continue
        existing_owner = already_owned.get(group_norm)
        if existing_owner and existing_owner in eligible_accounts:
            # Sticky: leave the group on its current promo account.
            skipped_owned += 1
            continue
        owner = rightful_owner(group_ref, eligible_accounts)
        sources = sources_by_account.get(owner) or []
        if not sources:
            continue
        source_key = sources[
            stable_bucket_index(f"{group_norm}:{owner}", n=len(sources))
        ]
        result = claim_group(
            profiles,
            owner_id=owner,
            group_ref=group_ref,
            source=source_key,
        )
        if result.get("added") or result.get("removed"):
            claimed += 1
            already_owned[group_norm] = owner

    reconcile = reconcile_exclusive_profiles(
        profiles, account_ids=eligible_accounts
    )

    changed_any = bool(claimed or reconcile.get("changed"))
    for acc_id in eligible_accounts:
        profile = profile_by_id[acc_id]
        profile_path = ACCOUNTS_DIR / f"{acc_id}.json"
        profile_text = profile_path.read_text(encoding="utf-8")
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
        f"account(s) claimed={claimed} skipped_owned={skipped_owned} "
        f"overlaps_fixed="
        f"{reconcile.get('overlaps_before', 0)}→{reconcile.get('overlaps_after', 0)} "
        f"(dry_run={dry_run})."
    )
    return 0


def repair_local_overlaps(*, dry_run: bool = False) -> dict[str, Any]:
    """Fix existing exclusive-group violations in config/accounts/promo*.json."""
    profiles = _collect_promo_profiles()
    if not profiles:
        return {"changed": False, "reason": "no_profiles"}
    eligible = sorted(aid for aid, _ in profiles)
    overlaps_before = find_overlaps(profiles)
    result = reconcile_exclusive_profiles(profiles, account_ids=eligible)
    changed_files: list[str] = []
    profile_by_id = {aid: p for aid, p in profiles}
    for aid in eligible:
        profile = profile_by_id[aid]
        path = ACCOUNTS_DIR / f"{aid}.json"
        new_text = json.dumps(profile, ensure_ascii=False, indent=2) + "\n"
        old_text = path.read_text(encoding="utf-8") if path.exists() else ""
        if new_text != old_text:
            changed_files.append(aid)
            if not dry_run:
                path.write_text(new_text, encoding="utf-8")
    return {
        **result,
        "changed_files": changed_files,
        "overlap_groups_before": sorted(overlaps_before.keys()),
        "dry_run": dry_run,
    }


if __name__ == "__main__":
    raise SystemExit(sync())
