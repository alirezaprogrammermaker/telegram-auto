from __future__ import annotations

from pathlib import Path

from modules.promo_spread.queue import PromoQueue


def test_try_claim_post_ack_only_when_settled(tmp_path: Path | None = None) -> None:
    root = Path("data") / "_test_promo_ack"
    root.mkdir(parents=True, exist_ok=True)
    path = root / "promo_queue.json"
    if path.exists():
        path.unlink()
    q = PromoQueue(path=path)
    q.enqueue(
        source_id=1,
        group_ref="@g1",
        group_id=11,
        message_ids=[10],
        mode="forward",
        post_key="1:10-10",
    )
    q.enqueue(
        source_id=1,
        group_ref="@g2",
        group_id=22,
        message_ids=[10],
        mode="forward",
        post_key="1:10-10",
    )
    assert q.try_claim_post_ack("1:10-10") is False
    pending = q.list_pending()
    q.mark_done(str(pending[0]["id"]))
    assert q.try_claim_post_ack("1:10-10") is False
    pending = q.list_pending()
    q.mark_done(str(pending[0]["id"]))
    assert q.try_claim_post_ack("1:10-10") is True
    assert q.try_claim_post_ack("1:10-10") is False
