"""Safe profile module toggles + promo routes for owned accounts."""
from __future__ import annotations

from typing import Any

from app.Services.AccountScaffoldService import AccountScaffoldService, validate_account_id
from app.Services.AccountService import AccountConflictError, AccountService
from app.Services.GitHubService import GitHubError
from app.Support.ForwardRoutes import (
    DedupConfig,
    DeliveryConfig,
    MediaFilterConfig,
    ScheduleConfig,
    TextFilterConfig,
    apply_dedup_command,
    apply_delivery_command,
    apply_filter_command,
    apply_media_command,
    apply_schedule_command,
    default_route_dict,
    find_route as find_forward_route,
    format_routes_lines,
    migrate_routes as migrate_forward_routes,
    remove_route as remove_forward_route,
    route_destinations,
    upsert_route as upsert_forward_route,
)
from app.Support.PromoRoutes import (
    default_route,
    display_ref,
    find_route,
    migrate_routes,
    normalize_group_list,
    remove_route,
    upsert_route,
)

ALLOWED: dict[str, dict[str, str]] = {
    "group_inspect": {
        "dry_run": "bool",
        "paused": "bool",
        "daily_join_budget": "budget",
    },
    "link_harvest": {
        "paused": "bool",
        "catch_up_limit": "catchup",
        "directories": "dirs",
    },
    "linkdir_collect": {
        "paused": "bool",
        "enabled": "bool",
        "steps": "steps",
    },
    "promo_spread": {
        "dry_run": "bool",
        "paused": "bool",
        "mode": "mode",
        "routes": "routes",
        "auto_join": "bool",
        "safety": "safety",
        "source": "nullable",
        "groups": "dirs",
    },
    "channel_forward": {
        "dry_run": "bool",
        "paused": "bool",
        "auto_join": "bool",
        "enabled": "bool",
        "routes": "routes",
    },
}

ROLE_MODULE = {
    "inspector": "group_inspect",
    "collector": "link_harvest",
    "linkdir": "linkdir_collect",
    "promo": "promo_spread",
    "forward": "channel_forward",
}


class ProfileConfigService:
    def __init__(self, db, scaffold: AccountScaffoldService) -> None:
        self.db = db
        self.scaffold = scaffold
        self.accounts = AccountService(db)

    async def _owned_module(
        self, user_id: int, account_id: str, module: str
    ) -> None:
        row = await self.accounts.require_owned(user_id, account_id)
        role = str(row.get("role") or "").lower()
        expected = ROLE_MODULE.get(role)
        if role != "full" and expected and expected != module:
            raise AccountConflictError("wrong_role_for_module", account_id=account_id)

    def _validate_patch(self, module: str, patch: dict[str, Any]) -> dict[str, Any]:
        allowed = ALLOWED.get(module)
        if not allowed:
            raise GitHubError(f"module not allowed: {module}")
        out: dict[str, Any] = {}
        for key, value in patch.items():
            kind = allowed.get(key)
            if not kind:
                raise GitHubError(f"key not allowed: {module}.{key}")
            if kind == "bool":
                out[key] = bool(value)
            elif kind == "budget":
                out[key] = max(1, min(12, int(value)))
            elif kind == "catchup":
                out[key] = max(0, min(200, int(value)))
            elif kind == "mode":
                mode = str(value).strip().lower()
                if mode not in {"forward", "copy"}:
                    raise GitHubError("mode must be forward|copy")
                out[key] = mode
            elif kind == "steps":
                text = str(value or "").strip()
                parts = [p.strip() for p in text.split(",") if p.strip()]
                allowed_steps = {"search", "snowball", "rerank"}
                if not parts or any(p not in allowed_steps for p in parts):
                    raise GitHubError("steps must be search,snowball,rerank")
                out[key] = ",".join(parts)
            elif kind == "dirs":
                if value is None:
                    out[key] = []
                elif not isinstance(value, list):
                    raise GitHubError("directories must be a list")
                else:
                    dirs = [str(x).strip() for x in value if str(x).strip()]
                    if len(dirs) > 40:
                        raise GitHubError("too many entries")
                    out[key] = dirs
            elif kind == "routes":
                if not isinstance(value, list):
                    raise GitHubError("routes must be a list")
                out[key] = value
            elif kind == "safety":
                if not isinstance(value, dict):
                    raise GitHubError("safety must be an object")
                out[key] = value
            elif kind == "nullable":
                out[key] = value
            else:
                raise GitHubError(f"unknown kind {kind}")
        if not out:
            raise GitHubError("empty patch")
        return out

    async def patch(
        self,
        user_id: int,
        account_id: str,
        module: str,
        patch: dict[str, Any],
    ) -> dict[str, Any]:
        aid = validate_account_id(account_id)
        if not aid:
            raise AccountConflictError("invalid_id", account_id=account_id)
        await self._owned_module(user_id, aid, module)
        clean = self._validate_patch(module, patch)
        return await self.scaffold.patch_profile_modules(aid, module, clean)

    async def module_config(
        self, user_id: int, account_id: str, module: str
    ) -> dict[str, Any]:
        await self.accounts.require_owned(user_id, account_id)
        info = await self.scaffold.get_profile(account_id)
        modules = (info.get("profile") or {}).get("modules") or {}
        cfg = modules.get(module) if isinstance(modules, dict) else {}
        return cfg if isinstance(cfg, dict) else {}

    async def describe_module(
        self, user_id: int, account_id: str, module: str
    ) -> dict[str, Any]:
        cfg = await self.module_config(user_id, account_id, module)
        if module == "promo_spread":
            routes = migrate_routes(cfg)
            return {
                "module": module,
                "enabled": cfg.get("enabled"),
                "paused": cfg.get("paused"),
                "dry_run": cfg.get("dry_run"),
                "mode": cfg.get("mode"),
                "routes": routes,
                "route_count": len(routes),
            }
        if module == "link_harvest":
            dirs = [str(x) for x in (cfg.get("directories") or []) if str(x).strip()]
            return {
                "module": module,
                "enabled": cfg.get("enabled"),
                "paused": cfg.get("paused"),
                "catch_up_limit": cfg.get("catch_up_limit"),
                "directories": dirs,
            }
        if module == "group_inspect":
            return {
                "module": module,
                "enabled": cfg.get("enabled"),
                "paused": cfg.get("paused"),
                "dry_run": cfg.get("dry_run"),
                "daily_join_budget": cfg.get("daily_join_budget"),
            }
        if module == "linkdir_collect":
            return {
                "module": module,
                "enabled": cfg.get("enabled"),
                "paused": cfg.get("paused"),
                "steps": cfg.get("steps") or "search,snowball,rerank",
            }
        if module == "channel_forward":
            routes = migrate_forward_routes(cfg)
            return {
                "module": module,
                "enabled": cfg.get("enabled"),
                "paused": cfg.get("paused"),
                "dry_run": cfg.get("dry_run"),
                "auto_join": cfg.get("auto_join"),
                "routes": routes,
                "route_count": len(routes),
                "routes_text": format_routes_lines(routes),
            }
        return {"module": module, "config": cfg}

    async def toggle_bool(
        self,
        user_id: int,
        account_id: str,
        module: str,
        key: str,
        *,
        value: bool | None = None,
    ) -> dict[str, Any]:
        cfg = await self.module_config(user_id, account_id, module)
        cur_val = bool(cfg.get(key))
        new_val = (not cur_val) if value is None else bool(value)
        return await self.patch(user_id, account_id, module, {key: new_val})

    async def set_budget(
        self, user_id: int, account_id: str, budget: int
    ) -> dict[str, Any]:
        return await self.patch(
            user_id, account_id, "group_inspect", {"daily_join_budget": budget}
        )

    async def set_catchup(
        self, user_id: int, account_id: str, n: int
    ) -> dict[str, Any]:
        return await self.patch(
            user_id, account_id, "link_harvest", {"catch_up_limit": n}
        )

    async def add_directory(
        self, user_id: int, account_id: str, ref: str
    ) -> dict[str, Any]:
        shown = display_ref(ref)
        if not shown:
            raise GitHubError("empty directory")
        cfg = await self.module_config(user_id, account_id, "link_harvest")
        dirs = [str(x) for x in (cfg.get("directories") or []) if str(x).strip()]
        if any(display_ref(d) == shown for d in dirs):
            raise GitHubError("directory_exists")
        if len(dirs) >= 5:
            raise GitHubError("directories_full")
        dirs.append(shown)
        return await self.patch(
            user_id, account_id, "link_harvest", {"directories": dirs}
        )

    async def remove_directory(
        self, user_id: int, account_id: str, ref: str
    ) -> dict[str, Any]:
        shown = display_ref(ref)
        cfg = await self.module_config(user_id, account_id, "link_harvest")
        dirs = [str(x) for x in (cfg.get("directories") or []) if str(x).strip()]
        new_dirs = [d for d in dirs if display_ref(d) != shown]
        if len(new_dirs) == len(dirs):
            raise GitHubError("directory_missing")
        return await self.patch(
            user_id, account_id, "link_harvest", {"directories": new_dirs}
        )

    async def _save_promo_routes(
        self, user_id: int, account_id: str, routes: list[dict[str, Any]]
    ) -> dict[str, Any]:
        return await self.patch(
            user_id,
            account_id,
            "promo_spread",
            {"routes": routes, "source": None, "groups": [], "auto_join": False},
        )

    async def promo_add_route(
        self,
        user_id: int,
        account_id: str,
        source: str,
        groups_csv: str,
    ) -> dict[str, Any]:
        cfg = await self.module_config(user_id, account_id, "promo_spread")
        routes = migrate_routes(cfg)
        source_ref = display_ref(source)
        groups = normalize_group_list(
            [p.strip() for p in groups_csv.replace("،", ",").split(",") if p.strip()]
        )
        if not source_ref or not groups:
            raise GitHubError("need source and groups")
        existing = find_route(routes, source_ref)
        if existing:
            merged = normalize_group_list(list(existing.get("groups") or []) + groups)
            route = default_route(
                source_ref,
                merged,
                enabled=existing.get("enabled", True),
                paused=existing.get("paused", False),
                mode=existing.get("mode") or cfg.get("mode") or "forward",
            )
        else:
            route = default_route(
                source_ref, groups, mode=cfg.get("mode") or "forward"
            )
        routes = upsert_route(routes, route)
        result = await self._save_promo_routes(user_id, account_id, routes)
        result["route"] = route
        return result

    async def promo_remove_route(
        self, user_id: int, account_id: str, source: str
    ) -> dict[str, Any]:
        cfg = await self.module_config(user_id, account_id, "promo_spread")
        routes = remove_route(migrate_routes(cfg), source)
        return await self._save_promo_routes(user_id, account_id, routes)

    async def promo_set_route_paused(
        self, user_id: int, account_id: str, source: str, *, paused: bool
    ) -> dict[str, Any]:
        cfg = await self.module_config(user_id, account_id, "promo_spread")
        routes = migrate_routes(cfg)
        route = find_route(routes, source)
        if not route:
            raise GitHubError("route_missing")
        route["paused"] = bool(paused)
        routes = upsert_route(routes, route)
        return await self._save_promo_routes(user_id, account_id, routes)

    async def promo_group_add(
        self, user_id: int, account_id: str, source: str, group: str
    ) -> dict[str, Any]:
        cfg = await self.module_config(user_id, account_id, "promo_spread")
        routes = migrate_routes(cfg)
        route = find_route(routes, source)
        if not route:
            route = default_route(source, [], mode=cfg.get("mode") or "forward")
        groups = normalize_group_list(list(route.get("groups") or []))
        g = display_ref(group)
        if g not in groups:
            groups.append(g)
        route["groups"] = groups
        routes = upsert_route(routes, route)
        result = await self._save_promo_routes(user_id, account_id, routes)
        result["route"] = route
        return result

    async def to_promo(
        self,
        user_id: int,
        promo_account_id: str,
        source: str,
        group_ref: str,
    ) -> dict[str, Any]:
        """Add an already-approved group ref onto a promo route (profile only)."""
        return await self.promo_group_add(
            user_id, promo_account_id, source, group_ref
        )

    async def _forward_routes(
        self, user_id: int, account_id: str
    ) -> list[dict[str, Any]]:
        cfg = await self.module_config(user_id, account_id, "channel_forward")
        return migrate_forward_routes(cfg)

    async def _save_forward_routes(
        self, user_id: int, account_id: str, routes: list[dict[str, Any]]
    ) -> dict[str, Any]:
        return await self.patch(
            user_id,
            account_id,
            "channel_forward",
            {"routes": routes, "enabled": True},
        )

    async def forward_add_route(
        self,
        user_id: int,
        account_id: str,
        source: str,
        dest: str,
    ) -> dict[str, Any]:
        routes = await self._forward_routes(user_id, account_id)
        source_ref = display_ref(source)
        dest_ref = display_ref(dest)
        if not source_ref or not dest_ref:
            raise GitHubError("need source and destination")
        if find_forward_route(routes, source_ref):
            raise GitHubError("route_exists")
        route = default_route_dict(
            source_ref, dest_ref, owner_id=int(user_id), visibility="private"
        )
        routes.append(route)
        result = await self._save_forward_routes(user_id, account_id, routes)
        result["route"] = route
        return result

    async def forward_remove_route(
        self, user_id: int, account_id: str, source: str
    ) -> dict[str, Any]:
        routes = remove_forward_route(
            await self._forward_routes(user_id, account_id), source
        )
        return await self._save_forward_routes(user_id, account_id, routes)

    async def forward_set_destination(
        self, user_id: int, account_id: str, source: str, dest: str
    ) -> dict[str, Any]:
        routes = await self._forward_routes(user_id, account_id)
        route = find_forward_route(routes, source)
        if not route:
            raise GitHubError("route_missing")
        dest_ref = display_ref(dest)
        route["destination"] = dest_ref
        route["destinations"] = [dest_ref]
        routes = upsert_forward_route(routes, route)
        result = await self._save_forward_routes(user_id, account_id, routes)
        result["route"] = route
        return result

    async def forward_set_route_paused(
        self, user_id: int, account_id: str, source: str, *, paused: bool
    ) -> dict[str, Any]:
        routes = await self._forward_routes(user_id, account_id)
        route = find_forward_route(routes, source)
        if not route:
            raise GitHubError("route_missing")
        route["paused"] = bool(paused)
        return await self._save_forward_routes(
            user_id, account_id, upsert_forward_route(routes, route)
        )

    async def forward_set_route_mode(
        self, user_id: int, account_id: str, source: str, mode: str
    ) -> dict[str, Any]:
        mode = str(mode or "").strip().lower()
        if mode not in {"forward", "copy"}:
            raise GitHubError("mode must be forward|copy")
        routes = await self._forward_routes(user_id, account_id)
        route = find_forward_route(routes, source)
        if not route:
            raise GitHubError("route_missing")
        route["forward_mode"] = mode
        return await self._save_forward_routes(
            user_id, account_id, upsert_forward_route(routes, route)
        )

    async def forward_set_visibility(
        self, user_id: int, account_id: str, source: str, visibility: str
    ) -> dict[str, Any]:
        from app.Support.ForwardRoutes import normalize_visibility

        routes = await self._forward_routes(user_id, account_id)
        route = find_forward_route(routes, source)
        if not route:
            raise GitHubError("route_missing")
        route["visibility"] = normalize_visibility(visibility)
        if route.get("owner_id") is None:
            route["owner_id"] = int(user_id)
        return await self._save_forward_routes(
            user_id, account_id, upsert_forward_route(routes, route)
        )

    async def forward_claim_route(
        self, user_id: int, account_id: str, source: str
    ) -> dict[str, Any]:
        from app.Support.ForwardRoutes import normalize_visibility

        routes = await self._forward_routes(user_id, account_id)
        route = find_forward_route(routes, source)
        if not route:
            raise GitHubError("route_missing")
        owner = route.get("owner_id")
        if owner not in (None, "") and int(owner) != int(user_id):
            raise GitHubError("route_owned_by_other")
        route["owner_id"] = int(user_id)
        route["visibility"] = normalize_visibility(route.get("visibility"))
        return await self._save_forward_routes(
            user_id, account_id, upsert_forward_route(routes, route)
        )

    async def forward_dest_add(
        self, user_id: int, account_id: str, source: str, dest: str
    ) -> dict[str, Any]:
        routes = await self._forward_routes(user_id, account_id)
        route = find_forward_route(routes, source)
        if not route:
            raise GitHubError("route_missing")
        dests = route_destinations(route)
        dest_ref = display_ref(dest)
        if dest_ref not in [display_ref(d) for d in dests]:
            dests.append(dest_ref)
        route["destinations"] = dests
        route["destination"] = dests[0]
        return await self._save_forward_routes(
            user_id, account_id, upsert_forward_route(routes, route)
        )

    async def forward_dest_remove(
        self, user_id: int, account_id: str, source: str, dest: str
    ) -> dict[str, Any]:
        routes = await self._forward_routes(user_id, account_id)
        route = find_forward_route(routes, source)
        if not route:
            raise GitHubError("route_missing")
        target = display_ref(dest)
        dests = [
            d
            for d in route_destinations(route)
            if display_ref(d) != target
        ]
        if not dests:
            raise GitHubError("need_at_least_one_dest")
        route["destinations"] = dests
        route["destination"] = dests[0]
        return await self._save_forward_routes(
            user_id, account_id, upsert_forward_route(routes, route)
        )

    async def forward_import_routes(
        self,
        user_id: int,
        account_id: str,
        sources_csv: str,
        dest: str,
    ) -> dict[str, Any]:
        routes = await self._forward_routes(user_id, account_id)
        dest_ref = display_ref(dest)
        sources = [
            s.strip()
            for s in sources_csv.replace("،", ",").split(",")
            if s.strip()
        ]
        if not sources or not dest_ref:
            raise GitHubError("need sources and dest")
        added = 0
        for src in sources:
            if find_forward_route(routes, src):
                continue
            routes.append(
                default_route_dict(
                    src, dest_ref, owner_id=int(user_id), visibility="private"
                )
            )
            added += 1
        result = await self._save_forward_routes(user_id, account_id, routes)
        result["added"] = added
        return result

    async def forward_filter_command(
        self, user_id: int, account_id: str, source: str, cmd: str
    ) -> dict[str, Any]:
        routes = await self._forward_routes(user_id, account_id)
        route = find_forward_route(routes, source)
        if not route:
            raise GitHubError("route_missing")
        parts = [p for p in (cmd or "").strip().split() if p]
        filt = TextFilterConfig.from_dict(route.get("filter"))
        if not parts:
            result = await self.module_config(user_id, account_id, "channel_forward")
            return {
                "summary": filt.summary_lines(),
                "module": "channel_forward",
                "merged": result,
            }
        filt = apply_filter_command(filt, parts)
        route["filter"] = filt.to_dict()
        if filt.enabled and route.get("forward_mode") == "forward":
            route["forward_mode"] = "copy"
        saved = await self._save_forward_routes(
            user_id, account_id, upsert_forward_route(routes, route)
        )
        saved["summary"] = filt.summary_lines()
        return saved

    async def forward_schedule_command(
        self, user_id: int, account_id: str, source: str, cmd: str
    ) -> dict[str, Any]:
        routes = await self._forward_routes(user_id, account_id)
        route = find_forward_route(routes, source)
        if not route:
            raise GitHubError("route_missing")
        parts = [p for p in (cmd or "").strip().split() if p]
        sched = ScheduleConfig.from_dict(route.get("schedule"))
        if not parts:
            return {"summary": sched.summary_lines(), "module": "channel_forward"}
        sched = apply_schedule_command(sched, parts)
        route["schedule"] = sched.to_dict()
        saved = await self._save_forward_routes(
            user_id, account_id, upsert_forward_route(routes, route)
        )
        saved["summary"] = sched.summary_lines()
        return saved

    async def forward_media_command(
        self, user_id: int, account_id: str, source: str, cmd: str
    ) -> dict[str, Any]:
        routes = await self._forward_routes(user_id, account_id)
        route = find_forward_route(routes, source)
        if not route:
            raise GitHubError("route_missing")
        parts = [p for p in (cmd or "").strip().split() if p]
        mf = MediaFilterConfig.from_dict(route.get("media_filter"))
        if not parts:
            return {"summary": mf.summary_lines(), "module": "channel_forward"}
        mf = apply_media_command(mf, parts)
        route["media_filter"] = mf.to_dict()
        saved = await self._save_forward_routes(
            user_id, account_id, upsert_forward_route(routes, route)
        )
        saved["summary"] = mf.summary_lines()
        return saved

    async def forward_dedup_command(
        self, user_id: int, account_id: str, source: str, cmd: str
    ) -> dict[str, Any]:
        routes = await self._forward_routes(user_id, account_id)
        route = find_forward_route(routes, source)
        if not route:
            raise GitHubError("route_missing")
        parts = [p for p in (cmd or "").strip().split() if p]
        dd = DedupConfig.from_dict(route.get("dedup"))
        if not parts:
            return {
                "summary": [
                    f"enabled={'ON' if dd.enabled else 'OFF'}",
                    f"window={dd.window_hours}h",
                ],
                "module": "channel_forward",
            }
        dd = apply_dedup_command(dd, parts)
        route["dedup"] = dd.to_dict()
        saved = await self._save_forward_routes(
            user_id, account_id, upsert_forward_route(routes, route)
        )
        saved["summary"] = [
            f"enabled={'ON' if dd.enabled else 'OFF'}",
            f"window={dd.window_hours}h",
        ]
        return saved

    async def forward_delivery_command(
        self, user_id: int, account_id: str, source: str, cmd: str
    ) -> dict[str, Any]:
        routes = await self._forward_routes(user_id, account_id)
        route = find_forward_route(routes, source)
        if not route:
            raise GitHubError("route_missing")
        parts = [p for p in (cmd or "").strip().split() if p]
        dlv = DeliveryConfig.from_dict(route.get("delivery"))
        if not parts:
            return {"summary": dlv.summary_lines(), "module": "channel_forward"}
        dlv = apply_delivery_command(dlv, parts)
        route["delivery"] = dlv.to_dict()
        saved = await self._save_forward_routes(
            user_id, account_id, upsert_forward_route(routes, route)
        )
        saved["summary"] = dlv.summary_lines()
        return saved

    async def forward_toggle_filter_bool(
        self,
        user_id: int,
        account_id: str,
        source: str,
        key: str,
        *,
        value: bool | None = None,
    ) -> dict[str, Any]:
        bool_keys = {
            "links": "remove_links",
            "mentions": "remove_mentions",
            "hashtags": "remove_hashtags",
            "ids": "remove_ids",
        }
        field_name = bool_keys.get(key)
        if not field_name:
            raise GitHubError("bad filter key")
        routes = await self._forward_routes(user_id, account_id)
        route = find_forward_route(routes, source)
        if not route:
            raise GitHubError("route_missing")
        filt = TextFilterConfig.from_dict(route.get("filter"))
        cur = bool(getattr(filt, field_name))
        new_val = (not cur) if value is None else bool(value)
        setattr(filt, field_name, new_val)
        if new_val:
            filt.enabled = True
        route["filter"] = filt.to_dict()
        if filt.enabled and route.get("forward_mode") == "forward":
            route["forward_mode"] = "copy"
        return await self._save_forward_routes(
            user_id, account_id, upsert_forward_route(routes, route)
        )
