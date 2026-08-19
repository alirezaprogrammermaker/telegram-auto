"""Smart Assignment Service — orchestrates rule-based account selection.

Responsibilities
----------------
1. Gather the context (load summary, heartbeats, sticky lookup) from D1.
2. Run the RuleEngine to rank eligible accounts.
3. Patch the winner's GitHub profile with the new route.
4. Persist the assignment record in D1 for audit trail + future lookups.
5. Optionally dispatch (restart) the winner's GitHub Actions workflow.

Public API (called from AssignmentController and AgentCommandBus)
-----------------------------------------------------------------
    svc = AssignmentService(db, scaffold, runner)

    result = await svc.assign_forward(user_id, source, destination,
                                      *, auto_dispatch=True)
    result = await svc.assign_promo(user_id, source, groups,
                                    *, auto_dispatch=True)
    await svc.remove(assignment_id)
    rows   = await svc.list(user_id, task_type=None)
    load   = await svc.get_account_load(user_id)
    ranked = await svc.preview(user_id, task_type, source)  # dry-run
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any

from app.Models.Account import Account
from app.Models.Assignment import Assignment
from app.Models.Command import AccountHeartbeat
from app.Services.AccountScaffoldService import AccountScaffoldService
from app.Services.ProfileConfigService import ProfileConfigService
from app.Services.RuleEngine import RuleEngine, ScoredAccount
from app.Services.RunOrchestratorService import RunOrchestratorService
from app.Support.AssignmentRules import AssignmentContext
from app.Support.PromoRoutes import display_ref, normalize_group_list

MAX_ROUTES_PER_ACCOUNT = 20  # tunable ceiling per task-type


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class AssignmentResult:
    assignment_id: str
    account_id: str
    account_label: str
    task_type: str
    source: str
    target: str | None
    score: float
    breakdown: dict[str, float] = field(default_factory=dict)
    dispatch_info: dict[str, Any] | None = None
    was_sticky: bool = False   # True when the same account was chosen as before


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class NoEligibleAccountError(Exception):
    """Raised when no account passes the hard-filter rules."""

    def __init__(self, reason: str = "no_eligible_account") -> None:
        super().__init__(reason)
        self.reason = reason


class AssignmentNotFoundError(Exception):
    pass


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class AssignmentService:
    def __init__(
        self,
        db,
        scaffold: AccountScaffoldService,
        runner: RunOrchestratorService | None = None,
        engine: RuleEngine | None = None,
    ) -> None:
        self.db = db
        self.scaffold = scaffold
        self.runner = runner
        self.engine = engine or RuleEngine.default()
        self._profile = ProfileConfigService(db, scaffold)

    # ------------------------------------------------------------------
    # Public: assign
    # ------------------------------------------------------------------

    async def assign_forward(
        self,
        user_id: int,
        source: str,
        destination: str,
        *,
        auto_dispatch: bool = True,
        exclude_account_ids: set[str] | None = None,
    ) -> AssignmentResult:
        """Assign a forward route to the best eligible account.

        1. Normalise refs.
        2. Build context, run engine.
        3. Patch GitHub profile.
        4. Record in D1.
        5. Dispatch workflow (if auto_dispatch and runner available).
        """
        source_ref = display_ref(source)
        dest_ref = display_ref(destination)
        if not source_ref or not dest_ref:
            raise ValueError("source and destination must be non-empty refs")

        winner, context = await self._run_engine(
            user_id, "forward", source_ref, exclude_account_ids=exclude_account_ids
        )

        await self._profile.forward_add_route(
            user_id, winner.account_id, source_ref, dest_ref
        )

        assignment = await Assignment.create(
            self.db,
            user_id=user_id,
            account_id=winner.account_id,
            task_type="forward",
            source=source_ref,
            target=dest_ref,
            score=winner.breakdown,
        )

        dispatch_info = None
        if auto_dispatch and self.runner:
            try:
                dispatch_info = await self.runner.dispatch(user_id, winner.account_id)
            except Exception:
                pass  # non-fatal: profile is already patched

        acct = winner.account
        return AssignmentResult(
            assignment_id=str(assignment.get("id")),
            account_id=winner.account_id,
            account_label=str(acct.get("label") or winner.account_id),
            task_type="forward",
            source=source_ref,
            target=dest_ref,
            score=winner.score,
            breakdown=winner.breakdown,
            dispatch_info=dispatch_info,
            was_sticky=(context.sticky_account_id == winner.account_id),
        )

    async def assign_promo(
        self,
        user_id: int,
        source: str,
        groups: list[str],
        *,
        auto_dispatch: bool = True,
        exclude_account_ids: set[str] | None = None,
    ) -> AssignmentResult:
        """Assign a promo route to the best eligible account."""
        source_ref = display_ref(source)
        if not source_ref:
            raise ValueError("source must be a non-empty ref")
        groups_clean = normalize_group_list(groups)
        if not groups_clean:
            raise ValueError("at least one group is required")

        winner, context = await self._run_engine(
            user_id, "promo", source_ref, exclude_account_ids=exclude_account_ids
        )

        groups_csv = ",".join(groups_clean)
        await self._profile.promo_add_route(
            user_id, winner.account_id, source_ref, groups_csv
        )

        import json as _json
        assignment = await Assignment.create(
            self.db,
            user_id=user_id,
            account_id=winner.account_id,
            task_type="promo",
            source=source_ref,
            target=_json.dumps(groups_clean),
            score=winner.breakdown,
        )

        dispatch_info = None
        if auto_dispatch and self.runner:
            try:
                dispatch_info = await self.runner.dispatch(user_id, winner.account_id)
            except Exception:
                pass

        acct = winner.account
        return AssignmentResult(
            assignment_id=str(assignment.get("id")),
            account_id=winner.account_id,
            account_label=str(acct.get("label") or winner.account_id),
            task_type="promo",
            source=source_ref,
            target=_json.dumps(groups_clean),
            score=winner.score,
            breakdown=winner.breakdown,
            dispatch_info=dispatch_info,
            was_sticky=(context.sticky_account_id == winner.account_id),
        )

    # ------------------------------------------------------------------
    # Public: preview (dry-run — no writes)
    # ------------------------------------------------------------------

    async def preview(
        self, user_id: int, task_type: str, source: str
    ) -> list[ScoredAccount]:
        """Return the engine's ranked list without modifying anything.

        Useful for showing the user which account *would* be chosen and why.
        """
        source_ref = display_ref(source) or source
        _, _ = None, None
        context = await self._build_context(user_id, task_type, source_ref)
        accounts = await self._fetch_accounts(user_id)
        account_dicts = [a.to_view() for a in accounts]
        return self.engine.rank(account_dicts, context)

    # ------------------------------------------------------------------
    # Public: remove
    # ------------------------------------------------------------------

    async def remove(
        self,
        assignment_id: str,
        *,
        user_id: int,
        cleanup_profile: bool = True,
        auto_dispatch: bool = True,
    ) -> dict[str, Any]:
        """Soft-delete an assignment record and optionally clean profile state."""
        row = await Assignment.find(self.db, assignment_id)
        if not row:
            raise AssignmentNotFoundError(assignment_id)
        if str(row.get("user_id")) != str(user_id):
            raise PermissionError("not_your_assignment")
        account_id = str(row.get("account_id") or "")
        task_type = str(row.get("task_type") or "")
        source = str(row.get("source") or "")
        target = row.get("target")
        cleaned = False
        dispatch_info = None
        if cleanup_profile:
            if task_type == "forward":
                await self._profile.forward_remove_route(user_id, account_id, source)
                cleaned = True
            elif task_type == "promo":
                groups: list[str] = []
                if isinstance(target, str):
                    try:
                        parsed = json.loads(target)
                        if isinstance(parsed, list):
                            groups = [str(x) for x in parsed if str(x).strip()]
                    except Exception:
                        groups = []
                if groups:
                    for group in groups:
                        await self._profile.promo_group_remove(
                            user_id, account_id, source, group
                        )
                else:
                    await self._profile.promo_remove_route(user_id, account_id, source)
                cleaned = True
        await Assignment.remove(self.db, assignment_id)
        if auto_dispatch and cleaned and self.runner:
            try:
                dispatch_info = await self.runner.dispatch(user_id, account_id)
            except Exception:
                dispatch_info = None
        return {
            "assignment_id": assignment_id,
            "account_id": account_id,
            "task_type": task_type,
            "source": source,
            "cleaned_profile": cleaned,
            "dispatch_info": dispatch_info,
        }

    async def reassign_account(
        self,
        user_id: int,
        failed_account_id: str,
        *,
        auto_dispatch: bool = True,
    ) -> dict[str, Any]:
        rows = await Assignment.list_for_account(
            self.db, failed_account_id, status="active", limit=500
        )
        moved: list[dict[str, Any]] = []
        for row in rows:
            if str(row.get("user_id") or "") != str(user_id):
                continue
            task_type = str(row.get("task_type") or "")
            source = str(row.get("source") or "")
            if task_type == "forward":
                destination = str(row.get("target") or "")
                result = await self.assign_forward(
                    user_id,
                    source,
                    destination,
                    auto_dispatch=auto_dispatch,
                    exclude_account_ids={failed_account_id},
                )
            elif task_type == "promo":
                target = str(row.get("target") or "")
                try:
                    groups = json.loads(target)
                except Exception:
                    groups = []
                if not isinstance(groups, list) or not groups:
                    continue
                result = await self.assign_promo(
                    user_id,
                    source,
                    [str(x) for x in groups],
                    auto_dispatch=auto_dispatch,
                    exclude_account_ids={failed_account_id},
                )
            else:
                continue
            await self.remove(
                str(row.get("id")),
                user_id=user_id,
                cleanup_profile=True,
                auto_dispatch=auto_dispatch,
            )
            moved.append(
                {
                    "old_assignment_id": str(row.get("id") or ""),
                    "new_assignment_id": result.assignment_id,
                    "source": source,
                    "task_type": task_type,
                    "new_account_id": result.account_id,
                }
            )
        return {"moved": moved, "count": len(moved)}

    # ------------------------------------------------------------------
    # Public: list / load
    # ------------------------------------------------------------------

    async def list(
        self,
        user_id: int,
        *,
        task_type: str | None = None,
        status: str = "active",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        rows = await Assignment.list_for_user(
            self.db, user_id, task_type=task_type, status=status, limit=limit
        )
        return [r.to_dict() for r in rows]

    async def get_account_load(self, user_id: int) -> dict[str, dict[str, int]]:
        """Return {account_id: {forward, promo, total}} for the user's accounts."""
        return await Assignment.load_summary(self.db, user_id=user_id)

    # ------------------------------------------------------------------
    # Internal: engine plumbing
    # ------------------------------------------------------------------

    async def _run_engine(
        self,
        user_id: int,
        task_type: str,
        source: str,
        *,
        exclude_account_ids: set[str] | None = None,
    ) -> tuple[ScoredAccount, AssignmentContext]:
        context = await self._build_context(user_id, task_type, source)
        accounts = await self._fetch_accounts(
            user_id, exclude_account_ids=exclude_account_ids
        )
        account_dicts = [a.to_view() for a in accounts]

        ranked = self.engine.rank(account_dicts, context)
        if not ranked:
            raise NoEligibleAccountError(
                f"no eligible account for task_type={task_type}"
            )
        return ranked[0], context

    async def _build_context(
        self, user_id: int, task_type: str, source: str
    ) -> AssignmentContext:
        load_summary = await Assignment.load_summary(self.db, user_id=user_id)

        # Heartbeats: {account_id: row_dict}
        # AccountHeartbeat.all() is not on the base model; query directly.
        heartbeats: dict[str, dict[str, Any]] = {}
        try:
            hb_rows = await AccountHeartbeat.query(self.db).get()
            for hb in hb_rows:
                hb_dict = hb.to_dict()
                aid = str(hb_dict.get("account_id") or "")
                if aid:
                    heartbeats[aid] = hb_dict
        except Exception:
            pass

        # Sticky lookup
        sticky_row = await Assignment.find_by_source(
            self.db, user_id=user_id, task_type=task_type, source=source
        )
        sticky_account_id = (
            str(sticky_row.get("account_id")) if sticky_row else None
        )

        return AssignmentContext(
            task_type=task_type,
            source=source,
            user_id=user_id,
            load_summary=load_summary,
            heartbeats=heartbeats,
            sticky_account_id=sticky_account_id,
            max_routes_per_account=MAX_ROUTES_PER_ACCOUNT,
        )

    async def _fetch_accounts(
        self, user_id: int, *, exclude_account_ids: set[str] | None = None
    ) -> list[Account]:
        rows = await Account.for_user(self.db, user_id)
        blocked = {str(x) for x in (exclude_account_ids or set()) if str(x)}
        if not blocked:
            return rows
        return [row for row in rows if str(row.get("id") or "") not in blocked]
