"""Keyboard layouts (structure only — labels come from lang)."""
from __future__ import annotations

from app.Support.Lang import __


def main_keyboard() -> dict:
    return {
        "keyboard": [
            [{"text": __("menu.btn_status")}, {"text": __("menu.btn_accounts")}],
            [{"text": __("menu.btn_discovery")}, {"text": __("menu.btn_promo")}],
            [{"text": __("menu.btn_ops")}, {"text": __("menu.btn_settings")}],
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
                {"text": __("accounts.role_full")},
                {"text": __("accounts.btn_cancel")},
            ],
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


def discovery_menu_keyboard() -> dict:
    return {
        "keyboard": [
            [
                {"text": __("discovery.btn_refresh")},
                {"text": __("discovery.btn_pool_status")},
            ],
            [
                {"text": __("discovery.btn_pool_list")},
                {"text": __("discovery.btn_pool_approve")},
            ],
            [
                {"text": __("discovery.btn_pool_reject")},
                {"text": __("discovery.btn_inspect_dry")},
            ],
            [
                {"text": __("discovery.btn_inspect_pause")},
                {"text": __("discovery.btn_inspect_resume")},
            ],
            [
                {"text": __("discovery.btn_inspect_budget")},
                {"text": __("discovery.btn_harvest_pause")},
            ],
            [
                {"text": __("discovery.btn_harvest_resume")},
                {"text": __("discovery.btn_harvest_add")},
            ],
            [
                {"text": __("discovery.btn_help")},
                {"text": __("accounts.btn_back")},
            ],
        ],
        "resize_keyboard": True,
    }


def promo_menu_keyboard() -> dict:
    return {
        "keyboard": [
            [
                {"text": __("promo.btn_refresh")},
                {"text": __("promo.btn_dry")},
            ],
            [
                {"text": __("promo.btn_pause")},
                {"text": __("promo.btn_resume")},
            ],
            [
                {"text": __("promo.btn_mode_forward")},
                {"text": __("promo.btn_mode_copy")},
            ],
            [
                {"text": __("promo.btn_help")},
                {"text": __("accounts.btn_back")},
            ],
        ],
        "resize_keyboard": True,
    }
