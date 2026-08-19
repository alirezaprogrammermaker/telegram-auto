"""Export all catalog refs to a plain txt for manual Telegram review."""
from __future__ import annotations

from pathlib import Path

from experiments.linkdir_finders.catalog import LinkDirCatalog

OUT = Path(__file__).resolve().parent / "results" / "linkdir_all_links.txt"


def _link_of(r: dict) -> str:
    uname = r.get("username")
    ref = r.get("ref") or ""
    if uname:
        return f"https://t.me/{uname}"
    if str(ref).startswith("@"):
        return f"https://t.me/{str(ref)[1:]}"
    return str(ref)


def main() -> None:
    cat = LinkDirCatalog()
    rows = cat.list_items(limit=10000)
    rows.sort(
        key=lambda r: (
            1 if r.get("promo_ready") else 0,
            1 if r.get("postable") else 0,
            float(r.get("rank_score") or 0),
        ),
        reverse=True,
    )

    lines: list[str] = [
        f"# linkdir catalog export — {len(rows)} items",
        "# format: verdict | kind | postable | rank | members | link | title",
        "# postable=yes  => members can send messages (good promo target)",
        "# postable=no   => channel or locked group (seed only / not for promo)",
        "",
    ]
    public = 0
    for r in rows:
        link = _link_of(r)
        if link.startswith("https://t.me/"):
            public += 1
        title = (r.get("title") or "").replace("\n", " ").strip()
        verdict = str(r.get("verdict") or "-")
        kind = str(r.get("kind") or ("channel" if r.get("is_channel") else "group" if r.get("is_group") else "?"))
        if r.get("members_can_send") is True:
            postable = "yes"
        elif r.get("members_can_send") is False:
            postable = "no"
        else:
            postable = "?"
        rank = float(r.get("rank_score") or 0)
        mem = r.get("participants") or "-"
        lines.append(
            f"{verdict:6} | {kind:18} | post={postable:3} | {rank:5.1f} | mem={mem} | {link} | {title}"
        )

    lines.append("")
    lines.append("# --- promo_ready only (postable keep) ---")
    for r in rows:
        if r.get("promo_ready") and r.get("username"):
            lines.append(f"https://t.me/{r['username']}")

    lines.append("")
    lines.append("# --- all public links ---")
    for r in rows:
        uname = r.get("username")
        if uname:
            lines.append(f"https://t.me/{uname}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {OUT}")
    print(f"items={len(rows)} public_links={public}")


if __name__ == "__main__":
    main()
