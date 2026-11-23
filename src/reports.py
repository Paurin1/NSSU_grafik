"""Builds tables and the text report from a solved schedule (no file I/O here)."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date

import pandas as pd

from .calendar_utils import month_days, weekday_name_pl
from .config import Settings
from .models import AvailabilityKind, ProblemData, ValidationReport
from .objective import day_weight, hours_targets
from .optimizer import SolveResult
from .preprocessing import build_context

SCHEDULE_COLUMNS = [
    "date", "weekday", "post_id", "post_name", "shift_type",
    "duration_hours", "employee_id", "employee_name",
]
PREFERENCE_KINDS = (AvailabilityKind.PREFER_16, AvailabilityKind.PREFER_5)


@dataclass
class ScheduleReports:
    """All report tables derived from one schedule."""

    schedule: pd.DataFrame
    employees: pd.DataFrame
    statistics: pd.DataFrame
    preferences: pd.DataFrame
    consecutive_short_pairs: int
    realized_preferences: int


def build_reports(data: ProblemData, settings: Settings, result: SolveResult) -> ScheduleReports:
    ctx = build_context(data, settings)
    posts, employees = ctx.posts, ctx.employees
    rows = []
    for (day, post_id), employee_id in sorted(result.assignments.items()):
        post = posts[post_id]
        rows.append([
            day.isoformat(), weekday_name_pl(day), post_id, post.post_name, post.shift_type,
            post.duration_hours, employee_id, employees[employee_id].name,
        ])
    schedule = pd.DataFrame(rows, columns=SCHEDULE_COLUMNS)

    by_employee: dict[str, list[tuple[date, str]]] = defaultdict(list)
    for (day, post_id), employee_id in result.assignments.items():
        by_employee[employee_id].append((day, post_id))

    classes = settings.shift_classes
    targets = hours_targets(ctx)
    preference_rows = []
    realized_total = 0
    summary_rows = []
    for employee_id in ctx.active_employee_ids:
        duties = by_employee.get(employee_id, [])
        long_n = sum(1 for _, p in duties if posts[p].shift_type == classes.long_shift_type)
        short_n = sum(1 for _, p in duties if posts[p].shift_type == classes.short_shift_type)
        hours = sum(posts[p].duration_hours for _, p in duties)
        weekend_days = {d for d, _ in duties if day_weight(ctx, d) > 0}
        worked = {d: posts[p].shift_type for d, p in duties}

        realized = mismatched = unused = 0
        for (eid, day), kind in ctx.availability.items():
            if eid != employee_id or kind not in PREFERENCE_KINDS or day not in set(ctx.days):
                continue
            wanted = classes.long_shift_type if kind is AvailabilityKind.PREFER_16 else classes.short_shift_type
            if day not in worked:
                unused += 1
            elif worked[day] == wanted:
                realized += 1
            else:
                mismatched += 1
        realized_total += realized
        preference_rows.append([
            employee_id, employees[employee_id].name, realized, mismatched, unused,
        ])
        summary_rows.append([
            employee_id, employees[employee_id].name, long_n, short_n, long_n + short_n, hours,
            targets[employee_id], hours - targets[employee_id], len(weekend_days), realized,
        ])

    employees_df = pd.DataFrame(summary_rows, columns=[
        "employee_id", "name", "shifts_16h", "shifts_5h", "total_shifts", "total_hours",
        "target_hours", "deviation_hours", "weekend_days", "preferences_realized",
    ])
    preferences_df = pd.DataFrame(preference_rows, columns=[
        "employee_id", "name", "realized", "other_shift_type", "not_assigned_that_day",
    ])
    statistics = _statistics(employees_df)
    return ScheduleReports(
        schedule=schedule,
        employees=employees_df,
        statistics=statistics,
        preferences=preferences_df,
        consecutive_short_pairs=_count_consecutive_short(ctx, result, settings),
        realized_preferences=realized_total,
    )


def _statistics(employees: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for column in ("total_hours", "total_shifts", "shifts_16h", "shifts_5h", "weekend_days"):
        series = employees[column]
        rows.append([column, series.min(), series.max(), round(series.mean(), 2), round(series.std(ddof=0), 2)])
    return pd.DataFrame(rows, columns=["metric", "min", "max", "mean", "std"])


def _count_consecutive_short(ctx, result: SolveResult, settings: Settings) -> int:
    short_type = settings.consecutive_short.shift_type
    short_days: set[tuple[str, date]] = {
        (e, d) for (d, p), e in result.assignments.items() if ctx.posts[p].shift_type == short_type
    }
    history = {(s.employee_id, s.date) for s in ctx.data.previous_schedule if s.shift_type == short_type}
    pairs = 0
    from datetime import timedelta

    for employee_id, day in short_days:
        if (employee_id, day - timedelta(days=1)) in short_days | history:
            pairs += 1
    return pairs


def format_optimization_report(
    settings: Settings,
    result: SolveResult,
    reports: ScheduleReports | None,
    validation: ValidationReport,
    input_report: ValidationReport,
) -> str:
    """Plain-text report in Polish."""
    lines = [
        f"RAPORT OPTYMALIZACJI - {settings.year}-{settings.month:02d}",
        "=" * 60,
        f"Status solvera: {result.status}",
        f"Czas obliczeń: {result.wall_time_seconds:.2f} s",
    ]
    if result.status == "FEASIBLE":
        lines.append("UWAGA: rozwiązanie poprawne, ale optymalność nie została udowodniona.")
    if result.objective_value is not None:
        lines.append(f"Wartość funkcji celu: {result.objective_value:.0f}")
        for name, value in result.penalties.items():
            lines.append(f"  kara {name}: {value}")
    if reports is not None:
        emp = reports.employees
        lines += [
            "",
            "Rozkład godzin (min / średnia / max): "
            f"{emp.total_hours.min()} / {emp.total_hours.mean():.1f} / {emp.total_hours.max()}",
            "Rozkład liczby dyżurów (min / średnia / max): "
            f"{emp.total_shifts.min()} / {emp.total_shifts.mean():.1f} / {emp.total_shifts.max()}",
            f"Zrealizowane preferencje: {reports.realized_preferences}",
            f"Kolejne dyżury 5 h: {reports.consecutive_short_pairs}",
            "Rozkład weekendów (dni weekendowe na osobę): "
            + ", ".join(f"{k}: {v}" for k, v in sorted(Counter(emp.weekend_days).items())),
        ]
    warnings = input_report.warnings + validation.warnings
    errors = input_report.errors + validation.errors
    lines += ["", f"Ostrzeżenia ({len(warnings)}):"] + [f"  - {i.message}" for i in warnings]
    lines += [f"Błędy ({len(errors)}):"] + [f"  - {i.message}" for i in errors]
    lines.append("")
    lines.append(
        "Grafik: ZATWIERDZALNY (brak błędów twardych)" if not validation.errors and result.has_solution
        else "Grafik: NIE MOŻE BYĆ ZATWIERDZONY"
    )
    return "\n".join(lines) + "\n"
