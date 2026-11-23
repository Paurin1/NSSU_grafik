import pandas as pd
import pytest

import main
from helpers import make_data, make_settings
from src.exporter import OutputExistsError, export_all
from src.models import ValidationReport
from src.optimizer import solve
from src.reports import build_reports, format_optimization_report


def solved(**kwargs):
    data = make_data(history=False)
    settings = make_settings(solver={"time_limit_seconds": 10, "workers": 1})
    return data, settings, solve(data, settings)


def test_reports_tables_are_consistent():
    data, settings, result = solved()
    reports = build_reports(data, settings, result)
    assert len(reports.schedule) == 28 * 2
    assert list(reports.schedule.columns)[:3] == ["date", "weekday", "post_id"]
    assert reports.employees.total_hours.sum() == 28 * (16 + 5)
    assert (reports.employees.shifts_16h + reports.employees.shifts_5h == reports.employees.total_shifts).all()
    assert (reports.employees.deviation_hours == reports.employees.total_hours - reports.employees.target_hours).all()


def test_text_report_flags_feasible_and_lists_sections():
    data, settings, result = solved()
    result.status = "FEASIBLE"
    text = format_optimization_report(settings, result, build_reports(data, settings, result), ValidationReport(), ValidationReport())
    for fragment in ("Status solvera: FEASIBLE", "optymalność nie została udowodniona", "Czas obliczeń", "Ostrzeżenia", "Błędy"):
        assert fragment in text


def test_export_creates_files_and_refuses_silent_overwrite(tmp_path):
    data, settings, result = solved()
    reports = build_reports(data, settings, result)
    args = (tmp_path, data, settings, reports, ValidationReport(), "x")
    paths = export_all(*args)
    assert {p.name for p in paths} == {"schedule.csv", "schedule.xlsx", "optimization_report.txt"}
    sheets = pd.read_excel(tmp_path / "schedule.xlsx", sheet_name=None)
    assert list(sheets) == ["Schedule", "Employees", "Statistics", "Validation", "Preferences"]
    assert len(sheets["Schedule"]) == 28
    with pytest.raises(OutputExistsError):
        export_all(*args)
    export_all(*args, overwrite=True)


def test_cli_end_to_end_on_demo_data(tmp_path):
    argv = ["--month", "12", "--year", "2026", "--time-limit", "5", "--output-dir", str(tmp_path)]
    assert main.run(main.parse_args(argv)) == main.EXIT_OK
    assert (tmp_path / "schedule.csv").exists()
    assert main.run(main.parse_args(argv)) == main.EXIT_OUTPUT_EXISTS
    assert main.run(main.parse_args(argv + ["--overwrite"])) == main.EXIT_OK
