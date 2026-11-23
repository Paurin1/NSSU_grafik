from dataclasses import replace
from datetime import date

from helpers import day, fix, forbid, make_data, make_settings, unavailable
from src.loader import load_problem_data
from src.models import (
    AvailabilityEntry,
    AvailabilityKind,
    Employee,
    PreviousShift,
    Qualification,
)
from src.validation import validate_problem


def run(data, **settings):
    return validate_problem(data, make_settings(**settings))


def test_clean_dataset_passes():
    report = run(make_data())
    assert report.ok and not report.warnings


def test_demo_dataset_is_valid():
    from src.config import load_settings

    data, _ = load_problem_data("data")
    report = validate_problem(data, load_settings("config/settings.yaml"))
    assert report.ok, report.format()


def test_duplicate_availability_is_an_error():
    data = make_data()
    data.availability = [
        AvailabilityEntry("E1", day(3), AvailabilityKind.NEUTRAL),
        AvailabilityEntry("E1", day(3), AvailabilityKind.UNAVAILABLE),
    ]
    assert "AVAILABILITY_DUPLICATE" in run(data).codes()


def test_duplicate_employee_and_post_ids():
    data = make_data()
    data.employees.append(replace(data.employees[0]))
    data.posts.append(replace(data.posts[0]))
    assert {"EMPLOYEE_DUPLICATE", "POST_DUPLICATE"} <= run(data).codes()


def test_unknown_references_are_errors():
    data = make_data()
    data.availability = [unavailable("X9", 3)]
    data.fixed_assignments = [fix("E1", 3, "Z")]
    data.qualifications.append(Qualification("X9", "A", "16", True))
    assert {"UNKNOWN_EMPLOYEE", "UNKNOWN_POST"} <= run(data).codes()


def test_qualification_shift_type_must_match_post():
    data = make_data()
    data.qualifications[0] = Qualification("E1", "A", "5", True)
    assert "QUALIFICATION_TYPE_MISMATCH" in run(data).codes()


def test_dates_outside_month():
    data = make_data()
    data.fixed_assignments = [replace(fix("E1", 1, "A"), date=date(2026, 4, 1))]
    data.availability = [AvailabilityEntry("E1", date(2026, 1, 5), AvailabilityKind.NEUTRAL)]
    data.previous_schedule.append(PreviousShift("E1", day(2), "A", "16"))
    codes = run(data).codes()
    assert {"FIXED_OUT_OF_MONTH", "AVAILABILITY_OUT_OF_MONTH", "PREVIOUS_NOT_BEFORE_MONTH"} <= codes


def test_fix_and_forbid_on_same_slot_conflict_with_readable_message():
    data = make_data()
    data.fixed_assignments = [fix("E1", 5, "A"), forbid("E1", 5, "A")]
    report = run(data)
    assert "FIX_FORBID_CONFLICT" in report.codes()
    assert "jednocześnie FIX i FORBID" in report.format()


def test_fix_against_unavailability_or_missing_qualification():
    data = make_data()
    data.availability = [unavailable("E1", 5)]
    data.fixed_assignments = [fix("E1", 5, "A")]
    data.qualifications[2] = Qualification("E2", "A", "16", False)
    data.fixed_assignments.append(fix("E2", 6, "A"))
    report = run(data)
    messages = " ".join(i.message for i in report.errors)
    assert "FIX_NOT_ALLOWED" in report.codes()
    assert "UNAVAILABLE" in messages and "brak kwalifikacji" in messages


def test_conflicting_fixes():
    data = make_data()
    data.fixed_assignments = [
        fix("E1", 5, "A"),
        fix("E2", 5, "A"),  # two people on one post
        fix("E3", 7, "A"),
        fix("E3", 7, "B"),  # one person on two posts
        fix("E2", 9, "A"),
        fix("E2", 10, "B"),  # duty on the day after a 16 h duty
    ]
    assert {"FIX_SLOT_CONFLICT", "FIX_EMPLOYEE_DAY_CONFLICT", "FIX_REST_CONFLICT"} <= run(data).codes()


def test_history_rest_makes_fix_on_first_day_impossible():
    data = make_data(history=False)
    data.previous_schedule = [PreviousShift("E1", date(2026, 1, 31), "A", "16")]
    data.fixed_assignments = [fix("E1", 1, "B")]
    report = run(data)
    assert "FIX_NOT_ALLOWED" in report.codes()
    assert "odpoczynek po dyżurze z 2026-01-31" in report.format()


def test_slot_without_candidates():
    data = make_data()
    data.qualifications = [q for q in data.qualifications if q.post_id != "B"]
    assert "NO_CANDIDATE" in run(data).codes()


def test_not_enough_distinct_people_in_a_day():
    data = make_data(employee_ids=("E1", "E2"), posts=(("A", "16", 16), ("B", "5", 5), ("C", "5", 5)))
    report = run(data)
    assert "INSUFFICIENT_STAFF" in report.codes()
    assert "maksymalnie 2 z 3" in report.format()


def test_unavailability_reduces_staffing_on_that_day_only():
    data = make_data(employee_ids=("E1", "E2", "E3"))
    data.availability = [unavailable("E1", 4), unavailable("E2", 4)]
    report = run(data)
    assert "INSUFFICIENT_STAFF" in report.codes()
    assert all("2026-02-04" in i.message for i in report.errors)


def test_inconsistent_limits():
    data = make_data()
    data.employees[0] = replace(data.employees[0], min_shifts=5, max_shifts=3)
    assert "LIMIT_INCONSISTENT" in run(data).codes()


def test_unreachable_limit():
    data = make_data()
    data.employees[1] = replace(data.employees[1], min_long_shifts=20)  # at most 14 with 1 rest day
    assert "LIMIT_UNREACHABLE" in run(data).codes()


def test_limit_sums_versus_slots():
    data = make_data()
    data.employees = [replace(e, min_shifts=20) for e in data.employees]  # 80 > 56 slots
    assert "LIMIT_MIN_SUM_EXCEEDS_SLOTS" in run(data).codes()

    data = make_data()
    data.employees = [replace(e, max_shifts=10) for e in data.employees]  # 40 < 56 slots
    assert "LIMIT_MAX_SUM_BELOW_SLOTS" in run(data).codes()


def test_unset_max_limits_do_not_trigger_max_sum_error():
    data = make_data()
    data.employees[0] = replace(data.employees[0], max_shifts=1)
    assert "LIMIT_MAX_SUM_BELOW_SLOTS" not in run(data).codes()


def test_history_warnings():
    assert "HISTORY_EMPTY" in run(make_data(history=False)).codes()
    data = make_data(history=False)
    data.previous_schedule = [PreviousShift("E1", date(2026, 1, 10), "A", "16")]
    assert "HISTORY_GAP" in run(data).codes()


def test_target_hours_mismatch_is_only_a_warning():
    data = make_data()
    data.employees = [replace(e, target_hours=100) for e in data.employees]
    report = run(data)
    assert report.ok and "TARGET_HOURS_MISMATCH" in report.codes()


def test_inactive_employees_are_ignored_in_staffing():
    posts = (("A", "16", 16), ("B", "5", 5), ("C", "5", 5))

    def with_inactive(employee_ids):
        data = make_data(employee_ids=employee_ids, posts=posts)
        data.employees.append(Employee("E9", "Inactive", False, 0))
        data.qualifications.extend(Qualification("E9", p, t, True) for p, t, _ in posts)
        return data

    assert run(with_inactive(("E1", "E2", "E3"))).ok
    assert "INSUFFICIENT_STAFF" in run(with_inactive(("E1", "E2"))).codes()


def test_next_month_fix_is_accepted_and_blocks_long_shift_on_last_day():
    data = make_data()
    data.fixed_assignments = [replace(fix("E1", 1, "A"), date=date(2026, 3, 1))]
    report = run(data)
    assert report.ok and not report.warnings

    from src.preprocessing import build_context, exclusion_reasons

    ctx = build_context(data, make_settings())
    assert exclusion_reasons(ctx, "E1", day(28), "A")  # 16 h duty before a FIX next day
    assert not exclusion_reasons(ctx, "E1", day(28), "B")  # 5 h duty needs no rest
    assert not exclusion_reasons(ctx, "E1", day(27), "A")


def test_fix_conflicting_with_next_month_fix_and_next_month_forbid_warning():
    data = make_data()
    data.fixed_assignments = [
        replace(fix("E1", 1, "A"), date=date(2026, 3, 1)),
        fix("E1", 28, "A"),
        replace(forbid("E2", 1, "A"), date=date(2026, 3, 2)),
    ]
    report = run(data)
    assert "FIX_NOT_ALLOWED" in report.codes()
    assert "NEXT_MONTH_FORBID_IGNORED" in report.codes()
