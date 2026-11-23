from dataclasses import replace
from datetime import date

from helpers import day, fix, forbid, make_data, make_settings
from src.models import AvailabilityEntry, AvailabilityKind
from src.objective import CONSECUTIVE, HOURS, PREFERENCES, WEEKENDS, day_weight
from src.optimizer import solve
from src.preprocessing import build_context

ALL_ZERO = dict.fromkeys(
    ["hours_balance", "shift_count_balance", "preferences", "consecutive_5h", "weekend_balance",
     "long_shift_balance", "short_shift_balance"], 0)


def run(data, weights=None, **extra):
    settings = make_settings(
        solver={"time_limit_seconds": 20, "workers": 1},
        weights={**ALL_ZERO, **(weights or {})},
        **extra,
    )
    return solve(data, settings)


def test_hours_balance_reaches_known_perfect_split():
    # 588 required hours / 4 people = 147 h each (7 x 16 h + 7 x 5 h) is attainable.
    data = make_data(history=False)
    data.employees = [replace(e, target_hours=147) for e in data.employees]
    result = run(data, {"hours_balance": 1})
    assert result.is_optimal and result.penalties[HOURS] == 0
    hours = {}
    for (d, post), e in result.assignments.items():
        hours[e] = hours.get(e, 0) + (16 if post == "A" else 5)
    assert set(hours.values()) == {147}


def test_missing_target_hours_falls_back_to_equal_share():
    ctx = build_context(make_data(history=False), make_settings())
    from src.objective import hours_targets

    assert set(hours_targets(ctx).values()) == {147}


def test_preferences_are_followed_when_free():
    data = make_data(history=False)
    data.availability = [
        AvailabilityEntry("E1", day(d), AvailabilityKind.PREFER_5) for d in range(1, 29)
    ] + [AvailabilityEntry("E2", day(d), AvailabilityKind.PREFER_16) for d in range(1, 29)]
    result = run(data, {"preferences": 1})
    assert result.is_optimal and result.penalties[PREFERENCES] == 0
    assert not any(e == "E1" and p == "A" for (_, p), e in result.assignments.items())
    assert not any(e == "E2" and p == "B" for (_, p), e in result.assignments.items())


def test_preference_is_not_a_guarantee():
    data = make_data(employee_ids=("E1", "E2", "E3"), history=False)
    data.availability = [AvailabilityEntry("E1", day(3), AvailabilityKind.PREFER_5)]
    data.fixed_assignments = [fix("E1", 3, "A")]
    result = run(data, {"preferences": 1})
    assert result.has_solution and result.assignments[(day(3), "A")] == "E1"
    assert result.penalties[PREFERENCES] == 1


def test_consecutive_short_shifts_are_possible_but_penalised():
    # Two people must cover two 5 h posts every day, so both work every day.
    data = make_data(employee_ids=("E1", "E2"), posts=(("B", "5", 5), ("C", "5", 5)), history=False)
    result = run(data, {"consecutive_5h": 1})
    assert result.is_optimal
    assert result.penalties[CONSECUTIVE] == 2 * 27


def test_consecutive_short_shift_across_month_boundary():
    data = make_data(employee_ids=("E1", "E2"), posts=(("B", "5", 5), ("C", "5", 5)), history=False)
    from src.models import PreviousShift

    data.previous_schedule = [PreviousShift("E1", date(2026, 1, 31), "B", "5")]
    result = run(data, {"consecutive_5h": 1})
    assert result.penalties[CONSECUTIVE] == 2 * 27 + 1


def test_consecutive_short_shifts_avoided_when_there_is_room():
    data = make_data(employee_ids=("E1", "E2", "E3", "E4"), posts=(("B", "5", 5), ("C", "5", 5)), history=False)
    result = run(data, {"consecutive_5h": 1})
    assert result.is_optimal and result.penalties[CONSECUTIVE] == 0


def test_weekends_are_spread_and_weights_distinguish_days():
    result = run(make_data(history=False), {"weekend_balance": 1})
    assert result.has_solution and result.penalties[WEEKENDS] <= 1
    ctx = build_context(
        make_data(),
        make_settings(weekends={"saturday_weight": 2, "sunday_weight": 3, "holiday_weight": 5, "holidays": [date(2026, 2, 4)]}),
    )
    assert day_weight(ctx, date(2026, 2, 7)) == 2
    assert day_weight(ctx, date(2026, 2, 8)) == 3
    assert day_weight(ctx, date(2026, 2, 4)) == 5
    assert day_weight(ctx, date(2026, 2, 5)) == 0


def test_manual_fix_and_forbid_are_respected_with_objective():
    data = make_data(history=False)
    data.fixed_assignments = [fix("E2", 10, "A"), forbid("E1", 11, "B"), forbid("E1", 11, "A")]
    result = solve(data, make_settings(solver={"time_limit_seconds": 10, "workers": 1}))
    assert result.has_solution
    assert result.assignments[(day(10), "A")] == "E2"
    assert result.assignments[(day(11), "A")] != "E1" and result.assignments[(day(11), "B")] != "E1"


def test_explicit_limits_are_hard_and_unset_limits_are_not():
    data = make_data(history=False)
    data.employees[0] = replace(data.employees[0], max_shifts=3)
    data.employees[1] = replace(data.employees[1], min_long_shifts=10, max_short_shifts=2)
    result = run(data, {"hours_balance": 1})
    counts = {}
    for (_, post), e in result.assignments.items():
        counts.setdefault(e, {"A": 0, "B": 0})[post] += 1
    assert sum(counts["E1"].values()) <= 3
    assert counts["E2"]["A"] >= 10 and counts["E2"]["B"] <= 2


def test_history_lowers_target_of_people_who_worked_more_before():
    from src.models import PreviousShift
    from src.objective import hours_targets

    data = make_data(history=False)
    data.previous_schedule = [PreviousShift("E1", date(2026, 1, d), "A", "16") for d in (5, 10, 15, 20)]
    ctx = build_context(data, make_settings())
    targets = hours_targets(ctx)
    assert targets["E1"] == 147 - 48 and targets["E2"] == 147 + 16
    assert sum(targets.values()) == 4 * 147  # zero-sum shift

    off = build_context(data, make_settings(balancing={"use_history": False}))
    assert set(hours_targets(off).values()) == {147}


def test_history_is_used_for_long_shift_and_weekend_balance():
    from src.models import PreviousShift
    from src.objective import history_counts, history_weekend_load

    data = make_data(history=False)
    data.previous_schedule = [
        PreviousShift("E1", date(2026, 1, 3), "A", "16"),  # Saturday
        PreviousShift("E1", date(2026, 1, 4), "B", "5"),  # Sunday
        PreviousShift("E2", date(2026, 1, 6), "A", "16"),
    ]
    ctx = build_context(data, make_settings())
    assert history_counts(ctx, "16") == {"E1": 1, "E2": 1, "E3": 0, "E4": 0}
    assert history_weekend_load(ctx) == {"E1": 2, "E2": 0, "E3": 0, "E4": 0}


def test_history_shifts_load_towards_others():
    from src.models import PreviousShift

    data = make_data(history=False)
    data.previous_schedule = [PreviousShift("E1", date(2026, 1, d), "A", "16") for d in (5, 10, 15, 20)]
    result = run(data, {"hours_balance": 1})
    assert result.has_solution
    hours = {}
    for (_, post), e in result.assignments.items():
        hours[e] = hours.get(e, 0) + (16 if post == "A" else 5)
    assert hours["E1"] < min(hours["E2"], hours["E3"], hours["E4"])
