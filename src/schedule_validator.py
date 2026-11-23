"""Independent validation of a finished schedule.

Deliberately does not reuse the solver's candidate filtering: every rule is
re-checked directly against the raw input data.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, timedelta

from .calendar_utils import month_days
from .config import Settings
from .models import AvailabilityKind, FixedAction, ProblemData, ValidationReport

Assignment = tuple[date, str, str]  # (day, post_id, employee_id)


def validate_schedule(
    data: ProblemData, settings: Settings, assignments: list[Assignment]
) -> ValidationReport:
    """Return errors (block approval) and warnings for the given assignments."""
    report = ValidationReport()
    days = month_days(settings.year, settings.month)
    day_set = set(days)
    employees = {e.employee_id: e for e in data.employees}
    posts = {p.post_id: p for p in data.posts}
    active_posts = [p.post_id for p in data.posts if p.active]
    classes = settings.shift_classes

    valid: list[Assignment] = []
    for day, post_id, employee_id in assignments:
        if day not in day_set:
            report.error("DATE_OUT_OF_MONTH", f"Przydział {employee_id} / {post_id} z dnia {day.isoformat()} leży poza miesiącem.")
        elif post_id not in posts:
            report.error("UNKNOWN_POST", f"Przydział do nieistniejącego pionu '{post_id}'.")
        elif employee_id not in employees:
            report.error("UNKNOWN_EMPLOYEE", f"Przydział nieistniejącego pracownika '{employee_id}'.")
        else:
            valid.append((day, post_id, employee_id))

    for (day, post_id), count in Counter((d, p) for d, p, _ in valid).items():
        if count > 1:
            report.error("DUPLICATE_ASSIGNMENT", f"Pion {post_id} w dniu {day.isoformat()} ma {count} przydziały zamiast jednego.")
    for (day, post_id, employee_id), count in Counter(valid).items():
        if count > 1:
            report.error("DUPLICATE_ASSIGNMENT", f"Powtórzony przydział {employee_id} / {post_id} / {day.isoformat()}.")

    covered = {(d, p) for d, p, _ in valid}
    for day in days:
        for post_id in active_posts:
            if (day, post_id) not in covered:
                report.error("UNSTAFFED", f"Dnia {day.isoformat()} pion {post_id} nie jest obsadzony.")
    for day, post_id, _ in valid:
        if not posts[post_id].active:
            report.error("INACTIVE_POST", f"Przydział do nieaktywnego pionu {post_id} w dniu {day.isoformat()}.")

    per_employee_day: dict[tuple[str, date], list[str]] = defaultdict(list)
    for day, post_id, employee_id in valid:
        per_employee_day[(employee_id, day)].append(post_id)
    for (employee_id, day), post_ids in per_employee_day.items():
        if len(set(post_ids)) > 1:
            report.error("MULTIPLE_SHIFTS_PER_DAY", f"{employee_id} ma {len(post_ids)} dyżury w dniu {day.isoformat()}.")

    unavailable = {
        (a.employee_id, a.date)
        for a in data.availability
        if a.availability is AvailabilityKind.UNAVAILABLE
    }
    qualified = {(q.employee_id, q.post_id) for q in data.qualifications if q.qualified}
    for day, post_id, employee_id in valid:
        if not employees[employee_id].active:
            report.error("INACTIVE_EMPLOYEE", f"{employee_id} jest nieaktywny, a ma dyżur {day.isoformat()}.")
        if (employee_id, day) in unavailable:
            report.error("UNAVAILABLE", f"{employee_id} jest niedostępny {day.isoformat()}, a ma dyżur ({post_id}).")
        if (employee_id, post_id) not in qualified:
            report.error("NOT_QUALIFIED", f"{employee_id} nie ma kwalifikacji do pionu {post_id} ({day.isoformat()}).")

    _check_rest(data, settings, valid, posts, report)
    _check_manual_locks(data, valid, report)
    _check_limits(settings, employees, posts, valid, classes.long_shift_type, classes.short_shift_type, report)

    if not data.previous_schedule:
        report.warning("HISTORY_EMPTY", "Brak historii - nie sprawdzono odpoczynku na początku miesiąca.")
    return report


def _check_rest(data, settings, valid, posts, report) -> None:
    rest_rules = settings.rest.rest_days_after_shift_type
    duty_days: dict[str, set[date]] = defaultdict(set)
    duties: list[tuple[str, date, str]] = []
    for day, post_id, employee_id in valid:
        duty_days[employee_id].add(day)
        duties.append((employee_id, day, posts[post_id].shift_type))
    for shift in data.previous_schedule:
        duties.append((shift.employee_id, shift.date, shift.shift_type))

    for employee_id, day, shift_type in duties:
        for offset in range(1, rest_rules.get(shift_type, 0) + 1):
            later = day + timedelta(days=offset)
            if later in duty_days.get(employee_id, ()):
                report.error(
                    "REST_VIOLATION",
                    f"{employee_id}: dyżur w dniu {later.isoformat()} po dyżurze {shift_type} h z {day.isoformat()}.",
                )
    next_fixed = [
        f for f in data.fixed_assignments
        if f.action is FixedAction.FIX and f.date > month_days(settings.year, settings.month)[-1]
    ]
    for fixed in next_fixed:
        for day, post_id, employee_id in valid:
            gap = (fixed.date - day).days
            if employee_id == fixed.employee_id and 1 <= gap <= rest_rules.get(posts[post_id].shift_type, 0):
                report.error(
                    "REST_VIOLATION",
                    f"{employee_id}: dyżur z {day.isoformat()} koliduje z FIX w następnym miesiącu ({fixed.date.isoformat()}).",
                )


def _check_manual_locks(data, valid, report) -> None:
    assigned = {(e, d, p) for d, p, e in valid}
    days_in_schedule = {d for d, _, _ in valid}
    for lock in data.fixed_assignments:
        label = f"{lock.employee_id} / {lock.date.isoformat()} / {lock.post_id}"
        key = (lock.employee_id, lock.date, lock.post_id)
        if lock.action is FixedAction.FIX and lock.date in days_in_schedule and key not in assigned:
            report.error("FIX_VIOLATED", f"Nie zrealizowano ręcznego FIX: {label}.")
        elif lock.action is FixedAction.FORBID and key in assigned:
            report.error("FORBID_VIOLATED", f"Naruszono ręczny FORBID: {label}.")


def _check_limits(settings, employees, posts, valid, long_type, short_type, report) -> None:
    counts: dict[str, Counter[str]] = defaultdict(Counter)
    for _, post_id, employee_id in valid:
        stype = posts[post_id].shift_type
        counts[employee_id]["all"] += 1
        if stype == long_type:
            counts[employee_id]["long"] += 1
        if stype == short_type:
            counts[employee_id]["short"] += 1
    for employee in employees.values():
        if not employee.active:
            continue
        for key, low, high in (
            ("all", employee.min_shifts, employee.max_shifts),
            ("long", employee.min_long_shifts, employee.max_long_shifts),
            ("short", employee.min_short_shifts, employee.max_short_shifts),
        ):
            value = counts[employee.employee_id][key]
            if low is not None and value < low:
                report.error("LIMIT_BELOW_MIN", f"{employee.employee_id}: {value} dyżurów ({key}) < minimum {low}.")
            if high is not None and value > high:
                report.error("LIMIT_ABOVE_MAX", f"{employee.employee_id}: {value} dyżurów ({key}) > maksimum {high}.")
