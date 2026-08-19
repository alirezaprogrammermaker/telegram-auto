"""Keyboard layouts (structure only — labels come from lang)."""
from __future__ import annotations

from app.Support.Lang import __


def main_keyboard() -> dict:
    return {
        "keyboard": [
            [{"text": __("menu.btn_status")}, {"text": __("menu.btn_accounts")}],
            [{"text": __("menu.btn_discovery")}, {"text": __("menu.btn_promo")}],
            [{"text": __("menu.btn_forward")}, {"text": __("menu.btn_ops")}],
            [{"text": __("assign.btn_menu")}, {"text": __("menu.btn_automation")}],
            [{"text": __("menu.btn_help")}, {"text": __("menu.btn_settings")}],
        ],
        "resize_keyboard": True,
        "is_persistent": True,
    }


def guest_keyboard() -> dict:
    return {
        "keyboard": [[{"text": "/start"}, {"text": "/whoami"}]],
        "resize_keyboard": True,
    }


def accounts_menu_keyboard() -> dict:
    return {
        "keyboard": [
            [
                {"text": __("accounts.btn_list")},
                {"text": __("accounts.btn_add")},
            ],
            [
                {"text": __("accounts.btn_login")},
                {"text": __("accounts.btn_manage")},
            ],
            [
                {"text": __("accounts.btn_cancel")},
                {"text": __("accounts.btn_back")},
            ],
        ],
        "resize_keyboard": True,
    }


def accounts_pick_keyboard(account_ids: list[str]) -> dict:
    rows: list[list[dict[str, str]]] = []
    row: list[dict[str, str]] = []
    for aid in account_ids[:24]:
        row.append({"text": aid})
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append(
        [
            {"text": __("accounts.btn_cancel")},
            {"text": __("accounts.btn_back")},
        ]
    )
    return {"keyboard": rows, "resize_keyboard": True}


def manage_actions_keyboard() -> dict:
    return {
        "keyboard": [
            [
                {"text": __("accounts.btn_enable")},
                {"text": __("accounts.btn_disable")},
            ],
            [
                {"text": __("accounts.btn_rename")},
                {"text": __("accounts.btn_auto_label")},
            ],
            [
                {"text": __("accounts.btn_change_role")},
                {"text": __("accounts.btn_vacant_roles")},
            ],
            [
                {"text": __("accounts.btn_logout")},
                {"text": __("accounts.btn_delete")},
            ],
            [{"text": __("accounts.btn_manage_back")}],
            [
                {"text": __("accounts.btn_cancel")},
                {"text": __("accounts.btn_back")},
            ],
        ],
        "resize_keyboard": True,
    }


def role_pick_keyboard(roles: list[str], *, vacant_only: bool = False) -> dict:
    rows: list[list[dict[str, str]]] = []
    row: list[dict[str, str]] = []
    for role in roles:
        row.append({"text": role})
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    if vacant_only:
        rows.append([{"text": __("accounts.btn_all_roles")}])
    else:
        rows.append([{"text": __("accounts.btn_vacant_roles")}])
    rows.append(
        [
            {"text": __("accounts.btn_manage_back")},
            {"text": __("accounts.btn_cancel")},
        ]
    )
    return {"keyboard": rows, "resize_keyboard": True}


def rename_keyboard() -> dict:
    return {
        "keyboard": [
            [{"text": __("accounts.btn_auto_label")}],
            [
                {"text": __("accounts.btn_manage_back")},
                {"text": __("accounts.btn_cancel")},
            ],
        ],
        "resize_keyboard": True,
    }


def confirm_logout_keyboard() -> dict:
    return {
        "keyboard": [
            [
                {"text": __("accounts.btn_confirm_logout")},
                {"text": __("accounts.btn_cancel")},
            ]
        ],
        "resize_keyboard": True,
    }


def confirm_delete_keyboard() -> dict:
    return {
        "keyboard": [
            [
                {"text": __("accounts.btn_confirm_delete")},
                {"text": __("accounts.btn_cancel")},
            ]
        ],
        "resize_keyboard": True,
    }


def confirm_enable_keyboard(*, enabled: bool) -> dict:
    btn = (
        __("accounts.btn_confirm_enable")
        if enabled
        else __("accounts.btn_confirm_disable")
    )
    return {
        "keyboard": [[{"text": btn}, {"text": __("accounts.btn_cancel")}]],
        "resize_keyboard": True,
    }


def roles_keyboard() -> dict:
    return {
        "keyboard": [
            [
                {"text": __("accounts.role_promo")},
                {"text": __("accounts.role_forward")},
            ],
            [
                {"text": __("accounts.role_collector")},
                {"text": __("accounts.role_inspector")},
            ],
            [
                {"text": __("accounts.role_linkdir")},
                {"text": __("accounts.role_full")},
            ],
            [{"text": __("accounts.btn_cancel")}],
        ],
        "resize_keyboard": True,
    }


def confirm_keyboard() -> dict:
    return {
        "keyboard": [
            [
                {"text": __("accounts.btn_confirm")},
                {"text": __("accounts.btn_cancel")},
            ]
        ],
        "resize_keyboard": True,
    }


def otp_keyboard() -> dict:
    return {
        "keyboard": [
            [
                {"text": __("accounts.btn_check_run")},
                {"text": __("accounts.btn_need_2fa")},
            ],
            [{"text": __("accounts.btn_cancel")}],
        ],
        "resize_keyboard": True,
    }


def ops_menu_keyboard() -> dict:
    return {
        "keyboard": [
            [
                {"text": __("ops.btn_dispatch")},
                {"text": __("ops.btn_cancel_run")},
            ],
            [
                {"text": __("ops.btn_restart")},
                {"text": __("ops.btn_merge")},
            ],
            [
                {"text": __("accounts.btn_cancel")},
                {"text": __("accounts.btn_back")},
            ],
        ],
        "resize_keyboard": True,
    }


def confirm_ops_keyboard(action: str) -> dict:
    key = f"ops.btn_confirm_{action}"
    return {
        "keyboard": [
            [{"text": __(key)}, {"text": __("accounts.btn_cancel")}]
        ],
        "resize_keyboard": True,
    }


def status_menu_keyboard() -> dict:
    return {
        "keyboard": [
            [{"text": __("status.btn_refresh")}],
            [{"text": __("accounts.btn_back")}],
        ],
        "resize_keyboard": True,
    }


def settings_keyboard() -> dict:
    return {
        "keyboard": [
            [
                {"text": __("settings.btn_demote")},
                {"text": __("settings.btn_stats")},
            ],
            [{"text": __("settings.btn_modules")}],
            [{"text": __("accounts.btn_back")}],
        ],
        "resize_keyboard": True,
    }


def modules_action_keyboard() -> dict:
    return {
        "keyboard": [
            [
                {"text": __("settings.modules_btn_on")},
                {"text": __("settings.modules_btn_off")},
                {"text": __("settings.modules_btn_reload")},
            ],
            [{"text": __("accounts.btn_cancel")}],
        ],
        "resize_keyboard": True,
    }


def discovery_menu_keyboard() -> dict:
    """Top-level discovery menu — 5 rows max."""
    return {
        "keyboard": [
            [
                {"text": __("discovery.btn_refresh")},
                {"text": __("discovery.btn_profile_status")},
            ],
            [{"text": __("discovery.btn_sub_pool")}],
            [{"text": __("discovery.btn_sub_inspect")}],
            [{"text": __("discovery.btn_sub_linkdir")}],
            [
                {"text": __("discovery.btn_help")},
                {"text": __("accounts.btn_back")},
            ],
        ],
        "resize_keyboard": True,
    }


def discovery_pool_keyboard() -> dict:
    return {
        "keyboard": [
            [
                {"text": __("discovery.btn_pool_status")},
                {"text": __("discovery.btn_pool_list")},
            ],
            [
                {"text": __("discovery.btn_pool_list_ok")},
                {"text": __("discovery.btn_pool_list_approved")},
            ],
            [
                {"text": __("discovery.btn_pool_approve")},
                {"text": __("discovery.btn_pool_reject")},
            ],
            [{"text": __("discovery.btn_to_promo")}],
            [{"text": __("nav.btn_back")}],
        ],
        "resize_keyboard": True,
    }


def discovery_inspect_keyboard() -> dict:
    return {
        "keyboard": [
            [
                {"text": __("discovery.btn_inspect_dry")},
                {"text": __("discovery.btn_inspect_budget")},
            ],
            [
                {"text": __("discovery.btn_inspect_pause")},
                {"text": __("discovery.btn_inspect_resume")},
            ],
            [{"text": __("discovery.btn_inspect_dump")}],
            [
                {"text": __("discovery.btn_harvest_pause")},
                {"text": __("discovery.btn_harvest_resume")},
            ],
            [
                {"text": __("discovery.btn_harvest_add")},
                {"text": __("discovery.btn_harvest_remove")},
            ],
            [{"text": __("discovery.btn_harvest_catchup")}],
            [{"text": __("nav.btn_back")}],
        ],
        "resize_keyboard": True,
    }


def discovery_linkdir_keyboard() -> dict:
    return {
        "keyboard": [
            [
                {"text": __("discovery.btn_linkdir_counts")},
                {"text": __("discovery.btn_linkdir_run")},
            ],
            [
                {"text": __("discovery.btn_linkdir_pause")},
                {"text": __("discovery.btn_linkdir_resume")},
            ],
            [{"text": __("nav.btn_back")}],
        ],
        "resize_keyboard": True,
    }


def help_hub_keyboard() -> dict:
    from app.Support.HelpButtons import back_main_button, category_button

    return {
        "keyboard": [
            [{"text": category_button("general")}],
            [{"text": category_button("discovery")}],
            [{"text": category_button("promo")}],
            [{"text": category_button("forward")}],
            [{"text": back_main_button()}],
        ],
        "resize_keyboard": True,
    }


def help_categories_keyboard(buttons: list[str]) -> dict:
    from app.Support.HelpButtons import back_main_button

    rows: list[list[dict[str, str]]] = []
    row: list[dict[str, str]] = []
    for label in buttons:
        row.append({"text": label})
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([{"text": back_main_button()}])
    return {"keyboard": rows, "resize_keyboard": True}


def help_topics_keyboard(buttons: list[str], *, back_label: str) -> dict:
    rows: list[list[dict[str, str]]] = []
    row: list[dict[str, str]] = []
    for label in buttons:
        row.append({"text": label})
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([{"text": back_label}])
    return {"keyboard": rows, "resize_keyboard": True}


def queue_clear_confirm_keyboard() -> dict:
    return {
        "keyboard": [
            [{"text": __("cache.queue_clear_btn_confirm")}],
            [{"text": __("accounts.btn_cancel")}],
        ],
        "resize_keyboard": True,
    }


def forward_setup_keyboard() -> dict:
    """Simple keyboard during the quick-setup wizard."""
    return {
        "keyboard": [
            [{"text": __("forward.setup_btn_yes_filter")}, {"text": __("forward.setup_btn_no_filter")}],
            [{"text": __("accounts.btn_cancel")}],
        ],
        "resize_keyboard": True,
    }


def forward_menu_keyboard() -> dict:
    """Top-level forward menu — compact."""
    return {
        "keyboard": [
            [
                {"text": __("forward.btn_setup")},
                {"text": __("forward.btn_jobs")},
            ],
            [
                {"text": __("forward.btn_refresh")},
                {"text": __("forward.btn_profile_status")},
            ],
            [
                {"text": __("forward.btn_dry")},
                {"text": __("forward.btn_pause")},
                {"text": __("forward.btn_resume")},
            ],
            [{"text": __("forward.btn_sub_routes")}],
            [{"text": __("forward.btn_sub_filter")}],
            [{"text": __("forward.btn_sub_schedule")}],
            [{"text": __("forward.btn_sub_advanced")}],
            [
                {"text": __("forward.btn_help")},
                {"text": __("accounts.btn_back")},
            ],
        ],
        "resize_keyboard": True,
    }


def forward_routes_keyboard() -> dict:
    return {
        "keyboard": [
            [
                {"text": __("forward.btn_route_add")},
                {"text": __("forward.btn_route_remove")},
                {"text": __("forward.btn_route_set")},
            ],
            [
                {"text": __("forward.btn_route_pause")},
                {"text": __("forward.btn_route_resume")},
                {"text": __("forward.btn_route_mode")},
            ],
            [
                {"text": __("forward.btn_visibility")},
                {"text": __("forward.btn_claim")},
            ],
            [
                {"text": __("forward.btn_dest_add")},
                {"text": __("forward.btn_dest_remove")},
            ],
            [
                {"text": __("forward.btn_auto_join_on")},
                {"text": __("forward.btn_auto_join_off")},
            ],
            [{"text": __("nav.btn_back")}],
        ],
        "resize_keyboard": True,
    }


def forward_filter_keyboard() -> dict:
    return {
        "keyboard": [
            [
                {"text": __("forward.btn_filter_view")},
                {"text": __("forward.btn_filter_on")},
                {"text": __("forward.btn_filter_off")},
            ],
            [
                {"text": __("forward.btn_filter_links")},
                {"text": __("forward.btn_filter_mentions")},
                {"text": __("forward.btn_filter_hashtags")},
            ],
            [
                {"text": __("forward.btn_filter_prefix")},
                {"text": __("forward.btn_filter_suffix")},
                {"text": __("forward.btn_filter_block")},
            ],
            [{"text": __("forward.btn_filter_clear")}],
            [{"text": __("nav.btn_back")}],
        ],
        "resize_keyboard": True,
    }


def forward_schedule_keyboard() -> dict:
    return {
        "keyboard": [
            [
                {"text": __("forward.btn_schedule_view")},
                {"text": __("forward.btn_schedule_on")},
                {"text": __("forward.btn_schedule_off")},
            ],
            [
                {"text": __("forward.btn_schedule_tz")},
                {"text": __("forward.btn_schedule_days")},
                {"text": __("forward.btn_schedule_hours")},
            ],
            [{"text": __("forward.btn_schedule_clear")}],
            [{"text": __("nav.btn_back")}],
        ],
        "resize_keyboard": True,
    }


def forward_advanced_keyboard() -> dict:
    return {
        "keyboard": [
            [
                {"text": __("forward.btn_media")},
                {"text": __("forward.btn_dedup")},
                {"text": __("forward.btn_delivery")},
            ],
            [{"text": __("forward.btn_import")}],
            [
                {"text": __("forward.btn_queue_status")},
                {"text": __("forward.btn_queue_clear")},
            ],
            [{"text": __("nav.btn_back")}],
        ],
        "resize_keyboard": True,
    }


def promo_menu_keyboard() -> dict:
    """Top-level promo menu — compact."""
    return {
        "keyboard": [
            [
                {"text": __("promo.btn_refresh")},
                {"text": __("promo.btn_profile_status")},
            ],
            [
                {"text": __("promo.btn_dry")},
                {"text": __("promo.btn_pause")},
                {"text": __("promo.btn_resume")},
            ],
            [{"text": __("promo.btn_sub_routes")}],
            [{"text": __("promo.btn_sub_safety")}],
            [
                {"text": __("promo.btn_queue_status")},
                {"text": __("promo.btn_queue_clear")},
            ],
            [
                {"text": __("promo.btn_help")},
                {"text": __("accounts.btn_back")},
            ],
        ],
        "resize_keyboard": True,
    }


def promo_routes_keyboard() -> dict:
    return {
        "keyboard": [
            [
                {"text": __("promo.btn_route_add")},
                {"text": __("promo.btn_route_remove")},
            ],
            [
                {"text": __("promo.btn_route_mode")},
                {"text": __("promo.btn_route_pause")},
                {"text": __("promo.btn_route_resume")},
            ],
            [
                {"text": __("promo.btn_mode_forward")},
                {"text": __("promo.btn_mode_copy")},
            ],
            [
                {"text": __("promo.btn_group_add")},
                {"text": __("promo.btn_group_remove")},
                {"text": __("promo.btn_groups")},
            ],
            [{"text": __("nav.btn_back")}],
        ],
        "resize_keyboard": True,
    }


def promo_safety_keyboard() -> dict:
    return {
        "keyboard": [
            [
                {"text": __("promo.btn_safety_view")},
                {"text": __("promo.btn_safety_dump")},
            ],
            [
                {"text": __("promo.btn_safety_delay")},
                {"text": __("promo.btn_safety_budget")},
            ],
            [
                {"text": __("promo.btn_safety_windows")},
                {"text": __("promo.btn_safety_cooldown")},
                {"text": __("promo.btn_safety_tz")},
            ],
            [{"text": __("nav.btn_back")}],
        ],
        "resize_keyboard": True,
    }
