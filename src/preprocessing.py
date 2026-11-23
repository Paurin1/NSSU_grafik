"""Derives lookup structures and candidate sets from raw data.

Shared by validation (diagnostics) and, later, the CP-SAT model builder so the
rules deciding who may work where exist in exactly one place.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from .calendar_utils import month_days, next_month_range
from .config import Settings
from .models import AvailabilityKind, Employee, FixedAction, Post, ProblemData

Slot = tuple[date, str]  # (day, post_id)


@dataclass
class ProblemContext:
    """Indexed view of the problem for one month."""

    data: ProblemData
    settings: Settings
    days: list[date]
    employees: dict[str, Employee]
    posts: dict[str, Post]
    active_employee_ids: list[str]
    active_post_ids: list[str]
    qualified: set[tuple[str, str]]
    availability: dict[tuple[str, date], AvailabilityKind]
    forbidden: set[tuple[str, date, str]]
    fixed: set[tuple[str, date, str]]
    history_rest_blocked: dict[tuple[str, date], date]  # (employee, day) -> historical duty day
    next_month_fixed: set[tuple[str, date]]  # FIX days in the following month


def build_context(data: ProblemData, settings: Settings) -> ProblemContext:
    """Index the raw data. Invalid references are skipped here; validation reports them."""
    days = month_days(settings.year, settings.month)
    day_set = set(days)
    employees = {e.employee_id: e for e in data.employees}
    posts = {p.post_id: p for p in data.posts}

    qualified = {
        (q.employee_id, q.post_id)
        for q in data.qualifications
        if q.qualified and q.post_id in posts and posts[q.post_id].shift_type == q.shift_type
    }

    availability: dict[tuple[str, date], AvailabilityKind] = {}
    for entry in data.availability:
        availability.setdefault((entry.employee_id, entry.date), entry.availability)

    forbidden = {
        (f.employee_id, f.date, f.post_id)
        for f in data.fixed_assignments
        if f.action is FixedAction.FORBID
    }
    fixed = {
        (f.employee_id, f.date, f.post_id)
        for f in data.fixed_assignments
        if f.action is FixedAction.FIX
    }

    next_first, next_last = next_month_range(settings.year, settings.month)
    next_month_fixed = {
        (f.employee_id, f.date)
        for f in data.fixed_assignments
        if f.action is FixedAction.FIX and next_first <= f.date <= next_last
    }

    rest_rules = settings.rest.rest_days_after_shift_type
    history_blocked: dict[tuple[str, date], date] = {}
    for shift in data.previous_schedule:
        for offset in range(1, rest_rules.get(shift.shift_type, 0) + 1):
            blocked_day = shift.date + timedelta(days=offset)
            if blocked_day in day_set:
                history_blocked.setdefault((shift.employee_id, blocked_day), shift.date)

    return ProblemContext(
        data=data,
        settings=settings,
        days=days,
        employees=employees,
        posts=posts,
        active_employee_ids=[e.employee_id for e in data.employees if e.active],
        active_post_ids=[p.post_id for p in data.posts if p.active],
        qualified=qualified,
        availability=availability,
        forbidden=forbidden,
        fixed=fixed,
        history_rest_blocked=history_blocked,
        next_month_fixed=next_month_fixed,
    )


def exclusion_reasons(ctx: ProblemContext, employee_id: str, day: date, post_id: str) -> list[str]:
    """Reasons (Polish) why the employee cannot work the post that day; empty = allowed."""
    reasons: list[str] = []
    employee = ctx.employees.get(employee_id)
    if employee is None:
        return ["nieznany pracownik"]
    if not employee.active:
        reasons.append("pracownik nieaktywny")
    if (employee_id, post_id) not in ctx.qualified:
        reasons.append("brak kwalifikacji do pionu")
    if ctx.availability.get((employee_id, day)) is AvailabilityKind.UNAVAILABLE:
        reasons.append("niedostępność (UNAVAILABLE)")
    if (employee_id, day, post_id) in ctx.forbidden:
        reasons.append("ręczny zakaz (FORBID)")
    historical_day = ctx.history_rest_blocked.get((employee_id, day))
    if historical_day is not None:
        reasons.append(f"obowiązkowy odpoczynek po dyżurze z {historical_day.isoformat()}")
    post = ctx.posts.get(post_id)
    rest_days = ctx.settings.rest.rest_days_after_shift_type.get(post.shift_type, 0) if post else 0
    for offset in range(1, rest_days + 1):
        later = day + timedelta(days=offset)
        if (employee_id, later) in ctx.next_month_fixed:
            reasons.append(f"FIX w następnym miesiącu ({later.isoformat()}) wymaga odpoczynku")
            break
    return reasons


def compute_candidates(ctx: ProblemContext) -> dict[Slot, list[str]]:
    """Employees allowed for each (day, active post); FIX narrows a slot to its employee."""
    fixed_by_slot: dict[Slot, set[str]] = {}
    for employee_id, day, post_id in ctx.fixed:
        fixed_by_slot.setdefault((day, post_id), set()).add(employee_id)

    candidates: dict[Slot, list[str]] = {}
    for day in ctx.days:
        for post_id in ctx.active_post_ids:
            allowed = [
                employee_id
                for employee_id in ctx.active_employee_ids
                if not exclusion_reasons(ctx, employee_id, day, post_id)
            ]
            forced = fixed_by_slot.get((day, post_id))
            if forced:
                allowed = [e for e in allowed if e in forced]
            candidates[(day, post_id)] = allowed
    return candidates
