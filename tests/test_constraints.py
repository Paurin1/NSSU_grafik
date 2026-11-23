from datetime import date, timedelta

from helpers import day, fix, forbid, make_data, make_settings, unavailable
from ortools.sat.python import cp_model
from src.constraints import create_variables
from src.models import PreviousShift, Qualification
from src.optimizer import SolveResult, build_model, solve
from src.preprocessing import build_context, compute_candidates


def test_no_variables_for_disallowed_combinations():
    data = make_data()
    data.qualifications = [
        Qualification("E1", "A", "16", False) if (q.employee_id, q.post_id) == ("E1", "A") else q
        for q in data.qualifications
    ]
    data.availability = [unavailable("E2", 5)]
    data.fixed_assignments = [forbid("E3", 6, "B")]
    ctx = build_context(data, make_settings())
    _, mv, _ = build_model(ctx)
    assert not any(e == "E1" and p == "A" for e, _, p in mv.x)
    assert not any(e == "E2" and d == day(5) for e, d, _ in mv.x)
    assert ("E3", day(6), "B") not in mv.x
    assert ("E3", day(6), "A") in mv.x


def test_inactive_employee_and_post_get_no_variables():
    data = make_data()
    data.employees[0] = type(data.employees[0])("E1", "x", False)
    ctx = build_context(data, make_settings())
    assert "E1" not in {e for e, _, _ in build_model(ctx)[1].x}


def test_candidates_cover_each_slot_once_in_model():
    ctx = build_context(make_data(), make_settings())
    candidates = compute_candidates(ctx)
    assert len(candidates) == 28 * 2
    model = cp_model.CpModel()
    assert len(create_variables(model, candidates).x) == sum(map(len, candidates.values()))


def test_solution_is_complete_one_per_day_and_respects_rest():
    data = make_data()
    result = solve(data, make_settings(solver={"time_limit_seconds": 10, "workers": 1}), with_objective=False)
    assert result.has_solution
    posts = {"A": "16", "B": "5"}
    for d in range(1, 29):
        for post in posts:
            assert (day(d), post) in result.assignments
        assert len({result.assignments[(day(d), p)] for p in posts}) == 2
    for (d, post), employee in result.assignments.items():
        if posts[post] == "16":
            assert employee not in {e for (dd, _), e in result.assignments.items() if dd == d + timedelta(days=1)}


def test_unavailable_and_unqualified_never_assigned():
    data = make_data()
    data.availability = [unavailable("E1", d) for d in range(1, 15)]
    data.qualifications = [
        Qualification("E2", "A", "16", False) if (q.employee_id, q.post_id) == ("E2", "A") else q
        for q in data.qualifications
    ]
    result = solve(data, make_settings(solver={"time_limit_seconds": 10, "workers": 1}), with_objective=False)
    assert result.has_solution
    for (d, post), employee in result.assignments.items():
        assert not (employee == "E1" and d.day <= 14)
        assert not (employee == "E2" and post == "A")


def test_history_16h_duty_blocks_first_day_of_month():
    data = make_data(history=False)
    data.previous_schedule = [PreviousShift(e, date(2026, 1, 31), "A", "16") for e in ("E1", "E2")]
    result = solve(data, make_settings(solver={"time_limit_seconds": 10, "workers": 1}), with_objective=False)
    assert result.has_solution
    assert {result.assignments[(day(1), p)] for p in ("A", "B")} <= {"E3", "E4"}


def test_history_5h_duty_does_not_block():
    data = make_data(history=False)
    data.previous_schedule = [PreviousShift(e, date(2026, 1, 31), "B", "5") for e in ("E3", "E4")]
    data.availability = [unavailable("E1", 1), unavailable("E2", 1)]
    assert solve(data, make_settings(solver={"time_limit_seconds": 10, "workers": 1}), with_objective=False).has_solution


def test_next_month_fix_blocks_long_duty_on_last_day():
    data = make_data()
    data.fixed_assignments = [fix("E1", 28, "B")]
    from dataclasses import replace

    data.fixed_assignments.append(replace(fix("E1", 1, "A"), date=date(2026, 3, 1)))
    result = solve(data, make_settings(solver={"time_limit_seconds": 10, "workers": 1}), with_objective=False)
    assert result.assignments[(day(28), "B")] == "E1"
    assert result.assignments[(day(28), "A")] != "E1"


def test_rest_induced_infeasibility_detected_by_solver():
    data = make_data(employee_ids=("E1", "E2"), posts=(("A", "16", 16), ("C", "16", 16)), history=False)
    result = solve(data, make_settings(solver={"time_limit_seconds": 10, "workers": 1}), with_objective=False)
    assert result.status == "INFEASIBLE" and not result.has_solution and not result.assignments


def test_feasible_is_not_treated_as_optimal():
    feasible = SolveResult("FEASIBLE", 1.0, {(day(1), "A"): "E1"})
    optimal = SolveResult("OPTIMAL", 1.0, {(day(1), "A"): "E1"})
    assert feasible.has_solution and not feasible.is_optimal
    assert optimal.has_solution and optimal.is_optimal
