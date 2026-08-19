"""Rule definitions for the Smart Assignment Engine.

Each rule is a self-contained class that inherits from BaseRule.
Rules are stateless: all context they need is passed in via AssignmentContext.

To add a new rule:
  1. Create a subclass of BaseRule.
  2. Set `weight` (relative importance vs other rules).
  3. Implement `score(account, context) -> float` returning a value in [0.0, 1.0].
  4. Register it in RuleEngine.default_rules().

Rules can be hard-filters (return 0.0 to exclude) or soft-preferences (return
a fractional score that is blended with others).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


# ---------------------------------------------------------------------------
# Context object: everything a rule can inspect
# ---------------------------------------------------------------------------


@dataclass
class AssignmentContext:
    """Snapshot of the assignment request plus pre-computed environment data."""

    task_type: str                              # 'forward' | 'promo'
    source: str                                 # normalised source ref
    user_id: int

    # Pre-fetched from D1 (populated by AssignmentService before calling engine)
    load_summary: dict[str, dict[str, int]] = field(default_factory=dict)
    # {account_id: {"forward": N, "promo": N, "total": N}}

    heartbeats: dict[str, dict[str, Any]] = field(default_factory=dict)
    # {account_id: {status, modules_json, updated_at, ...}}

    sticky_account_id: str | None = None
    # If this source was previously assigned to an account, this is it.

    max_routes_per_account: int = 20
    # Configurable ceiling; accounts at or above this cap are ineligible.


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------


class BaseRule:
    """Interface all rules must implement."""

    #: Relative weight; higher = more influence on the final score.
    weight: float = 1.0

    #: If True, a score of 0.0 from this rule eliminates the account entirely.
    is_hard_filter: bool = False

    def score(self, account: dict[str, Any], context: AssignmentContext) -> float:
        """Return a value in [0.0, 1.0].

        0.0 means "never pick this account" (when is_hard_filter=True) or
        "strongly prefer not to" (when is_hard_filter=False).
        1.0 means "ideal candidate".
        """
        raise NotImplementedError

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(weight={self.weight})"


# ---------------------------------------------------------------------------
# Concrete rules
# ---------------------------------------------------------------------------


class StatusRule(BaseRule):
    """Hard filter: only accounts with status='ready' are eligible.

    An account that is still scaffolding, logging in, or in error state
    must never receive new assignments.
    """

    weight = 1.0
    is_hard_filter = True

    def score(self, account: dict[str, Any], context: AssignmentContext) -> float:
        status = str(account.get("status") or "").lower()
        enabled = int(account.get("enabled") or 0)
        if status == "ready" and enabled:
            return 1.0
        return 0.0


class RoleMatchRule(BaseRule):
    """Hard filter: account role must be compatible with task_type.

    forward  →  role in {forward, full}
    promo    →  role in {promo, full}
    """

    weight = 1.0
    is_hard_filter = True

    _COMPATIBLE: dict[str, frozenset[str]] = {
        "forward": frozenset({"forward", "full"}),
        "promo": frozenset({"promo", "full"}),
    }

    def score(self, account: dict[str, Any], context: AssignmentContext) -> float:
        role = str(account.get("role") or "").lower()
        compatible = self._COMPATIBLE.get(context.task_type, frozenset())
        return 1.0 if role in compatible else 0.0


class CapacityRule(BaseRule):
    """Hard filter: exclude accounts that have reached the route cap.

    The cap is set by context.max_routes_per_account (default 20).
    """

    weight = 1.0
    is_hard_filter = True

    def score(self, account: dict[str, Any], context: AssignmentContext) -> float:
        aid = str(account.get("id") or "")
        load = context.load_summary.get(aid, {})
        task_count = int(load.get(context.task_type) or 0)
        if task_count >= context.max_routes_per_account:
            return 0.0
        return 1.0


class LoadBalanceRule(BaseRule):
    """Soft preference: prefer accounts with fewer existing assignments.

    Score = 1 - (current_load / cap)
    An account at 0 assignments scores 1.0; at cap-1 it scores ~0.05.
    """

    weight = 3.0

    def score(self, account: dict[str, Any], context: AssignmentContext) -> float:
        aid = str(account.get("id") or "")
        load = context.load_summary.get(aid, {})
        task_count = int(load.get(context.task_type) or 0)
        cap = max(1, context.max_routes_per_account)
        fraction = task_count / cap
        return max(0.0, 1.0 - fraction)


class HeartbeatRule(BaseRule):
    """Soft preference: penalise accounts whose heartbeat is stale.

    - No heartbeat row → score 0.5 (unknown, do not exclude)
    - Heartbeat within 5 min → score 1.0
    - Heartbeat within 10 min → score 0.7
    - Older than 10 min or status != 'running' → score 0.2
    """

    weight = 2.0
    _FRESH_SECONDS = 300    # 5 min
    _WARN_SECONDS = 600     # 10 min

    def score(self, account: dict[str, Any], context: AssignmentContext) -> float:
        aid = str(account.get("id") or "")
        hb = context.heartbeats.get(aid)
        if not hb:
            return 0.5

        hb_status = str(hb.get("status") or "").lower()
        updated_at = str(hb.get("updated_at") or "")

        try:
            dt = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
            age = (datetime.now(timezone.utc) - dt).total_seconds()
        except Exception:
            return 0.5

        if hb_status not in {"running", "idle"}:
            return 0.2
        if age <= self._FRESH_SECONDS:
            return 1.0
        if age <= self._WARN_SECONDS:
            return 0.7
        return 0.2


class StickySourceRule(BaseRule):
    """Soft preference: if this source was previously on an account, prefer it.

    Stickiness reduces churn — the same source stays on the same account
    unless the account is ineligible or overloaded.
    A strong bonus (0.9) is given so the sticky account usually wins,
    but hard-filter rules can still eliminate it.
    """

    weight = 4.0

    def score(self, account: dict[str, Any], context: AssignmentContext) -> float:
        if not context.sticky_account_id:
            return 0.5  # neutral when there is no prior assignment
        aid = str(account.get("id") or "")
        return 0.9 if aid == context.sticky_account_id else 0.1


class TotalLoadRule(BaseRule):
    """Soft preference: prefer accounts with lower overall route count (all types).

    This complements LoadBalanceRule which is task-type specific.
    Useful when you want to distribute full-role accounts evenly across
    both forward and promo tasks.
    """

    weight = 1.0

    def score(self, account: dict[str, Any], context: AssignmentContext) -> float:
        aid = str(account.get("id") or "")
        load = context.load_summary.get(aid, {})
        total = int(load.get("total") or 0)
        cap = max(1, context.max_routes_per_account * 2)
        return max(0.0, 1.0 - total / cap)
