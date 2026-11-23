from datetime import date

import pytest

from helpers import write_file, write_minimal_dataset
from src.calendar_utils import month_days
from src.config import ConfigError, load_settings
from src.loader import load_problem_data
from src.models import AvailabilityKind, DataLoadError


def test_minimal_dataset_loads_and_optional_values_stay_none(tmp_path):
    write_minimal_dataset(tmp_path)
    data, report = load_problem_data(tmp_path)
    assert report.ok
    assert [e.employee_id for e in data.employees] == ["E1", "E2"]
    assert data.employees[1].target_hours is None
    assert data.employees[0].min_shifts is None and data.employees[0].max_long_shifts is None
    assert data.posts[0].duration_hours == 16
    assert {"AVAILABILITY_FILE_MISSING", "PREVIOUS_FILE_MISSING"} <= report.codes()
    assert data.availability == [] and not data.previous_schedule_provided


def test_missing_availability_entries_are_not_loaded_as_unavailable(tmp_path):
    write_minimal_dataset(tmp_path)
    write_file(tmp_path, "availability.csv", "employee_id;date;availability\nE1;2026-02-03;PREFER_16\n")
    data, _ = load_problem_data(tmp_path)
    assert [a.availability for a in data.availability] == [AvailabilityKind.PREFER_16]


def test_missing_mandatory_file_raises(tmp_path):
    write_minimal_dataset(tmp_path)
    (tmp_path / "shifts.csv").unlink()
    with pytest.raises(DataLoadError) as excinfo:
        load_problem_data(tmp_path)
    assert "shifts.csv" in str(excinfo.value)


def test_missing_required_column_raises(tmp_path):
    write_minimal_dataset(tmp_path)
    write_file(tmp_path, "employees.csv", "employee_id;name;active\nE1;Jan;1\n")
    with pytest.raises(DataLoadError) as excinfo:
        load_problem_data(tmp_path)
    assert "target_hours" in str(excinfo.value)


def test_invalid_rows_are_reported_with_line_numbers_and_skipped(tmp_path):
    write_minimal_dataset(tmp_path)
    write_file(
        tmp_path,
        "availability.csv",
        "employee_id;date;availability\n"
        "E1;2026-02-03;MAYBE\n"
        "E1;2026-02-30;UNAVAILABLE\n"
        "E1;2026-02-04;UNAVAILABLE\n",
    )
    write_file(
        tmp_path,
        "employees.csv",
        "employee_id;name;active;target_hours\nE1;Jan;yes;40\nE2;Anna;1;abc\nE3;Ola;1;-5\n",
    )
    data, report = load_problem_data(tmp_path)
    messages = [i.message for i in report.errors]
    assert len(data.availability) == 1 and not data.employees
    assert any("availability.csv, wiersz 2" in m and "MAYBE" in m for m in messages)
    assert any("availability.csv, wiersz 3" in m for m in messages)
    assert any("employees.csv, wiersz 2" in m for m in messages)
    assert any("employees.csv, wiersz 3" in m for m in messages)
    assert any("employees.csv, wiersz 4" in m for m in messages)


def test_duplicate_rows_are_preserved_for_validation(tmp_path):
    write_minimal_dataset(tmp_path)
    write_file(
        tmp_path,
        "availability.csv",
        "employee_id;date;availability\nE1;2026-02-03;NEUTRAL\nE1;2026-02-03;UNAVAILABLE\n",
    )
    data, _ = load_problem_data(tmp_path)
    assert len(data.availability) == 2


def test_demo_dataset_matches_specification():
    data, report = load_problem_data("data")
    assert report.ok
    active = [e for e in data.employees if e.active]
    assert len(active) > 50
    long_posts = [p for p in data.posts if p.active and p.shift_type == "16"]
    short_posts = [p for p in data.posts if p.active and p.shift_type == "5"]
    assert (len(long_posts), len(short_posts)) == (5, 4)


def test_settings_load_and_overrides():
    settings = load_settings("config/settings.yaml", year=2028, month=2, time_limit=5)
    assert (settings.year, settings.month, settings.solver.time_limit_seconds) == (2028, 2, 5)
    assert settings.weights.hours_balance == 10 and settings.weights.weekend_balance == 4
    assert len(month_days(2028, 2)) == 29 and len(month_days(2026, 2)) == 28
    assert date(2026, 12, 25) in settings.weekends.holidays


def test_invalid_settings_are_rejected(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("year: 2026\nmonth: 13\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_settings(bad)
    typo = tmp_path / "typo.yaml"
    typo.write_text("year: 2026\nmonth: 1\nweigths: {}\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_settings(typo)
    with pytest.raises(ConfigError):
        load_settings(tmp_path / "absent.yaml")
