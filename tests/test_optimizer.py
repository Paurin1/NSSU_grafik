from helpers import make_data, make_settings
from src.config import load_settings
from src.loader import load_problem_data
from src.optimizer import solve


def test_default_weights_produce_valid_schedule_with_penalty_breakdown():
    result = solve(make_data(history=False), make_settings(solver={"time_limit_seconds": 20, "workers": 1}))
    assert result.has_solution and result.objective_value is not None
    assert {"hours_balance", "shift_count_balance", "preferences", "consecutive_5h", "weekend_balance"} <= set(result.penalties)
    assert all(v >= 0 for v in result.penalties.values())


def test_same_seed_same_result_with_one_worker():
    settings = make_settings(solver={"time_limit_seconds": 20, "workers": 1, "random_seed": 7})
    assert solve(make_data(history=False), settings).assignments == solve(make_data(history=False), settings).assignments


def test_infeasible_limits_give_infeasible_status():
    from dataclasses import replace

    data = make_data()
    data.employees = [replace(e, max_shifts=1) for e in data.employees]
    result = solve(data, make_settings(solver={"time_limit_seconds": 10, "workers": 1}))
    assert result.status == "INFEASIBLE" and not result.assignments


def test_demo_dataset_solves_within_limit():
    data, _ = load_problem_data("data")
    result = solve(data, load_settings("config/settings.yaml", time_limit=10))
    assert result.has_solution and len(result.assignments) == 31 * 9
