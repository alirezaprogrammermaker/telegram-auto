"""Human-friendly error messages instead of raw exception strings."""
from __future__ import annotations


def friendly_error(exc: Exception) -> str:
    msg = str(exc)
    ml = msg.lower()
    if "422" in msg or "unprocessable" in ml:
        return "اطلاعات ارسالی معتبر نبود. ورودی را بررسی کن."
    if "404" in msg or "not found" in ml:
        return "مورد مورد نظر یافت نشد."
    if "403" in msg or "forbidden" in ml or "permission" in ml:
        return "دسترسی ناکافی است. سطح دسترسی را بررسی کن."
    if "401" in msg or "unauthorized" in ml:
        return "احراز هویت ناموفق. اتصال GitHub را بررسی کن."
    if "timeout" in ml or "timed out" in ml:
        return "زمان عملیات به پایان رسید. دوباره تلاش کن."
    if "connect" in ml or "connection" in ml or "network" in ml:
        return "اتصال برقرار نشد. اینترنت را بررسی کن."
    if "no workflow" in ml or "workflow" in ml:
        return "ورک‌فلو پیدا نشد. ابتدا اکانت را فعال کن."
    if "account_disabled" in ml:
        return "اکانت غیرفعال است. ابتدا آن را فعال کن."
    if "not owned" in ml or "owned" in ml:
        return "این اکانت متعلق به تو نیست."
    return "خطای غیرمنتظره رخ داد. با مدیر تماس بگیر."
