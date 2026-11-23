"""Soft constraints: every criterion is a separate non-negative penalty term.

Terms are kept apart (not pre-summed) so a later stage can optimise them
lexicographically; ``apply_weighted_sum`` is the first-version strategy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from ortools.sat.python import cp_model

from .constraints import ModelVariables
from .models import AvailabilityKind
from .preprocessing import ProblemContext

SATURDAY, SUNDAY = 5, 6

# Criterion names double as keys in settings ``weights``.
HOURS = "hours_balance"
SHIFT_COUNT = "shift_count_balance"
PREFERENCES = "preferences"
CONSECUTIVE = "consecutive_5h"
WEEKENDS = "weekend_balance"
LONG_BALANCE = "long_shift_balance"
SHORT_BALANCE = "short_shift_balance"

# Lexicographic order for a future multi-stage optimisation (most important first).
PRIORITY_ORDER = (HOURS, SHIFT_COUNT, PREFERENCES, CONSECUTIVE, WEEKENDS, LONG_BALANCE, SHORT_BALANCE)


@dataclass
class PenaltyTerms:
    """Linear penalty expressions by criterion name."""

    terms: dict[str, cp_model.LinearExprT] = field(default_factory=dict)


def _hours_by_employee(ctx: ProblemContext, mv: ModelVariables) -> dict[str, cp_model.LinearExprT]:
    hours: dict[str, list] = {e: [] for e in ctx.active_employee_ids}
    for (employee_id, _, post_id), var in mv.x.items():
        hours[employee_id].append(ctx.posts[post_id].duration_hours * var)
    return {e: sum(parts) for e, parts in hours.items()}


def _counts_by_employee(
    ctx: ProblemContext, mv: ModelVariables, shift_type: str | None = None
) -> dict[str, cp_model.LinearExprT]:
    counts: dict[str, list] = {e: [] for e in ctx.active_employee_ids}
    for (employee_id, _, post_id), var in mv.x.items():
        if shift_type is None or ctx.posts[post_id].shift_type == shift_type:
            counts[employee_id].append(var)
    return {e: sum(parts) for e, parts in counts.items()}


def _abs_deviation(
    model: cp_model.CpModel, expr: cp_model.LinearExprT, target: int, ub: int, name: str
) -> cp_model.IntVar:
    deviation = model.new_int_var(0, ub, name)
    model.add(deviation >= expr - target)
    model.add(deviation >= target - expr)
    return deviation


def _spread(
    model: cp_model.CpModel, exprs: list[cp_model.LinearExprT], ub: int, name: str
) -> cp_model.LinearExprT:
    """max - min over the given expressions (0 when fewer than two)."""
    if len(exprs) < 2:
        return 0
    high = model.new_int_var(0, ub, f"{name}_max")
    low = model.new_int_var(0, ub, f"{name}_min")
    for expr in exprs:
        model.add(high >= expr)
        model.add(low <= expr)
    return high - low


def _history_enabled(ctx: ProblemContext) -> bool:
    return ctx.settings.balancing.use_history


def history_hours(ctx: ProblemContext) -> dict[str, int]:
    """Hours worked per active employee in ``previous_schedule`` (unknown posts count 0)."""
    hours = dict.fromkeys(ctx.active_employee_ids, 0)
    if not _history_enabled(ctx):
        return hours
    for shift in ctx.data.previous_schedule:
        post = ctx.posts.get(shift.post_id)
        if post is not None and shift.employee_id in hours:
            hours[shift.employee_id] += post.duration_hours
    return hours


def history_counts(ctx: ProblemContext, shift_type: str) -> dict[str, int]:
    """Historical number of duties of ``shift_type`` per active employee."""
    counts = dict.fromkeys(ctx.active_employee_ids, 0)
    if not _history_enabled(ctx):
        return counts
    for shift in ctx.data.previous_schedule:
        if shift.shift_type == shift_type and shift.employee_id in counts:
            counts[shift.employee_id] += 1
    return counts


def history_weekend_load(ctx: ProblemContext) -> dict[str, int]:
    """Weighted weekend/holiday duties in the history per active employee."""
    load = dict.fromkeys(ctx.active_employee_ids, 0)
    if not _history_enabled(ctx):
        return load
    for shift in ctx.data.previous_schedule:
        if shift.employee_id in load:
            load[shift.employee_id] += day_weight(ctx, shift.date)
    return load


def hours_targets(ctx: ProblemContext) -> dict[str, int]:
    """Monthly hour goal per employee.

    Base: target_hours, or an equal share of the required hours when unset.
    With history, people who worked more than the average in the history window
    get a lower goal (and vice versa), so load evens out over a longer period.
    The shift is zero-sum across employees before clamping at 0.
    """
    required = len(ctx.days) * sum(ctx.posts[p].duration_hours for p in ctx.active_post_ids)
    fallback = round(required / max(1, len(ctx.active_employee_ids)))
    base = {
        e: ctx.employees[e].target_hours if ctx.employees[e].target_hours is not None else fallback
        for e in ctx.active_employee_ids
    }
    past = history_hours(ctx)
    mean_past = sum(past.values()) / max(1, len(past))
    return {e: max(0, base[e] - round(past[e] - mean_past)) for e in base}


def shift_count_targets(ctx: ProblemContext) -> dict[str, int]:
    """Individual count goal: target hours over the mean duty length of the month."""
    slots = len(ctx.days) * len(ctx.active_post_ids)
    required = len(ctx.days) * sum(ctx.posts[p].duration_hours for p in ctx.active_post_ids)
    mean_duration = required / max(1, slots)
    return {
        e: round(target / mean_duration) if mean_duration else 0
        for e, target in hours_targets(ctx).items()
    }


def day_weight(ctx: ProblemContext, day: date) -> int:
    """Weekend weight of a day; holidays count at least as the configured holiday weight."""
    rules = ctx.settings.weekends
    weight = 0
    if day.weekday() == SATURDAY:
        weight = rules.saturday_weight
    elif day.weekday() == SUNDAY:
        weight = rules.sunday_weight
    if day in rules.holidays:
        weight = max(weight, rules.holiday_weight)
    return weight


def build_penalty_terms(
    model: cp_model.CpModel, ctx: ProblemContext, mv: ModelVariables
) -> PenaltyTerms:
    result = PenaltyTerms()
    rules = ctx.settings.balancing
    classes = ctx.settings.shift_classes
    employees = ctx.active_employee_ids
    max_hours = len(ctx.days) * max(ctx.posts[p].duration_hours for p in ctx.active_post_ids)
    max_count = len(ctx.days)

    if rules.balance_hours:
        hours, targets = _hours_by_employee(ctx, mv), hours_targets(ctx)
        result.terms[HOURS] = sum(
            _abs_deviation(model, hours[e], targets[e], max_hours + targets[e], f"dev_h_{e}")
            for e in employees
        )

    if rules.balance_shift_count:
        counts, count_targets = _counts_by_employee(ctx, mv), shift_count_targets(ctx)
        result.terms[SHIFT_COUNT] = sum(
            _abs_deviation(model, counts[e], count_targets[e], max_count + count_targets[e], f"dev_n_{e}")
            for e in employees
        )

    result.terms[PREFERENCES] = _preference_penalty(ctx, mv)
    result.terms[CONSECUTIVE] = _consecutive_short_penalty(model, ctx, mv)
    result.terms[WEEKENDS] = _weekend_penalty(model, ctx, mv)

    if rules.balance_long_shifts:
        counts = _counts_by_employee(ctx, mv, classes.long_shift_type)
        past = history_counts(ctx, classes.long_shift_type)
        result.terms[LONG_BALANCE] = _spread(
            model, [counts[e] + past[e] for e in employees], max_count + max(past.values(), default=0), "long"
        )
    if rules.balance_short_shifts:
        counts = _counts_by_employee(ctx, mv, classes.short_shift_type)
        past = history_counts(ctx, classes.short_shift_type)
        result.terms[SHORT_BALANCE] = _spread(
            model, [counts[e] + past[e] for e in employees], max_count + max(past.values(), default=0), "short"
        )
    return result


def _preference_penalty(ctx: ProblemContext, mv: ModelVariables) -> cp_model.LinearExprT:
    """PREFER_16 on a short duty / PREFER_5 on a long duty costs ``mismatch_penalty``."""
    classes = ctx.settings.shift_classes
    penalty = ctx.settings.preferences.mismatch_penalty
    mismatches = []
    for (employee_id, day, post_id), var in mv.x.items():
        preference = ctx.availability.get((employee_id, day))
        shift_type = ctx.posts[post_id].shift_type
        if (preference is AvailabilityKind.PREFER_16 and shift_type == classes.short_shift_type) or (
            preference is AvailabilityKind.PREFER_5 and shift_type == classes.long_shift_type
        ):
            mismatches.append(var)
    return penalty * sum(mismatches)


def _consecutive_short_penalty(
    model: cp_model.CpModel, ctx: ProblemContext, mv: ModelVariables
) -> cp_model.LinearExprT:
    """Counts pairs of short duties on adjacent days (history included); allowed but penalised."""
    short_type = ctx.settings.consecutive_short.shift_type
    short_by_day: dict[tuple[str, date], list[cp_model.IntVar]] = {}
    for (employee_id, day, post_id), var in mv.x.items():
        if ctx.posts[post_id].shift_type == short_type:
            short_by_day.setdefault((employee_id, day), []).append(var)

    history_short = {
        (s.employee_id, s.date)
        for s in ctx.data.previous_schedule
        if s.shift_type == short_type
    }
    pair_vars: list[cp_model.IntVar] = []
    for (employee_id, day), today in short_by_day.items():
        tomorrow = short_by_day.get((employee_id, day + timedelta(days=1)))
        if tomorrow:
            pair = model.new_bool_var(f"cons_{employee_id}_{day.isoformat()}")
            model.add(pair >= sum(today) + sum(tomorrow) - 1)
            pair_vars.append(pair)
        if (employee_id, day - timedelta(days=1)) in history_short:
            pair_vars.extend(today)  # at most one duty a day, so this is 0/1
    return sum(pair_vars)


def _weekend_penalty(
    model: cp_model.CpModel, ctx: ProblemContext, mv: ModelVariables
) -> cp_model.LinearExprT:
    """Spread (max - min) of weighted weekend/holiday duties among people who can work them."""
    loads: dict[str, list] = {}
    for (employee_id, day, _), var in mv.x.items():
        weight = day_weight(ctx, day)
        if weight:
            loads.setdefault(employee_id, []).append(weight * var)
    past = history_weekend_load(ctx)
    exprs = [sum(parts) + past[e] for e, parts in loads.items()]
    upper = sum(day_weight(ctx, d) for d in ctx.days) + max(past.values(), default=0)
    return _spread(model, exprs, max(1, upper), "weekend")


def apply_weighted_sum(
    model: cp_model.CpModel, ctx: ProblemContext, penalties: PenaltyTerms
) -> None:
    """First-version objective: Z = sum(weight_k * penalty_k), all penalties >= 0."""
    weights = ctx.settings.weights.model_dump()
    total = sum(weights[name] * expr for name, expr in penalties.terms.items() if weights.get(name, 0))
    model.minimize(total)
