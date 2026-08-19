"""Pluggable rule-based scoring engine for Smart Assignment.

Usage
-----
    engine = RuleEngine.default()
    ranked = engine.rank(accounts, context)  # sorted best-first
    winner = ranked[0] if ranked else None

Extension
---------
    engine.register(MyCustomRule())

The engine can also be rebuilt from scratch:
    engine = RuleEngine(rules=[RoleMatchRule(), LoadBalanceRule(weight=5.0)])

Design
------
Scoring is a two-phase process:

1. Hard-filter phase: any rule with is_hard_filter=True that returns 0.0
   immediately disqualifies the account — no further rules are evaluated.

2. Soft-score phase: remaining rules contribute weighted scores.
   Final score = sum(rule.weight * rule.score(...)) / sum(weights)

The result also carries a breakdown dict for UI transparency ("why was this
account chosen?").
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.Support.AssignmentRules import (
    AssignmentContext,
    BaseRule,
    CapacityRule,
    HeartbeatRule,
    LoadBalanceRule,
    RoleMatchRule,
    StatusRule,
    StickySourceRule,
    TotalLoadRule,
)


@dataclass
class ScoredAccount:
    """An account with its computed score and per-rule breakdown."""

    account: dict[str, Any]
    score: float                              # weighted average [0.0, 1.0]
    breakdown: dict[str, float] = field(default_factory=dict)
    # {RuleClassName: raw_score}
    disqualified_by: str | None = None       # set when a hard-filter fired

    @property
    def account_id(self) -> str:
        return str(self.account.get("id") or "")

    def to_dict(self) -> dict[str, Any]:
        return {
            "account_id": self.account_id,
            "score": round(self.score, 4),
            "breakdown": {k: round(v, 4) for k, v in self.breakdown.items()},
            "disqualified_by": self.disqualified_by,
        }


class RuleEngine:
    """Stateless engine that scores and ranks accounts.

    Rules are evaluated in registration order.  Hard-filter rules are
    evaluated first within that order; soft rules contribute to the blend.
    """

    def __init__(self, rules: list[BaseRule] | None = None) -> None:
        self._rules: list[BaseRule] = list(rules or [])

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def default(cls) -> "RuleEngine":
        """Build the standard engine with all built-in rules."""
        return cls(
            rules=[
                # Hard filters (order matters — cheaper checks first)
                StatusRule(),
                RoleMatchRule(),
                CapacityRule(),
                # Soft preferences
                StickySourceRule(),
                LoadBalanceRule(),
                HeartbeatRule(),
                TotalLoadRule(),
            ]
        )

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, rule: BaseRule) -> "RuleEngine":
        """Append a rule.  Returns self for chaining."""
        self._rules.append(rule)
        return self

    def replace(self, rule_class: type, new_rule: BaseRule) -> "RuleEngine":
        """Replace the first rule of rule_class with new_rule."""
        self._rules = [
            new_rule if isinstance(r, rule_class) else r for r in self._rules
        ]
        return self

    @property
    def rules(self) -> list[BaseRule]:
        return list(self._rules)

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def _score_one(
        self, account: dict[str, Any], context: AssignmentContext
    ) -> ScoredAccount:
        breakdown: dict[str, float] = {}
        soft_rules: list[BaseRule] = []

        # Phase 1: hard filters
        for rule in self._rules:
            if not rule.is_hard_filter:
                soft_rules.append(rule)
                continue
            s = rule.score(account, context)
            breakdown[rule.__class__.__name__] = s
            if s == 0.0:
                return ScoredAccount(
                    account=account,
                    score=0.0,
                    breakdown=breakdown,
                    disqualified_by=rule.__class__.__name__,
                )

        # Phase 2: soft scoring
        total_weight = 0.0
        weighted_sum = 0.0
        for rule in soft_rules:
            s = rule.score(account, context)
            breakdown[rule.__class__.__name__] = s
            weighted_sum += rule.weight * s
            total_weight += rule.weight

        final = weighted_sum / total_weight if total_weight > 0 else 0.0
        return ScoredAccount(account=account, score=final, breakdown=breakdown)

    def rank(
        self, accounts: list[dict[str, Any]], context: AssignmentContext
    ) -> list[ScoredAccount]:
        """Score every account and return eligible ones sorted best-first.

        Disqualified accounts are filtered out from the result.
        """
        scored = [self._score_one(a, context) for a in accounts]
        eligible = [s for s in scored if s.disqualified_by is None]
        eligible.sort(key=lambda s: s.score, reverse=True)
        return eligible

    def score_all(
        self, accounts: list[dict[str, Any]], context: AssignmentContext
    ) -> list[ScoredAccount]:
        """Like rank() but also includes disqualified accounts (for debugging)."""
        scored = [self._score_one(a, context) for a in accounts]
        scored.sort(key=lambda s: (s.disqualified_by is None, s.score), reverse=True)
        return scored
