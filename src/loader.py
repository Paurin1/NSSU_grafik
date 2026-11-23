"""CSV loading. Row-level problems become issues (row skipped); structural ones raise."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import TypeVar

import pandas as pd

from .models import (
    AvailabilityEntry,
    AvailabilityKind,
    DataLoadError,
    Employee,
    FixedAction,
    FixedAssignment,
    PreviousShift,
    Post,
    ProblemData,
    Qualification,
    ValidationReport,
)

T = TypeVar("T")

CSV_ENCODING = "utf-8-sig"
CSV_HEADER_LINES = 1  # row N of the DataFrame is file line N + 2

EMPLOYEES_FILE = "employees.csv"
AVAILABILITY_FILE = "availability.csv"
QUALIFICATIONS_FILE = "qualifications.csv"
SHIFTS_FILE = "shifts.csv"
FIXED_FILE = "fixed_assignments.csv"
PREVIOUS_FILE = "previous_schedule.csv"

EMPLOYEE_COLUMNS = ["employee_id", "name", "active", "target_hours"]
EMPLOYEE_OPTIONAL_COLUMNS = [
    "min_shifts",
    "max_shifts",
    "min_long_shifts",
    "max_long_shifts",
    "min_short_shifts",
    "max_short_shifts",
]


class _RowError(ValueError):
    """Row cannot be parsed; the message is reported to the user."""


def _parse_bool(value: str, column: str) -> bool:
    if value in ("1", "true", "True", "TRUE"):
        return True
    if value in ("0", "false", "False", "FALSE"):
        return False
    raise _RowError(f"kolumna '{column}' musi mieć wartość 1 lub 0 (jest: '{value}')")


def _parse_int(value: str, column: str, minimum: int = 0) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise _RowError(f"kolumna '{column}' musi być liczbą całkowitą (jest: '{value}')") from exc
    if number < minimum:
        raise _RowError(f"kolumna '{column}' nie może być mniejsza niż {minimum} (jest: {number})")
    return number


def _parse_optional_int(value: str, column: str) -> int | None:
    return None if value == "" else _parse_int(value, column)


def _parse_date(value: str, column: str = "date") -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise _RowError(
            f"kolumna '{column}' musi mieć format RRRR-MM-DD i istniejącą datę (jest: '{value}')"
        ) from exc


def _parse_enum(value: str, enum_type: type[T], column: str) -> T:
    try:
        return enum_type(value)  # type: ignore[call-arg]
    except ValueError as exc:
        allowed = ", ".join(m.value for m in enum_type)  # type: ignore[attr-defined]
        raise _RowError(
            f"kolumna '{column}' ma niedozwoloną wartość '{value}' (dozwolone: {allowed})"
        ) from exc


def _require_text(value: str, column: str) -> str:
    if value == "":
        raise _RowError(f"kolumna '{column}' nie może być pusta")
    return value


def _read_table(
    path: Path,
    delimiter: str,
    required: list[str],
    report: ValidationReport,
    mandatory: bool,
) -> pd.DataFrame | None:
    """Read a CSV as strings. Returns None for an absent optional file."""
    if not path.is_file():
        if mandatory:
            report.error("FILE_MISSING", f"Brak wymaganego pliku: {path.name}")
            raise DataLoadError(report)
        return None
    try:
        frame = pd.read_csv(
            path,
            sep=delimiter,
            dtype=str,
            keep_default_na=False,
            encoding=CSV_ENCODING,
            skipinitialspace=True,
        )
    except (pd.errors.ParserError, pd.errors.EmptyDataError, UnicodeDecodeError) as exc:
        report.error("FILE_UNREADABLE", f"Nie można odczytać pliku {path.name}: {exc}")
        raise DataLoadError(report) from exc
    frame.columns = [str(c).strip() for c in frame.columns]
    missing = [c for c in required if c not in frame.columns]
    if missing:
        report.error(
            "COLUMNS_MISSING",
            f"W pliku {path.name} brakuje kolumn: {', '.join(missing)}",
        )
        raise DataLoadError(report)
    return frame.apply(lambda col: col.str.strip())


def _parse_rows(
    frame: pd.DataFrame | None,
    file_name: str,
    parser: Callable[[dict[str, str]], T],
    report: ValidationReport,
) -> list[T]:
    """Apply ``parser`` to every row; invalid rows are reported and skipped."""
    if frame is None:
        return []
    parsed: list[T] = []
    for index, row in enumerate(frame.to_dict(orient="records")):
        line = index + CSV_HEADER_LINES + 1
        try:
            parsed.append(parser(row))
        except _RowError as exc:
            report.error("ROW_INVALID", f"{file_name}, wiersz {line}: {exc}")
    return parsed


def _employee(row: dict[str, str]) -> Employee:
    return Employee(
        employee_id=_require_text(row["employee_id"], "employee_id"),
        name=_require_text(row["name"], "name"),
        active=_parse_bool(row["active"], "active"),
        target_hours=_parse_optional_int(row["target_hours"], "target_hours"),
        **{
            col: _parse_optional_int(row.get(col, ""), col)
            for col in EMPLOYEE_OPTIONAL_COLUMNS
        },
    )


def _post(row: dict[str, str]) -> Post:
    return Post(
        post_id=_require_text(row["post_id"], "post_id"),
        post_name=_require_text(row["post_name"], "post_name"),
        shift_type=_require_text(row["shift_type"], "shift_type"),
        duration_hours=_parse_int(row["duration_hours"], "duration_hours", minimum=1),
        active=_parse_bool(row["active"], "active"),
    )


def _qualification(row: dict[str, str]) -> Qualification:
    return Qualification(
        employee_id=_require_text(row["employee_id"], "employee_id"),
        post_id=_require_text(row["post_id"], "post_id"),
        shift_type=_require_text(row["shift_type"], "shift_type"),
        qualified=_parse_bool(row["qualified"], "qualified"),
    )


def _availability(row: dict[str, str]) -> AvailabilityEntry:
    return AvailabilityEntry(
        employee_id=_require_text(row["employee_id"], "employee_id"),
        date=_parse_date(row["date"]),
        availability=_parse_enum(row["availability"], AvailabilityKind, "availability"),
    )


def _fixed(row: dict[str, str]) -> FixedAssignment:
    return FixedAssignment(
        employee_id=_require_text(row["employee_id"], "employee_id"),
        date=_parse_date(row["date"]),
        post_id=_require_text(row["post_id"], "post_id"),
        action=_parse_enum(row["action"], FixedAction, "action"),
    )


def _previous(row: dict[str, str]) -> PreviousShift:
    return PreviousShift(
        employee_id=_require_text(row["employee_id"], "employee_id"),
        date=_parse_date(row["date"]),
        post_id=_require_text(row["post_id"], "post_id"),
        shift_type=_require_text(row["shift_type"], "shift_type"),
    )


def load_problem_data(
    data_dir: Path | str, delimiter: str = ";"
) -> tuple[ProblemData, ValidationReport]:
    """Load all input CSVs.

    employees, shifts and qualifications are mandatory (no qualification means
    nobody can be assigned). availability, fixed assignments and history are
    optional; a missing availability file means everybody is NEUTRAL.

    Raises:
        DataLoadError: a mandatory file or required column is missing.
    """
    directory = Path(data_dir)
    report = ValidationReport()

    def table(name: str, required: list[str], mandatory: bool) -> pd.DataFrame | None:
        return _read_table(directory / name, delimiter, required, report, mandatory)

    employees_frame = table(EMPLOYEES_FILE, EMPLOYEE_COLUMNS, True)
    shifts_frame = table(SHIFTS_FILE, ["post_id", "post_name", "shift_type", "duration_hours", "active"], True)
    qualifications_frame = table(
        QUALIFICATIONS_FILE, ["employee_id", "post_id", "shift_type", "qualified"], True
    )
    availability_frame = table(AVAILABILITY_FILE, ["employee_id", "date", "availability"], False)
    fixed_frame = table(FIXED_FILE, ["employee_id", "date", "post_id", "action"], False)
    previous_frame = table(PREVIOUS_FILE, ["employee_id", "date", "post_id", "shift_type"], False)

    if availability_frame is None:
        report.warning(
            "AVAILABILITY_FILE_MISSING",
            f"Brak pliku {AVAILABILITY_FILE} - wszyscy pracownicy traktowani jako NEUTRAL.",
        )
    if previous_frame is None:
        report.warning(
            "PREVIOUS_FILE_MISSING",
            f"Brak pliku {PREVIOUS_FILE} - nie można kontrolować odpoczynku na granicy miesięcy.",
        )

    data = ProblemData(
        employees=_parse_rows(employees_frame, EMPLOYEES_FILE, _employee, report),
        posts=_parse_rows(shifts_frame, SHIFTS_FILE, _post, report),
        qualifications=_parse_rows(qualifications_frame, QUALIFICATIONS_FILE, _qualification, report),
        availability=_parse_rows(availability_frame, AVAILABILITY_FILE, _availability, report),
        fixed_assignments=_parse_rows(fixed_frame, FIXED_FILE, _fixed, report),
        previous_schedule=_parse_rows(previous_frame, PREVIOUS_FILE, _previous, report),
        previous_schedule_provided=previous_frame is not None,
    )
    return data, report
