"""File export: CSV, XLSX and text report. Refuses to overwrite silently."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

from .calendar_utils import month_days
from .config import Settings
from .models import ProblemData, ValidationReport
from .reports import ScheduleReports

CSV_FILE = "schedule.csv"
XLSX_FILE = "schedule.xlsx"
REPORT_FILE = "optimization_report.txt"
OUTPUT_FILES = (CSV_FILE, XLSX_FILE, REPORT_FILE)
CSV_DELIMITER = ";"
CALENDAR_CELL_FILL = PatternFill("solid", fgColor="DDEBF7")


class OutputExistsError(Exception):
    """Raised when result files already exist and overwriting was not requested."""


def existing_outputs(output_dir: Path) -> list[Path]:
    return [output_dir / name for name in OUTPUT_FILES if (output_dir / name).exists()]


def calendar_table(data: ProblemData, settings: Settings, reports: ScheduleReports) -> pd.DataFrame:
    """Rows = days, columns = posts, cells = employee names."""
    posts = [p for p in data.posts if p.active]
    frame = pd.DataFrame(index=[d.isoformat() for d in month_days(settings.year, settings.month)])
    pivot = reports.schedule.pivot(index="date", columns="post_id", values="employee_name")
    for post in posts:
        frame[f"{post.post_name} ({post.shift_type} h)"] = pivot.get(post.post_id)
    frame.index.name = "date"
    frame.insert(0, "weekday", [
        reports.schedule.loc[reports.schedule.date == d, "weekday"].iloc[0]
        if (reports.schedule.date == d).any() else ""
        for d in frame.index
    ])
    return frame.reset_index()


def export_all(
    output_dir: Path,
    data: ProblemData,
    settings: Settings,
    reports: ScheduleReports,
    validation: ValidationReport,
    report_text: str,
    overwrite: bool = False,
) -> list[Path]:
    """Write schedule.csv, schedule.xlsx and optimization_report.txt."""
    output_dir.mkdir(parents=True, exist_ok=True)
    existing = existing_outputs(output_dir)
    if existing and not overwrite:
        names = ", ".join(p.name for p in existing)
        raise OutputExistsError(f"Pliki wynikowe już istnieją ({names}). Użyj --overwrite, aby je nadpisać.")

    csv_path = output_dir / CSV_FILE
    reports.schedule.to_csv(csv_path, sep=CSV_DELIMITER, index=False, encoding="utf-8-sig")

    xlsx_path = output_dir / XLSX_FILE
    validation_df = pd.DataFrame(
        [[i.severity.value, i.code, i.message] for i in validation.errors + validation.warnings],
        columns=["severity", "code", "message"],
    )
    if validation_df.empty:
        validation_df = pd.DataFrame([["OK", "", "Brak błędów i ostrzeżeń"]], columns=validation_df.columns)
    sheets = {
        "Schedule": calendar_table(data, settings, reports),
        "Employees": reports.employees,
        "Statistics": reports.statistics,
        "Validation": validation_df,
        "Preferences": reports.preferences,
    }
    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
        for name, frame in sheets.items():
            frame.to_excel(writer, sheet_name=name, index=False)
            _format_sheet(writer.sheets[name], frame)

    report_path = output_dir / REPORT_FILE
    report_path.write_text(report_text, encoding="utf-8")
    return [csv_path, xlsx_path, report_path]


def _format_sheet(sheet, frame: pd.DataFrame) -> None:
    for cell in sheet[1]:
        cell.font = Font(bold=True)
        cell.fill = CALENDAR_CELL_FILL
    for index, column in enumerate(frame.columns, start=1):
        longest = max([len(str(column))] + [len(str(v)) for v in frame[column]])
        sheet.column_dimensions[get_column_letter(index)].width = min(60, longest + 2)
    sheet.freeze_panes = "A2"
