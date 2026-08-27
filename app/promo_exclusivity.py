"""Enforce exclusive promo destination groups across accounts.

Invariant: a destination group may appear on at most one promo/full account.
Owner for contested / catalog-synced groups is a stable hash over sorted
account ids so ownership does not flip with JSON insertion order.
"""
from __future__ import annotations

import hashlib
from typing import Any, Callable

from modules.channel_forward.refs import display_ref, normalize_ref
from modules.promo_spread.routes import migrate_routes


def is_active_promo_profile(account_id: str, profile: dict[str, Any]) -> bool:
    """True for real promo workers (ignore disabled stubs / unrelated roles)."""
    modules = profile.get("modules")
    promo = modules.get("promo_spread") if isinstance(modules, dict) else None
    if not isinstance(promo, dict):
        return False
    if not bool(promo.get("enabled", True)):
        return False
    aid = str(account_id or "").strip().lower()
    if aid.startswith("promo"):
        return True
    # Non-promo-* ids only count when they already carry ad routes.
    for route in migrate_routes(promo):
        if display_ref(route.get("source") or ""):
            return True
    return False


def stable_bucket_index(text: str, *, n: int) -> int:
    h = hashlib.sha1(text.encode("utf-8")).hexdigest()
    return int(h, 16) % max(1, n)


def group_norm_key(group_ref: str) -> str:
    return str(normalize_ref(group_ref))


def rightful_owner(group_ref: str, account_ids: list[str]) -> str:
    """Deterministic exclusive owner among sorted account ids."""
    ids = sorted({str(a).strip() for a in account_ids if str(a).strip()})
    if not ids:
        raise ValueError("account_ids required")
    return ids[stable_bucket_index(group_norm_key(group_ref), n=len(ids))]


def _ensure_promo_spread(profile: dict[str, Any]) -> dict[str, Any]:
    modules = profile.setdefault("modules", {})
    if not isinstance(modules, dict):
        raise ValueError("profile.modules must be an object")
    promo = modules.get("promo_spread")
    if not isinstance(promo, dict):
        promo = {}
        modules["promo_spread"] = promo
    return promo


def _iter_route_groups(
    profile: dict[str, Any],
) -> list[tuple[str, str, str]]:
    """Return (source_key, group_raw, group_norm) for enabled-or-any routes."""
    promo = _ensure_promo_spread(profile)
    out: list[tuple[str, str, str]] = []
    for route in migrate_routes(promo):
        if not isinstance(route, dict):
            continue
        src = display_ref(route.get("source") or "")
        if not src:
            continue
        for raw in list(route.get("groups") or []):
            if not isinstance(raw, str) or not raw.strip():
                continue
            try:
                nk = group_norm_key(raw)
            except Exception:
                continue
            out.append((src, raw, nk))
    return out


def find_overlaps(
    profiles: list[tuple[str, dict[str, Any]]],
) -> dict[str, list[str]]:
    """group_norm -> [account_id, ...] for groups on more than one account."""
    owners: dict[str, list[str]] = {}
    for aid, profile in profiles:
        seen: set[str] = set()
        for _src, _raw, nk in _iter_route_groups(profile):
            if nk in seen:
                continue
            seen.add(nk)
            owners.setdefault(nk, []).append(aid)
    return {k: v for k, v in owners.items() if len(v) > 1}


def strip_group_from_profile(profile: dict[str, Any], group_norm: str) -> bool:
    promo = _ensure_promo_spread(profile)
    routes = migrate_routes(promo)
    changed = False
    for route in routes:
        if not isinstance(route, dict):
            continue
        groups = list(route.get("groups") or [])
        kept: list[str] = []
        for g in groups:
            if not isinstance(g, str):
                continue
            try:
                if group_norm_key(g) == group_norm:
                    changed = True
                    continue
            except Exception:
                pass
            kept.append(g)
        route["groups"] = kept
    if changed:
        promo["routes"] = routes
    return changed


def ensure_group_on_profile(
    profile: dict[str, Any],
    *,
    group_ref: str,
    preferred_source: str | None = None,
) -> bool:
    """Attach group to preferred/first enabled source. Return True if mutated."""
    promo = _ensure_promo_spread(profile)
    routes = migrate_routes(promo)
    if not routes:
        return False
    nk = group_norm_key(group_ref)
    preferred_key = display_ref(preferred_source) if preferred_source else ""

    target = None
    if preferred_key:
        for route in routes:
            if display_ref(route.get("source") or "") == preferred_key:
                target = route
                break
    if target is None:
        for route in routes:
            if route.get("enabled", True):
                target = route
                break
    if target is None:
        target = routes[0]

    groups = list(target.get("groups") or [])
    existing = set()
    for g in groups:
        if isinstance(g, str):
            try:
                existing.add(group_norm_key(g))
            except Exception:
                continue
    if nk in existing:
        return False
    groups.append(group_ref)
    target["groups"] = groups
    # Keep route object identity inside routes list.
    by_src: dict[str, dict[str, Any]] = {}
    for route in routes:
        src = display_ref(route.get("source") or "")
        if src:
            by_src[src] = route
    src_key = display_ref(target.get("source") or "")
    if src_key:
        by_src[src_key] = target
    promo["routes"] = sorted(by_src.values(), key=lambda r: str(r.get("source") or ""))
    return True


def reconcile_exclusive_profiles(
    profiles: list[tuple[str, dict[str, Any]]],
    *,
    account_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Mutate profiles so each group_norm is owned by at most one account.

    Contested groups move to ``rightful_owner`` (stable hash over sorted ids
    that have at least one ad source). Uncontested groups stay put.
    """
    profile_by_id = {aid: profile for aid, profile in profiles}

    def _has_source(aid: str) -> bool:
        profile = profile_by_id.get(aid)
        if not profile:
            return False
        promo = _ensure_promo_spread(profile)
        return bool(_enabled_source_keys(promo))

    ids = sorted(
        {
            str(a).strip()
            for a in (account_ids or [aid for aid, _ in profiles])
            if str(a).strip() and _has_source(str(a).strip())
        }
    )
    if len(ids) < 2:
        # Still strip duplicates within a single eligible account set edge-case.
        if len(ids) == 1:
            pass
        else:
            return {"changed": False, "moved": 0, "removed": 0, "overlaps_before": 0}

    # group_norm -> list of placements
    placements: dict[str, list[dict[str, str]]] = {}
    for aid, profile in profiles:
        for src, raw, nk in _iter_route_groups(profile):
            placements.setdefault(nk, []).append(
                {"account_id": aid, "source": src, "ref": raw}
            )

    overlaps_before = sum(
        1 for rows in placements.values() if len({r["account_id"] for r in rows}) > 1
    )
    moved = 0
    removed = 0
    changed = False

    for nk, rows in list(placements.items()):
        owners = sorted({r["account_id"] for r in rows})
        if len(owners) <= 1:
            continue
        # Prefer hash owner among accounts that can actually host routes.
        candidates = [a for a in ids if a]
        if not candidates:
            continue
        winner = rightful_owner(nk, candidates)
        if winner not in profile_by_id or not _has_source(winner):
            # Fall back to an existing owner that has a source.
            sourced_owners = [a for a in owners if _has_source(a)]
            winner = sourced_owners[0] if sourced_owners else owners[0]

        winner_rows = [r for r in rows if r["account_id"] == winner]
        if winner_rows:
            keep_ref = winner_rows[0]["ref"]
            keep_source = winner_rows[0]["source"]
        else:
            keep_ref = rows[0]["ref"]
            keep_source = rows[0]["source"]
            if ensure_group_on_profile(
                profile_by_id[winner],
                group_ref=keep_ref,
                preferred_source=keep_source,
            ):
                moved += 1
                changed = True

        for aid, profile in profiles:
            if aid == winner:
                continue
            if strip_group_from_profile(profile, nk):
                removed += 1
                changed = True

    return {
        "changed": changed,
        "moved": moved,
        "removed": removed,
        "overlaps_before": overlaps_before,
        "overlaps_after": len(find_overlaps(profiles)),
    }


def _enabled_source_keys(promo_spread: dict[str, Any]) -> list[str]:
    sources: list[str] = []
    for route in migrate_routes(promo_spread):
        if not isinstance(route, dict):
            continue
        if not route.get("enabled", True):
            continue
        src = display_ref(route.get("source") or "")
        if src and src not in sources:
            sources.append(src)
    return sources


def claim_group(
    profiles: list[tuple[str, dict[str, Any]]],
    *,
    owner_id: str,
    group_ref: str,
    source: str | None = None,
) -> dict[str, Any]:
    """Give group exclusively to owner_id; strip from every other profile."""
    nk = group_norm_key(group_ref)
    removed = 0
    for aid, profile in profiles:
        if aid == owner_id:
            continue
        if strip_group_from_profile(profile, nk):
            removed += 1
    added = False
    for aid, profile in profiles:
        if aid != owner_id:
            continue
        added = ensure_group_on_profile(
            profile, group_ref=group_ref, preferred_source=source
        )
        break
    return {"removed": removed, "added": added, "owner": owner_id, "group": group_ref}


def foreign_group_norms_for_account(
    account_id: str,
    profiles: list[tuple[str, dict[str, Any]]],
) -> set[str]:
    """Groups this account must NOT send to (owned by someone else after reconcile rules).

    Uses overlap-aware rule: if a group appears only here, keep it; if contested
    or present on another account, only the rightful hash owner may keep it.
    """
    sourced = []
    for aid, profile in profiles:
        promo = profile.get("modules", {}).get("promo_spread") if isinstance(profile.get("modules"), dict) else None
        if not isinstance(promo, dict):
            continue
        if _enabled_source_keys(promo):
            sourced.append(aid)
    ids = sorted(set(sourced))
    if not ids or account_id not in ids:
        return set()

    placements: dict[str, set[str]] = {}
    for aid, profile in profiles:
        for _src, _raw, nk in _iter_route_groups(profile):
            placements.setdefault(nk, set()).add(aid)

    foreign: set[str] = set()
    for nk, owners in placements.items():
        if account_id not in owners:
            if rightful_owner(nk, ids) != account_id and owners:
                foreign.add(nk)
            continue
        if len(owners) == 1:
            continue
        if rightful_owner(nk, ids) != account_id:
            foreign.add(nk)
    return foreign


def load_sibling_promo_profiles(
    *,
    accounts_dir,
    accounts_json,
    read_text: Callable[[Any], str] | None = None,
) -> list[tuple[str, dict[str, Any]]]:
    """Load promo_spread-capable profiles from disk (for runtime / CLI)."""
    import json
    from pathlib import Path

    accounts_dir = Path(accounts_dir)
    accounts_json = Path(accounts_json)
    reader = read_text or (lambda p: Path(p).read_text(encoding="utf-8"))
    if not accounts_json.exists():
        return []
    try:
        data = json.loads(reader(accounts_json))
    except Exception:
        return []
    rows = data.get("accounts") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return []

    out: list[tuple[str, dict[str, Any]]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        aid = str(row.get("id") or "").strip()
        if not aid:
            continue
        path = accounts_dir / f"{aid}.json"
        if not path.exists():
            continue
        try:
            profile = json.loads(reader(path))
        except Exception:
            continue
        if not isinstance(profile, dict):
            continue
        modules = profile.get("modules")
        promo = modules.get("promo_spread") if isinstance(modules, dict) else None
        if isinstance(promo, dict) and is_active_promo_profile(aid, profile):
            out.append((aid, profile))
    return out
