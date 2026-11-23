"""Shared builders for tiny, fully known test datasets."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from src.config import Settings
from src.models import (
    AvailabilityEntry,
    AvailabilityKind,
    Employee,
    FixedAction,
    FixedAssignment,
    Post,
    PreviousShift,
    ProblemData,
    Qualification,
)

YEAR, MONTH = 2026, 2  # 28 days


def make_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {"year": YEAR, "month": MONTH}
    values.update(overrides)
    return Settings(**values)


def make_data(
    employee_ids: tuple[str, ...] = ("E1", "E2", "E3", "E4"),
    posts: tuple[tuple[str, str, int], ...] = (("A", "16", 16), ("B", "5", 5)),
    history: bool = True,
) -> ProblemData:
    """Everybody active and qualified for every post; history covers the days before the month."""
    data = ProblemData(
        employees=[Employee(e, f"Name {e}", True) for e in employee_ids],
        posts=[Post(pid, f"Pion {pid}", stype, hours, True) for pid, stype, hours in posts],
        previous_schedule_provided=True,
    )
    data.qualifications = [
        Qualification(e, pid, stype, True) for e in employee_ids for pid, stype, _ in posts
    ]
    if history:
        data.previous_schedule = [PreviousShift(employee_ids[-1], date(YEAR, MONTH - 1, 31), "B", "5")]
    return data


def day(number: int) -> date:
    return date(YEAR, MONTH, number)


def unavailable(employee_id: str, number: int) -> AvailabilityEntry:
    return AvailabilityEntry(employee_id, day(number), AvailabilityKind.UNAVAILABLE)


def fix(employee_id: str, number: int, post_id: str) -> FixedAssignment:
    return FixedAssignment(employee_id, day(number), post_id, FixedAction.FIX)


def forbid(employee_id: str, number: int, post_id: str) -> FixedAssignment:
    return FixedAssignment(employee_id, day(number), post_id, FixedAction.FORBID)


def write_file(directory: Path, name: str, text: str) -> None:
    (directory / name).write_text(text, encoding="utf-8")


def write_minimal_dataset(directory: Path) -> None:
    """Valid CSV set: 2 employees, 1 post."""
    write_file(directory, "employees.csv", "employee_id;name;active;target_hours\nE1;Jan;1;40\nE2;Anna;1;\n")
    write_file(directory, "shifts.csv", "post_id;post_name;shift_type;duration_hours;active\nA;Pion A;16;16;1\n")
    write_file(
        directory,
        "qualifications.csv",
        "employee_id;post_id;shift_type;qualified\nE1;A;16;1\nE2;A;16;0\n",
    )
