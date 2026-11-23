"""Pre-solver validation of input data. Findings are user-facing (Polish).

Cheap, certain infeasibility causes are detected here, before CP-SAT runs.
Diagnosing anything subtler is left to solver assumptions (later stage).
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from datetime import date, timedelta

from .calendar_utils import days_before, next_month_range
from .config import Settings
from .models import FixedAction, ProblemData, ValidationReport
from .preprocessing import (
    ProblemContext,
    Slot,
    build_context,
    compute_candidates,
    exclusion_reasons,
)

TARGET_HOURS_TOLERANCE = 0.05  # relative gap between summed targets and required hours


def validate_problem(data: ProblemData, settings: Settings) -> ValidationReport:
    """Run every check and return the combined report."""
    report = ValidationReport()
    ctx = build_context(data, settings)

    _check_basic_entities(ctx, report)
    _check_references_and_dates(ctx, report)
    _check_duplicates_and_qualifications(ctx, report)
    _check_history(ctx, report)
    _check_manual_locks(ctx, report)
    _check_limits_consistency(ctx, report)
    # Staffing diagnostics assume a structurally sound model.
    if report.ok:
        candidates = compute_candidates(ctx)
        _check_staffing(ctx, candidates, report)
        _check_limits_feasibility(ctx, candidates, report)
        _check_target_hours(ctx, report)
    return report


def _check_basic_entities(ctx: ProblemContext, report: ValidationReport) -> None:
    for employee_id, count in Counter(e.employee_id for e in ctx.data.employees).items():
        if count > 1:
            report.error("EMPLOYEE_DUPLICATE", f"Powtórzony identyfikator pracownika: {employee_id}")
    for post_id, count in Counter(p.post_id for p in ctx.data.posts).items():
        if count > 1:
            report.error("POST_DUPLICATE", f"Powtórzony identyfikator pionu: {post_id}")
    if not ctx.active_post_ids:
        report.error("NO_ACTIVE_POSTS", "Brak aktywnych pionów do obsadzenia.")
    if not ctx.active_employee_ids:
        report.error("NO_ACTIVE_EMPLOYEES", "Brak aktywnych pracowników.")


def _check_references_and_dates(ctx: ProblemContext, report: ValidationReport) -> None:
    first_day, last_day = ctx.days[0], ctx.days[-1]
    sources = {
        "qualifications.csv": ctx.data.qualifications,
        "availability.csv": ctx.data.availability,
        "fixed_assignments.csv": ctx.data.fixed_assignments,
        "previous_schedule.csv": ctx.data.previous_schedule,
    }
    for file_name, records in sources.items():
        for record in records:
            if record.employee_id not in ctx.employees:
                report.error(
                    "UNKNOWN_EMPLOYEE",
                    f"{file_name}: nieistniejący pracownik '{record.employee_id}'.",
                )
            post_id = getattr(record, "post_id", None)
            if post_id is not None and post_id not in ctx.posts:
                report.error("UNKNOWN_POST", f"{file_name}: nieistniejący pion '{post_id}'.")

    for entry in ctx.data.availability:
        if not first_day <= entry.date <= last_day:
            report.warning(
                "AVAILABILITY_OUT_OF_MONTH",
                f"availability.csv: wpis {entry.employee_id} z {entry.date.isoformat()} "
                f"leży poza planowanym miesiącem i zostanie pominięty.",
            )
    next_first, next_last = next_month_range(ctx.settings.year, ctx.settings.month)
    for fixed in ctx.data.fixed_assignments:
        if first_day <= fixed.date <= last_day:
            continue
        label = f"blokada {fixed.action.value} dla {fixed.employee_id} z {fixed.date.isoformat()}"
        if next_first <= fixed.date <= next_last:
            if fixed.action is FixedAction.FIX:
                continue  # accepted: constrains rest at the end of this month
            report.warning(
                "NEXT_MONTH_FORBID_IGNORED",
                f"fixed_assignments.csv: {label} dotyczy następnego miesiąca; "
                f"FORBID nie wpływa na ten grafik i jest pomijany.",
            )
        else:
            report.error(
                "FIXED_OUT_OF_MONTH",
                f"fixed_assignments.csv: {label} leży poza planowanym miesiącem "
                f"({first_day.isoformat()} - {last_day.isoformat()}) i następnym miesiącem.",
            )
    for shift in ctx.data.previous_schedule:
        if shift.date >= first_day:
            report.error(
                "PREVIOUS_NOT_BEFORE_MONTH",
                f"previous_schedule.csv: dyżur {shift.employee_id} z {shift.date.isoformat()} "
                f"nie poprzedza planowanego miesiąca.",
            )


def _check_duplicates_and_qualifications(ctx: ProblemContext, report: ValidationReport) -> None:
    for (employee_id, day), count in Counter(
        (a.employee_id, a.date) for a in ctx.data.availability
    ).items():
        if count > 1:
            report.error(
                "AVAILABILITY_DUPLICATE",
                f"availability.csv: powtórzony wpis dla {employee_id} i dnia {day.isoformat()}.",
            )
    for (employee_id, post_id), count in Counter(
        (q.employee_id, q.post_id) for q in ctx.data.qualifications
    ).items():
        if count > 1:
            report.error(
                "QUALIFICATION_DUPLICATE",
                f"qualifications.csv: powtórzona kwalifikacja {employee_id} / {post_id}.",
            )
    for q in ctx.data.qualifications:
        post = ctx.posts.get(q.post_id)
        if post is not None and post.shift_type != q.shift_type:
            report.error(
                "QUALIFICATION_TYPE_MISMATCH",
                f"qualifications.csv: {q.employee_id} / {q.post_id} ma rodzaj dyżuru "
                f"'{q.shift_type}', a pion jest typu '{post.shift_type}'.",
            )


def _check_history(ctx: ProblemContext, report: ValidationReport) -> None:
    for (employee_id, day), count in Counter(
        (s.employee_id, s.date) for s in ctx.data.previous_schedule
    ).items():
        if count > 1:
            report.warning(
                "PREVIOUS_DUPLICATE",
                f"previous_schedule.csv: kilka dyżurów {employee_id} w dniu {day.isoformat()}.",
            )
    for shift in ctx.data.previous_schedule:
        post = ctx.posts.get(shift.post_id)
        if post is not None and post.shift_type != shift.shift_type:
            report.warning(
                "PREVIOUS_TYPE_MISMATCH",
                f"previous_schedule.csv: {shift.employee_id} / {shift.date.isoformat()} ma rodzaj "
                f"'{shift.shift_type}', a pion {shift.post_id} jest typu '{post.shift_type}'.",
            )

    rest_days = ctx.settings.rest.max_rest_days()
    if rest_days == 0:
        return
    needed = days_before(ctx.days[0], rest_days)
    history_days = {s.date for s in ctx.data.previous_schedule}
    if not ctx.data.previous_schedule:
        report.warning(
            "HISTORY_EMPTY",
            "Brak historii dyżurów z poprzedniego miesiąca - nie można sprawdzić odpoczynku "
            "na początku miesiąca.",
        )
    elif not history_days.intersection(needed):
        report.warning(
            "HISTORY_GAP",
            f"Historia nie zawiera dyżurów z {needed[0].isoformat()} - {needed[-1].isoformat()}; "
            "odpoczynek na granicy miesięcy może być niewiarygodny.",
        )


def _check_manual_locks(ctx: ProblemContext, report: ValidationReport) -> None:
    fixes = [f for f in ctx.data.fixed_assignments if f.action is FixedAction.FIX]
    seen: Counter[tuple[str, date, str, str]] = Counter(
        (f.employee_id, f.date, f.post_id, f.action.value) for f in ctx.data.fixed_assignments
    )
    for (employee_id, day, post_id, action), count in seen.items():
        if count > 1:
            report.warning(
                "FIXED_DUPLICATE",
                f"fixed_assignments.csv: powtórzona blokada {action} {employee_id} / "
                f"{day.isoformat()} / {post_id}.",
            )

    in_month = set(ctx.days)
    by_slot: dict[Slot, set[str]] = defaultdict(set)
    by_employee_day: dict[tuple[str, date], set[str]] = defaultdict(set)
    for fix in fixes:
        if fix.date not in in_month or fix.employee_id not in ctx.employees or fix.post_id not in ctx.posts:
            continue  # already reported above
        label = f"{fix.employee_id} / {fix.date.isoformat()} / {fix.post_id}"
        if fix.post_id not in ctx.active_post_ids:
            report.error("FIX_INACTIVE_POST", f"FIX {label}: pion jest nieaktywny.")
        if (fix.employee_id, fix.date, fix.post_id) in ctx.forbidden:
            report.error(
                "FIX_FORBID_CONFLICT",
                f"Sprzeczne blokady: {label} jest jednocześnie FIX i FORBID.",
            )
        else:
            reasons = exclusion_reasons(ctx, fix.employee_id, fix.date, fix.post_id)
            if reasons:
                report.error(
                    "FIX_NOT_ALLOWED",
                    f"FIX {label} jest niemożliwy do spełnienia: {'; '.join(reasons)}.",
                )
        by_slot[(fix.date, fix.post_id)].add(fix.employee_id)
        by_employee_day[(fix.employee_id, fix.date)].add(fix.post_id)

    for (day, post_id), employee_ids in by_slot.items():
        if len(employee_ids) > 1:
            report.error(
                "FIX_SLOT_CONFLICT",
                f"Sprzeczne blokady: pion {post_id} w dniu {day.isoformat()} ma FIX dla wielu "
                f"pracowników ({', '.join(sorted(employee_ids))}).",
            )
    for (employee_id, day), post_ids in by_employee_day.items():
        if len(post_ids) > 1:
            report.error(
                "FIX_EMPLOYEE_DAY_CONFLICT",
                f"Sprzeczne blokady: {employee_id} ma FIX na wiele pionów "
                f"({', '.join(sorted(post_ids))}) w dniu {day.isoformat()}.",
            )

    rest_rules = ctx.settings.rest.rest_days_after_shift_type
    fixed_days = set(by_employee_day)
    for (employee_id, day), post_ids in by_employee_day.items():
        for post_id in post_ids:
            rest = rest_rules.get(ctx.posts[post_id].shift_type, 0)
            for offset in range(1, rest + 1):
                if (employee_id, day + timedelta(days=offset)) in fixed_days:
                    report.error(
                        "FIX_REST_CONFLICT",
                        f"Konflikt odpoczynku: {employee_id} ma FIX w dniu {day.isoformat()} "
                        f"(pion {post_id}) oraz FIX w dniu {(day + timedelta(days=offset)).isoformat()}.",
                    )


_LIMIT_PAIRS = (
    ("min_shifts", "max_shifts"),
    ("min_long_shifts", "max_long_shifts"),
    ("min_short_shifts", "max_short_shifts"),
)


def _check_limits_consistency(ctx: ProblemContext, report: ValidationReport) -> None:
    for employee in ctx.data.employees:
        if not employee.active:
            continue
        for low_name, high_name in _LIMIT_PAIRS:
            low, high = getattr(employee, low_name), getattr(employee, high_name)
            if low is not None and high is not None and low > high:
                report.error(
                    "LIMIT_INCONSISTENT",
                    f"Pracownik {employee.employee_id}: {low_name}={low} > {high_name}={high}.",
                )
        parts = [employee.min_long_shifts, employee.min_short_shifts]
        if (
            employee.max_shifts is not None
            and all(p is not None for p in parts)
            and sum(parts) > employee.max_shifts  # type: ignore[arg-type]
        ):
            report.error(
                "LIMIT_INCONSISTENT",
                f"Pracownik {employee.employee_id}: suma minimów dyżurów długich i krótkich "
                f"przekracza max_shifts={employee.max_shifts}.",
            )


def _check_staffing(
    ctx: ProblemContext, candidates: dict[Slot, list[str]], report: ValidationReport
) -> None:
    """Every slot needs a candidate, and each day needs a perfect matching of posts."""
    for day in ctx.days:
        empty_posts = [p for p in ctx.active_post_ids if not candidates[(day, p)]]
        for post_id in empty_posts:
            report.error(
                "NO_CANDIDATE",
                f"Dnia {day.isoformat()} nikt nie może obsadzić pionu {post_id} "
                f"(kwalifikacje / niedostępność / blokady / odpoczynek).",
            )
        if empty_posts:
            continue
        matched = _max_matching({p: candidates[(day, p)] for p in ctx.active_post_ids})
        if matched < len(ctx.active_post_ids):
            report.error(
                "INSUFFICIENT_STAFF",
                f"Dnia {day.isoformat()} nie da się obsadzić wszystkich pionów różnymi osobami: "
                f"maksymalnie {matched} z {len(ctx.active_post_ids)}.",
            )


def _max_matching(adjacency: dict[str, list[str]]) -> int:
    """Maximum bipartite matching (augmenting paths) of posts to employees."""
    owner: dict[str, str] = {}

    def augment(post: str, visited: set[str]) -> bool:
        for employee in adjacency[post]:
            if employee in visited:
                continue
            visited.add(employee)
            if employee not in owner or augment(owner[employee], visited):
                owner[employee] = post
                return True
        return False

    return sum(1 for post in adjacency if augment(post, set()))


def _slot_counts(ctx: ProblemContext) -> tuple[int, int, int]:
    """Total, long and short slots in the month."""
    days = len(ctx.days)
    classes = ctx.settings.shift_classes
    active = [ctx.posts[p] for p in ctx.active_post_ids]
    long_slots = days * sum(1 for p in active if p.shift_type == classes.long_shift_type)
    short_slots = days * sum(1 for p in active if p.shift_type == classes.short_shift_type)
    return days * len(active), long_slots, short_slots


def _check_limits_feasibility(
    ctx: ProblemContext, candidates: dict[Slot, list[str]], report: ValidationReport
) -> None:
    classes = ctx.settings.shift_classes
    rest_rules = ctx.settings.rest.rest_days_after_shift_type
    total_slots, long_slots, short_slots = _slot_counts(ctx)
    active = [ctx.employees[e] for e in ctx.active_employee_ids]

    possible_days: dict[str, set[date]] = defaultdict(set)
    possible_type_days: dict[tuple[str, str], set[date]] = defaultdict(set)
    for (day, post_id), employee_ids in candidates.items():
        shift_type = ctx.posts[post_id].shift_type
        for employee_id in employee_ids:
            possible_days[employee_id].add(day)
            possible_type_days[(employee_id, shift_type)].add(day)

    for employee in active:
        eid = employee.employee_id
        checks = (
            ("min_shifts", employee.min_shifts, len(possible_days[eid])),
            (
                "min_long_shifts",
                employee.min_long_shifts,
                _rest_capacity(
                    possible_type_days[(eid, classes.long_shift_type)],
                    rest_rules.get(classes.long_shift_type, 0),
                ),
            ),
            (
                "min_short_shifts",
                employee.min_short_shifts,
                _rest_capacity(
                    possible_type_days[(eid, classes.short_shift_type)],
                    rest_rules.get(classes.short_shift_type, 0),
                ),
            ),
        )
        for name, minimum, capacity in checks:
            if minimum is not None and minimum > capacity:
                report.error(
                    "LIMIT_UNREACHABLE",
                    f"Pracownik {eid}: {name}={minimum}, ale w tym miesiącu możliwych jest "
                    f"najwyżej {capacity} takich dyżurów (kwalifikacje, niedostępność, odpoczynek).",
                )

    aggregates = (
        ("dyżurów", total_slots, "min_shifts", "max_shifts"),
        ("dyżurów długich", long_slots, "min_long_shifts", "max_long_shifts"),
        ("dyżurów krótkich", short_slots, "min_short_shifts", "max_short_shifts"),
    )
    for label, slots, min_name, max_name in aggregates:
        minimum_sum = sum(getattr(e, min_name) or 0 for e in active)
        if minimum_sum > slots:
            report.error(
                "LIMIT_MIN_SUM_EXCEEDS_SLOTS",
                f"Suma minimów {label} ({minimum_sum}) przekracza liczbę stanowisk do obsadzenia ({slots}).",
            )
        maxima = [getattr(e, max_name) for e in active]
        if all(m is not None for m in maxima) and sum(maxima) < slots:  # type: ignore[arg-type]
            report.error(
                "LIMIT_MAX_SUM_BELOW_SLOTS",
                f"Suma maksimów {label} ({sum(maxima)}) jest mniejsza niż liczba stanowisk ({slots}).",  # type: ignore[arg-type]
            )


def _rest_capacity(days: set[date], rest_days: int) -> int:
    """Greedy maximum number of shifts on ``days`` honouring ``rest_days`` between them."""
    count, last = 0, None
    for day in sorted(days):
        if last is None or (day - last).days > rest_days:
            count += 1
            last = day
    return count


def _check_target_hours(ctx: ProblemContext, report: ValidationReport) -> None:
    active = [ctx.employees[e] for e in ctx.active_employee_ids]
    if not all(e.target_hours is not None for e in active):
        return
    required = len(ctx.days) * sum(ctx.posts[p].duration_hours for p in ctx.active_post_ids)
    target_sum = sum(e.target_hours or 0 for e in active)
    if required and not math.isclose(target_sum, required, rel_tol=TARGET_HOURS_TOLERANCE):
        report.warning(
            "TARGET_HOURS_MISMATCH",
            f"Suma docelowych godzin ({target_sum} h) różni się od godzin do obsadzenia "
            f"({required} h); odchylenia będą nieuniknione (to cel miękki).",
        )
