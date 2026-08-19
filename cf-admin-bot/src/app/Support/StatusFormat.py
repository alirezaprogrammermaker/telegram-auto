"""Human-readable formatting for GitHub Actions run statuses."""
from __future__ import annotations


def translate_run_status(status: str | None, conclusion: str | None) -> str:
    s = (status or "").lower().strip()
    c = (conclusion or "").lower().strip()
    if s == "queued":
        return "در صف اجرا ⏳"
    if s == "in_progress":
        return "در حال اجرا 🔄"
    if s == "completed":
        if c == "success":
            return "موفق ✅"
        if c == "failure":
            return "ناموفق ❌ — لاگ را بررسی کن"
        if c == "cancelled":
            return "لغو شده ⏹"
        if c == "skipped":
            return "رد شده ⏭"
        if c == "timed_out":
            return "زمان منقضی شد ⏱"
        return f"تمام شده ({c})"
    if s == "waiting":
        return "در انتظار تأیید ⏳"
    if not s or s == "-":
        return "—"
    return f"{s}/{c}" if c else s


def format_run_line(run_id, status: str | None, conclusion: str | None, url: str | None) -> str:
    status_fa = translate_run_status(status, conclusion)
    parts = [status_fa]
    if run_id:
        parts.append(f"(#{run_id})")
    if url:
        parts.append(f"— {url}")
    return " ".join(parts)


def format_live_metrics(row: dict) -> str:
    """Compact heartbeat metrics line for status panels."""
    if row.get("heartbeat_stale"):
        return "📡 زنده: بدون heartbeat"
    hb_at = row.get("heartbeat_at") or "—"
    hb_status = row.get("heartbeat_status") or "—"
    parts = [f"📡 {hb_status} @ {hb_at}"]

    fwd_q = row.get("forward_queue_pending")
    promo_q = row.get("promo_queue_pending")
    queue_bits: list[str] = []
    if fwd_q is not None:
        queue_bits.append(f"fwd صف={fwd_q}")
    if promo_q is not None:
        queue_bits.append(f"promo صف={promo_q}")
    if queue_bits:
        parts.append(" | ".join(queue_bits))

    stats = row.get("stats_today")
    if isinstance(stats, dict):
        day = stats.get("day") or "امروز"
        parts.append(
            f"📈 {day}: fwd={stats.get('forwarded', 0)} "
            f"block={stats.get('blocked', 0)} "
            f"pub={stats.get('published_scheduled', 0)}"
        )
    circuit = row.get("promo_circuit")
    if isinstance(circuit, dict) and circuit.get("is_open"):
        reason = circuit.get("pause_reason") or "circuit"
        until = circuit.get("paused_until") or "?"
        parts.append(f"🛡 promo circuit OPEN تا {until} ({reason})")
    return "\n  ".join(parts)
