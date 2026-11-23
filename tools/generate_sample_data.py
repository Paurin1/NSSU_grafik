"""Generates the demo CSV files in ``data/`` (fictional, deterministic).

Usage: python tools/generate_sample_data.py [output_dir]
"""

from __future__ import annotations

import csv
import random
import sys
from datetime import date, timedelta
from pathlib import Path

SEED = 2026
EMPLOYEE_COUNT = 56
TARGET_HOURS = 55
LONG_POSTS = [f"P{i}" for i in range(1, 6)]
SHORT_POSTS = [f"P{i}" for i in range(6, 10)]
YEAR, MONTH = 2026, 12
HISTORY_DAYS = 3
DELIMITER = ";"


def write_csv(path: Path, header: list[str], rows: list[list[object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, delimiter=DELIMITER)
        writer.writerow(header)
        writer.writerows(rows)


def main(out_dir: Path) -> None:
    rng = random.Random(SEED)
    out_dir.mkdir(parents=True, exist_ok=True)
    ids = [f"E{i:03d}" for i in range(1, EMPLOYEE_COUNT + 1)]

    employees = []
    for number, eid in enumerate(ids, start=1):
        max_shifts = 10 if number % 9 == 0 else ""
        max_long = 4 if number % 11 == 0 else ""
        employees.append([eid, f"Pracownik {number:03d}", 1, TARGET_HOURS, "", max_shifts, "", max_long, "", ""])
    employees.append(["E999", "Pracownik nieaktywny", 0, 0, "", "", "", "", "", ""])
    write_csv(
        out_dir / "employees.csv",
        ["employee_id", "name", "active", "target_hours", "min_shifts", "max_shifts",
         "min_long_shifts", "max_long_shifts", "min_short_shifts", "max_short_shifts"],
        employees,
    )

    posts = [[p, f"Pion {p[1:]}", 16, 16, 1] for p in LONG_POSTS]
    posts += [[p, f"Pion {p[1:]}", 5, 5, 1] for p in SHORT_POSTS]
    write_csv(out_dir / "shifts.csv", ["post_id", "post_name", "shift_type", "duration_hours", "active"], posts)

    qualified_posts: dict[str, list[str]] = {}
    qualifications = []
    for number, eid in enumerate(ids, start=1):
        owned: list[str] = []
        if number % 4 != 3:
            owned += [p for p in LONG_POSTS if (number + int(p[1:])) % 3 != 0]
        if number % 3 != 0:
            owned += [p for p in SHORT_POSTS if (number + int(p[1:])) % 4 != 0]
        qualified_posts[eid] = owned
        for post in LONG_POSTS + SHORT_POSTS:
            shift_type = 16 if post in LONG_POSTS else 5
            qualifications.append([eid, post, shift_type, 1 if post in owned else 0])
    write_csv(out_dir / "qualifications.csv", ["employee_id", "post_id", "shift_type", "qualified"], qualifications)

    first_day = date(YEAR, MONTH, 1)
    days = [first_day + timedelta(days=i) for i in range(31)]
    availability = []
    for eid in ids:
        chosen = rng.sample(days, rng.randint(2, 7))
        for index, day in enumerate(sorted(chosen)):
            owned = qualified_posts[eid]
            has_long = any(p in LONG_POSTS for p in owned)
            has_short = any(p in SHORT_POSTS for p in owned)
            if index < 2:
                kind = "UNAVAILABLE"
            elif has_long and (rng.random() < 0.5 or not has_short):
                kind = "PREFER_16"
            else:
                kind = "PREFER_5"
            availability.append([eid, day.isoformat(), kind])
    write_csv(out_dir / "availability.csv", ["employee_id", "date", "availability"], availability)

    unavailable = {(r[0], r[1]) for r in availability if r[2] == "UNAVAILABLE"}
    fix_day, forbid_day = date(YEAR, MONTH, 10), date(YEAR, MONTH, 11)
    fix_employee = next(e for e in ids if "P1" in qualified_posts[e] and (e, fix_day.isoformat()) not in unavailable)
    forbid_employee = next(e for e in ids if "P2" in qualified_posts[e])
    write_csv(
        out_dir / "fixed_assignments.csv",
        ["employee_id", "date", "post_id", "action"],
        [[fix_employee, fix_day.isoformat(), "P1", "FIX"], [forbid_employee, forbid_day.isoformat(), "P2", "FORBID"]],
    )

    history = []
    for offset in range(1, HISTORY_DAYS + 1):
        day = first_day - timedelta(days=offset)
        used: set[str] = set()
        for post in LONG_POSTS + SHORT_POSTS:
            pool = [e for e in ids if post in qualified_posts[e] and e not in used]
            pick = rng.choice(pool)
            used.add(pick)
            history.append([pick, day.isoformat(), post, 16 if post in LONG_POSTS else 5])
    write_csv(out_dir / "previous_schedule.csv", ["employee_id", "date", "post_id", "shift_type"], history)


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data"))
