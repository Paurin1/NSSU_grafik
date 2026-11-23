"""Command-line entry point: ``python main.py --year 2026 --month 12``."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from src.config import ConfigError, load_settings
from src.exporter import OutputExistsError, existing_outputs, export_all
from src.diagnostics import explain_infeasibility
from src.loader import load_problem_data
from src.models import DataLoadError, ValidationReport
from src.optimizer import solve
from src.reports import build_reports, format_optimization_report
from src.schedule_validator import validate_schedule
from src.validation import validate_problem

EXIT_OK, EXIT_INPUT_ERROR, EXIT_NO_SOLUTION, EXIT_INVALID_SCHEDULE, EXIT_OUTPUT_EXISTS = 0, 2, 3, 4, 5

log = logging.getLogger("dyzury")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Automatyczny grafik dyżurów (OR-Tools CP-SAT).")
    parser.add_argument("--year", type=int)
    parser.add_argument("--month", type=int)
    parser.add_argument("--config", default="config/settings.yaml")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--output-dir", default="output")
    parser.add_argument("--time-limit", type=int)
    parser.add_argument("--overwrite", action="store_true", help="nadpisz istniejące pliki wynikowe")
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(message)s")
    output_dir = Path(args.output_dir)
    if existing_outputs(output_dir) and not args.overwrite:
        log.error("Pliki wynikowe w %s już istnieją. Użyj --overwrite, aby je nadpisać.", output_dir)
        return EXIT_OUTPUT_EXISTS

    try:
        settings = load_settings(args.config, args.year, args.month, args.time_limit)
        data, input_report = load_problem_data(args.data_dir, settings.csv_delimiter)
    except (ConfigError, DataLoadError) as exc:
        log.error("%s", exc)
        return EXIT_INPUT_ERROR

    input_report.extend(validate_problem(data, settings))
    if not input_report.ok:
        log.error("Dane wejściowe zawierają błędy:\n%s", input_report.format())
        return EXIT_INPUT_ERROR
    for warning in input_report.warnings:
        log.warning("%s", warning.message)

    log.info("Uruchamiam solver (limit %s s)...", settings.solver.time_limit_seconds)
    result = solve(data, settings)
    log.info("Status solvera: %s (%.1f s)", result.status, result.wall_time_seconds)
    if not result.has_solution:
        log.error("Brak grafiku (status %s).", result.status)
        if result.status == "INFEASIBLE":
            for message in explain_infeasibility(data, settings):
                log.error("%s", message)
        return EXIT_NO_SOLUTION

    assignments = [(d, p, e) for (d, p), e in result.assignments.items()]
    validation = validate_schedule(data, settings, assignments)
    reports = build_reports(data, settings, result)
    text = format_optimization_report(settings, result, reports, validation, input_report)
    paths = export_all(output_dir, data, settings, reports, validation, text, overwrite=args.overwrite)
    for path in paths:
        log.info("Zapisano: %s", path)
    if not validation.ok:
        log.error("Grafik NIE może być zatwierdzony:\n%s", ValidationReport(validation.errors).format())
        return EXIT_INVALID_SCHEDULE
    return EXIT_OK


def main() -> None:
    try:
        sys.exit(run(parse_args()))
    except OutputExistsError as exc:
        log.error("%s", exc)
        sys.exit(EXIT_OUTPUT_EXISTS)


if __name__ == "__main__":
    main()
