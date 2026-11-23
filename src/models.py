"""Domain models shared by all modules (no solver or I/O logic here)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum


class AvailabilityKind(str, Enum):
    """Allowed values of the ``availability`` column."""

    UNAVAILABLE = "UNAVAILABLE"
    PREFER_16 = "PREFER_16"
    PREFER_5 = "PREFER_5"
    NEUTRAL = "NEUTRAL"


class FixedAction(str, Enum):
    """Allowed values of the ``action`` column in fixed assignments."""

    FIX = "FIX"
    FORBID = "FORBID"


class Severity(str, Enum):
    """Severity of a validation finding."""

    ERROR = "ERROR"
    WARNING = "WARNING"


@dataclass(frozen=True)
class Employee:
    """A person who can be assigned to duties. Optional limits are hard only when set."""

    employee_id: str
    name: str
    active: bool
    target_hours: int | None = None
    min_shifts: int | None = None
    max_shifts: int | None = None
    min_long_shifts: int | None = None
    max_long_shifts: int | None = None
    min_short_shifts: int | None = None
    max_short_shifts: int | None = None


@dataclass(frozen=True)
class Post:
    """A post ("pion") that must be staffed by exactly one person every day."""

    post_id: str
    post_name: str
    shift_type: str
    duration_hours: int
    active: bool


@dataclass(frozen=True)
class Qualification:
    """Permission of an employee to work a given post with a given shift type."""

    employee_id: str
    post_id: str
    shift_type: str
    qualified: bool


@dataclass(frozen=True)
class AvailabilityEntry:
    """One row of the availability table; a missing row means NEUTRAL."""

    employee_id: str
    date: date
    availability: AvailabilityKind


@dataclass(frozen=True)
class FixedAssignment:
    """Manual lock: FIX (mandatory) or FORBID (prohibited) for employee/date/post."""

    employee_id: str
    date: date
    post_id: str
    action: FixedAction


@dataclass(frozen=True)
class PreviousShift:
    """A duty from history, used for rest checks across month boundaries."""

    employee_id: str
    date: date
    post_id: str
    shift_type: str


@dataclass
class ProblemData:
    """All raw input records, exactly as loaded (duplicates are preserved)."""

    employees: list[Employee] = field(default_factory=list)
    posts: list[Post] = field(default_factory=list)
    qualifications: list[Qualification] = field(default_factory=list)
    availability: list[AvailabilityEntry] = field(default_factory=list)
    fixed_assignments: list[FixedAssignment] = field(default_factory=list)
    previous_schedule: list[PreviousShift] = field(default_factory=list)
    previous_schedule_provided: bool = False


@dataclass(frozen=True)
class ValidationIssue:
    """A single finding; ``message`` is user-facing (Polish)."""

    severity: Severity
    code: str
    message: str


@dataclass
class ValidationReport:
    """Collection of findings produced by loader, validators or the solver."""

    issues: list[ValidationIssue] = field(default_factory=list)

    def add(self, severity: Severity, code: str, message: str) -> None:
        self.issues.append(ValidationIssue(severity, code, message))

    def error(self, code: str, message: str) -> None:
        self.add(Severity.ERROR, code, message)

    def warning(self, code: str, message: str) -> None:
        self.add(Severity.WARNING, code, message)

    def extend(self, other: ValidationReport) -> None:
        self.issues.extend(other.issues)

    @property
    def errors(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity is Severity.ERROR]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity is Severity.WARNING]

    @property
    def ok(self) -> bool:
        """True when there are no hard errors (warnings are allowed)."""
        return not self.errors

    def codes(self) -> set[str]:
        return {i.code for i in self.issues}

    def format(self) -> str:
        """Human-readable multi-line text, errors first."""
        ordered = self.errors + self.warnings
        return "\n".join(
            f"[{'BŁĄD' if i.severity is Severity.ERROR else 'OSTRZEŻENIE'}] {i.message}"
            for i in ordered
        )


class DataLoadError(Exception):
    """Raised when input cannot be read at all (missing file or required columns)."""

    def __init__(self, report: ValidationReport) -> None:
        super().__init__(report.format())
        self.report = report
