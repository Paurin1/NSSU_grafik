from datetime import date

from helpers import day, fix, forbid, make_data, make_settings, unavailable
from dataclasses import replace
from src.models import PreviousShift, Qualification
from src.schedule_validator import validate_schedule


def good_schedule(days=range(1, 29)):
    """E1/E2 alternate on post A (16 h, rest day between), E3/E4 on B (5 h)."""
    out = []
    for d in days:
        out.append((day(d), "A", "E1" if d % 2 else "E2"))
        out.append((day(d), "B", "E3" if d % 2 else "E4"))
    return out


def check(data, schedule, **settings):
    return validate_schedule(data, make_settings(**settings), schedule)


def test_valid_schedule_has_no_errors():
    report = check(make_data(history=False), good_schedule())
    assert report.ok, report.format()


def test_missing_slot_and_duplicate_assignment():
    schedule = good_schedule()[2:]
    schedule.append(schedule[0])
    codes = check(make_data(), schedule).codes()
    assert {"UNSTAFFED", "DUPLICATE_ASSIGNMENT"} <= codes


def test_two_shifts_same_day():
    schedule = [(d, p, "E1") if (d, p) == (day(3), "B") else (d, p, e) for d, p, e in good_schedule()]
    assert "MULTIPLE_SHIFTS_PER_DAY" in check(make_data(), schedule).codes()


def test_unavailable_and_unqualified():
    data = make_data()
    data.availability = [unavailable("E1", 1)]
    data.qualifications = [
        Qualification("E3", "B", "5", False) if (q.employee_id, q.post_id) == ("E3", "B") else q
        for q in data.qualifications
    ]
    assert {"UNAVAILABLE", "NOT_QUALIFIED"} <= check(data, good_schedule()).codes()


def test_rest_after_16h_inside_month_and_across_boundary():
    schedule = [(d, p, "E1") if (d, p) in {(day(2), "A")} else (d, p, e) for d, p, e in good_schedule()]
    schedule = [(d, p, e) for d, p, e in schedule if not (d == day(2) and p == "A")] + [(day(2), "A", "E1")]
    assert "REST_VIOLATION" in check(make_data(), schedule).codes()

    data = make_data(history=False)
    data.previous_schedule = [PreviousShift("E1", date(2026, 1, 31), "A", "16")]
    assert "REST_VIOLATION" in check(data, good_schedule()).codes()  # E1 works Feb 1


def test_short_shifts_on_consecutive_days_are_not_an_error():
    schedule = [(d, p, "E3") if p == "B" else (d, p, e) for d, p, e in good_schedule()]
    assert "REST_VIOLATION" not in check(make_data(), schedule).codes()


def test_manual_locks():
    data = make_data()
    data.fixed_assignments = [fix("E4", 1, "A"), forbid("E1", 1, "A")]
    assert {"FIX_VIOLATED", "FORBID_VIOLATED"} <= check(data, good_schedule()).codes()


def test_limits_and_unknown_references():
    data = make_data()
    data.employees[0] = replace(data.employees[0], max_shifts=3)
    data.employees[2] = replace(data.employees[2], min_short_shifts=100)
    schedule = good_schedule() + [(day(1), "Z", "E1"), (date(2026, 3, 1), "A", "E1"), (day(1), "A", "X")]
    codes = check(data, schedule).codes()
    assert {"LIMIT_ABOVE_MAX", "LIMIT_BELOW_MIN", "UNKNOWN_POST", "DATE_OUT_OF_MONTH", "UNKNOWN_EMPLOYEE"} <= codes


def test_history_warning_when_missing():
    assert "HISTORY_EMPTY" in check(make_data(history=False), good_schedule()).codes()
