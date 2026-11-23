"""Explains INFEASIBLE results using solver assumptions (infeasibility core).

Constraint groups (day coverage, rest per employee, limits per employee) are
guarded by literals; the solver returns a subset of them that is already
contradictory. The core is sufficient but not necessarily minimal.
"""

from __future__ import annotations

from ortools.sat.python import cp_model

from .constraints import Guards, add_hard_constraints, create_variables
from .config import Settings
from .models import ProblemData
from .preprocessing import build_context, compute_candidates

GROUP_LABELS = {
    "obsada": "pełna obsada w dniu {}",
    "odpoczynek": "odpoczynek po dyżurze 16 h pracownika {}",
    "limity": "limity dyżurów pracownika {}",
}


def explain_infeasibility(data: ProblemData, settings: Settings, time_limit: float = 30.0) -> list[str]:
    """Polish messages naming a conflicting set of constraints (empty if none found)."""
    ctx = build_context(data, settings)
    model = cp_model.CpModel()
    variables = create_variables(model, compute_candidates(ctx))
    guards: Guards = {}
    add_hard_constraints(model, ctx, variables, guards)
    model.add_assumptions(list(guards.values()))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_workers = 1
    if solver.solve(model) != cp_model.INFEASIBLE:
        return []
    by_index = {lit.index: name for name, lit in guards.items()}
    names = sorted(by_index[i] for i in solver.sufficient_assumptions_for_infeasibility() if i in by_index)
    if not names:
        return ["Model jest sprzeczny niezależnie od reguł obsady, odpoczynku i limitów "
                "(np. kwalifikacje, niedostępność, blokady FIX/FORBID, jeden dyżur dziennie)."]
    labels = []
    for name in names:
        kind, _, value = name.partition(":")
        labels.append(GROUP_LABELS[kind].format(value))
    return ["Brak rozwiązania. Wzajemnie sprzeczne reguły: " + "; ".join(labels) + "."]
