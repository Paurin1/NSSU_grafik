"""Builds and solves the CP-SAT model."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from ortools.sat.python import cp_model

from .config import Settings
from .constraints import ModelVariables, add_hard_constraints, create_variables
from .models import ProblemData
from .objective import PenaltyTerms, apply_weighted_sum, build_penalty_terms
from .preprocessing import ProblemContext, build_context, compute_candidates

STATUS_NAMES_PL = {
    cp_model.OPTIMAL: "OPTIMAL",
    cp_model.FEASIBLE: "FEASIBLE",
    cp_model.INFEASIBLE: "INFEASIBLE",
    cp_model.MODEL_INVALID: "MODEL_INVALID",
    cp_model.UNKNOWN: "UNKNOWN",
}


@dataclass
class SolveResult:
    """Outcome of one solver run.

    ``is_optimal`` is True only for status OPTIMAL; FEASIBLE means a valid
    schedule was found but optimality is not proven.
    """

    status: str
    wall_time_seconds: float
    assignments: dict[tuple[date, str], str] = field(default_factory=dict)  # (day, post) -> employee
    objective_value: float | None = None
    penalties: dict[str, int] = field(default_factory=dict)  # unweighted value per criterion

    @property
    def has_solution(self) -> bool:
        return self.status in ("OPTIMAL", "FEASIBLE")

    @property
    def is_optimal(self) -> bool:
        return self.status == "OPTIMAL"


def build_model(
    ctx: ProblemContext, with_objective: bool = False
) -> tuple[cp_model.CpModel, ModelVariables, PenaltyTerms | None]:
    model = cp_model.CpModel()
    candidates = compute_candidates(ctx)
    variables = create_variables(model, candidates)
    add_hard_constraints(model, ctx, variables)
    penalties = None
    if with_objective:
        penalties = build_penalty_terms(model, ctx, variables)
        apply_weighted_sum(model, ctx, penalties)
    return model, variables, penalties


def configure_solver(settings: Settings) -> cp_model.CpSolver:
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(settings.solver.time_limit_seconds)
    solver.parameters.num_workers = settings.solver.workers
    solver.parameters.random_seed = settings.solver.random_seed
    return solver


def solve(data: ProblemData, settings: Settings, with_objective: bool = True) -> SolveResult:
    """Build the model for ``settings.year/month`` and solve it."""
    ctx = build_context(data, settings)
    model, variables, penalties = build_model(ctx, with_objective)
    solver = configure_solver(settings)
    status_code = solver.solve(model)
    status = STATUS_NAMES_PL.get(status_code, str(status_code))
    result = SolveResult(status=status, wall_time_seconds=solver.wall_time)
    if result.has_solution:
        result.assignments = {
            (day, post_id): employee_id
            for (employee_id, day, post_id), var in variables.x.items()
            if solver.boolean_value(var)
        }
        if model.has_objective():
            result.objective_value = solver.objective_value
        if penalties is not None:
            result.penalties = {
                name: int(solver.value(expr)) for name, expr in penalties.terms.items()
            }
    return result
