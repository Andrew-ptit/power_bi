"""Deterministic planning contracts for BPMN N-006/N-007.

These pure functions consume *structured* fields. Natural-language extraction and
actual TMDL/PBIR generation are intentionally separate, later stages.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


Goal = Literal["trend", "comparison", "single_kpi", "detail"]
VisualType = Literal["line", "bar", "card", "table"]


@dataclass(frozen=True)
class KpiDefinition:
    name: str
    formula: str
    grain: str
    date_role: str
    unit: str
    components: tuple[str, ...]
    confirmed_by: str | None = None


def kpi_readiness(definition: KpiDefinition) -> dict:
    missing = [field for field in ("name", "formula", "grain", "date_role", "unit") if not getattr(definition, field).strip()]
    if not definition.components:
        missing.append("components")
    if not definition.confirmed_by:
        missing.append("confirmation")
    return {
        "status": "confirmed" if not missing else "needs_clarification",
        "missing": missing,
        "may_generate_dax": not missing,
    }


@dataclass(frozen=True)
class FieldCatalog:
    temporal_dimensions: tuple[str, ...]
    category_dimensions: tuple[str, ...]
    confirmed_measures: tuple[str, ...]


@dataclass(frozen=True)
class VisualRequest:
    question: str
    goal: Goal
    measure: str
    dimension: str | None = None
    requested_type: str | None = None
    target_page: str | None = None


def propose_visual(request: VisualRequest, catalog: FieldCatalog) -> dict:
    defaults: dict[str, VisualType] = {
        "trend": "line", "comparison": "bar", "single_kpi": "card", "detail": "table",
    }
    suggested = request.requested_type or defaults.get(request.goal)
    missing: list[str] = []
    if suggested not in {"line", "bar", "card", "table"}:
        missing.append(f"unsupported_visual_type:{suggested}")
    if request.measure not in catalog.confirmed_measures:
        missing.append(f"confirmed_measure:{request.measure}")
    if suggested == "line" and request.dimension not in catalog.temporal_dimensions:
        missing.append(f"temporal_dimension:{request.dimension}")
    if suggested == "bar" and request.dimension not in catalog.category_dimensions:
        missing.append(f"category_dimension:{request.dimension}")
    if suggested == "table" and request.dimension not in (*catalog.category_dimensions, *catalog.temporal_dimensions):
        missing.append(f"dimension:{request.dimension}")
    if not request.target_page:
        missing.append("target_page")
    alternative = defaults.get(request.goal)
    return {
        "question": request.question,
        "visual_type": suggested,
        "field_roles": {"measure": request.measure, "dimension": request.dimension},
        "target_page": request.target_page,
        "rationale": {
            "line": "A time axis shows change across periods",
            "bar": "Categories can be compared side by side",
            "card": "A single confirmed KPI can be shown at a glance",
            "table": "Shows grouped/detail fields without implying a trend",
        }.get(suggested, "Requested chart type is not in the supported catalog"),
        "status": "needs_clarification" if missing else "needs_user_review",
        "missing": missing,
        "alternative_type": alternative if suggested != alternative else None,
        "may_generate_pbir": False,
    }


@dataclass(frozen=True)
class ProposedOperation:
    id: str
    type: str
    target: str
    depends_on: tuple[str, ...] = ()
    approved: bool = False


SUPPORTED_OPERATIONS = frozenset({"measure.add", "query.add", "visual.add", "visual.rebind"})


def validate_operation_selection(operations: list[ProposedOperation], selected_ids: set[str]) -> dict:
    errors: list[str] = []
    by_id = {operation.id: operation for operation in operations}
    if len(by_id) != len(operations):
        errors.append("duplicate_operation_id")
    for operation in operations:
        if operation.type not in SUPPORTED_OPERATIONS:
            errors.append(f"unsupported_operation:{operation.id}:{operation.type}")
    for selected in selected_ids:
        operation = by_id.get(selected)
        if operation is None:
            errors.append(f"unknown_selection:{selected}")
            continue
        if not operation.approved:
            errors.append(f"not_approved:{selected}")
        for dependency in operation.depends_on:
            if dependency not in selected_ids:
                errors.append(f"missing_dependency:{selected}:{dependency}")
    for operation in operations:
        for dependency in operation.depends_on:
            if dependency not in by_id:
                errors.append(f"unknown_dependency:{operation.id}:{dependency}")
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(operation_id: str) -> None:
        if operation_id in visiting:
            errors.append(f"dependency_cycle:{operation_id}")
            return
        if operation_id in visited or operation_id not in by_id:
            return
        visiting.add(operation_id)
        for dependency in by_id[operation_id].depends_on:
            visit(dependency)
        visiting.remove(operation_id)
        visited.add(operation_id)

    for operation in operations:
        visit(operation.id)
    return {"status": "static_pass" if not errors else "blocked", "errors": sorted(set(errors))}
