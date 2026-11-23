"""Hard constraints of the CP-SAT model (stage 2).

Qualifications, unavailability, FORBID and rest after history duties are already
enforced by *not creating* variables (see ``preprocessing.compute_candidates``).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from ortools.sat.python import cp_model

from .preprocessing import ProblemContext, Slot

VarKey = tuple[str, date, str]  # (employee_id, day, post_id)


@dataclass
class ModelVariables:
    """Decision variables x[employee, day, post] and index helpers."""

    x: dict[VarKey, cp_model.IntVar]

    def day_vars(self, employee_id: str, day: date) -> list[cp_model.IntVar]:
        return [v for (e, d, _), v in self.x.items() if e == employee_id and d == day]


def create_variables(
    model: cp_model.CpModel, candidates: dict[Slot, list[str]]
) -> ModelVariables:
    """One boolean per allowed (employee, day, post); no variables for forbidden combos."""
    variables = {
        (employee_id, day, post_id): model.new_bool_var(f"x_{employee_id}_{day.isoformat()}_{post_id}")
        for (day, post_id), employee_ids in candidates.items()
        for employee_id in employee_ids
    }
    return ModelVariables(variables)


def add_full_coverage(
    model: cp_model.CpModel, ctx: ProblemContext, mv: ModelVariables
) -> None:
    """Every active post is staffed by exactly one person every day."""
    by_slot: dict[Slot, list[cp_model.IntVar]] = {}
    for (_, day, post_id), var in mv.x.items():
        by_slot.setdefault((day, post_id), []).append(var)
    for day in ctx.days:
        for post_id in ctx.active_post_ids:
            slot_vars = by_slot.get((day, post_id), [])
            if slot_vars:
                model.add_exactly_one(slot_vars)
            else:
                model.add_bool_or([])  # empty clause = infeasible, reported by validation


def add_one_shift_per_day(
    model: cp_model.CpModel, ctx: ProblemContext, mv: ModelVariables
) -> None:
    """At most one duty per employee per day."""
    by_employee_day: dict[tuple[str, date], list[cp_model.IntVar]] = {}
    for (employee_id, day, _), var in mv.x.items():
        by_employee_day.setdefault((employee_id, day), []).append(var)
    for variables in by_employee_day.values():
        if len(variables) > 1:
            model.add_at_most_one(variables)


def add_rest_rules(
    model: cp_model.CpModel, ctx: ProblemContext, mv: ModelVariables
) -> None:
    """After a shift type with rest requirement, no duty on the following N days.

    Since a person has at most one duty per day, ``rest_shift + any_duty_later <= 1``.
    Boundary with the previous month is handled by candidate filtering, with the
    next month by FIX locks (see ``preprocessing.exclusion_reasons``).
    """
    rest_rules = ctx.settings.rest.rest_days_after_shift_type
    day_vars: dict[tuple[str, date], list[cp_model.IntVar]] = {}
    rest_vars: dict[tuple[str, date, int], list[cp_model.IntVar]] = {}
    for (employee_id, day, post_id), var in mv.x.items():
        day_vars.setdefault((employee_id, day), []).append(var)
        rest_days = rest_rules.get(ctx.posts[post_id].shift_type, 0)
        if rest_days:
            rest_vars.setdefault((employee_id, day, rest_days), []).append(var)

    for (employee_id, day, rest_days), starters in rest_vars.items():
        for offset in range(1, rest_days + 1):
            later = day_vars.get((employee_id, day + timedelta(days=offset)), [])
            if later:
                model.add(sum(starters) + sum(later) <= 1)


def add_employee_limits(
    model: cp_model.CpModel, ctx: ProblemContext, mv: ModelVariables
) -> None:
    """Explicitly set min/max shift limits (total, long, short) are hard constraints."""
    classes = ctx.settings.shift_classes
    groups = {
        "": lambda stype: True,
        "_long": lambda stype: stype == classes.long_shift_type,
        "_short": lambda stype: stype == classes.short_shift_type,
    }
    by_employee: dict[str, list[tuple[str, cp_model.IntVar]]] = {}
    for (employee_id, _, post_id), var in mv.x.items():
        by_employee.setdefault(employee_id, []).append((ctx.posts[post_id].shift_type, var))

    for employee_id in ctx.active_employee_ids:
        employee = ctx.employees[employee_id]
        entries = by_employee.get(employee_id, [])
        for suffix, belongs in groups.items():
            total = sum(var for stype, var in entries if belongs(stype))
            minimum = getattr(employee, f"min{suffix}_shifts" if suffix else "min_shifts")
            maximum = getattr(employee, f"max{suffix}_shifts" if suffix else "max_shifts")
            if minimum is not None:
                model.add(total >= minimum)
            if maximum is not None:
                model.add(total <= maximum)


def add_hard_constraints(
    model: cp_model.CpModel, ctx: ProblemContext, mv: ModelVariables
) -> None:
    add_full_coverage(model, ctx, mv)
    add_one_shift_per_day(model, ctx, mv)
    add_rest_rules(model, ctx, mv)
    add_employee_limits(model, ctx, mv)
