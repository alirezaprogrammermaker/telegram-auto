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
                {"text": __("accounts.btn_cancel")},
            ],
            [{"text": __("accounts.btn_back")}],
        ],
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
