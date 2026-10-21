"""Problem Chain candidate-value construction and structured delta handling.

Functions return detached values; storage authority, CAS and locks stay in store.
"""

from __future__ import annotations
from copy import deepcopy
from datetime import datetime, timezone
import secrets
from typing import Any
from pbip_assistant.errors import InputError
from pbip_assistant.powerquery.history.document import (
    _analyze_semantic_plan,
    compute_review_hash,
    source_schema_fingerprint,
)


def _random_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(12)}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _revision_from_plan(
    plan: dict[str, Any], *, prompt: str, parent_revision_id: str | None,
    origin_kind: str = "problem", change_reason: str, allow_blocked: bool = False,
) -> dict[str, Any]:
    plan_blockers = plan.get("hardBlockers") if isinstance(plan, dict) else None
    if isinstance(plan_blockers, list) and plan_blockers and not allow_blocked:
        first = plan_blockers[0]
        if isinstance(first, dict):
            raise InputError(
                str(first.get("code") or "PQPC_DOCUMENT_INVALID"),
                str(first.get("path") or "typedPlan"),
                str(first.get("reason") or "Typed plan is blocked"),
            )
    semantic, blockers = _analyze_semantic_plan(plan)
    if blockers and not allow_blocked:
        first = blockers[0]
        raise InputError(first["code"], first["path"], first["reason"])
    snapshot_id = plan.get("snapshotId")
    if not isinstance(snapshot_id, str) or not snapshot_id or len(snapshot_id) > 256:
        raise InputError("PQPC_DOCUMENT_INVALID", "snapshotId", "Snapshot ID must be bounded non-empty text")
    revision: dict[str, Any] = {
        "revisionId": _random_id("rev"), "parentRevisionId": parent_revision_id,
        "originKind": origin_kind, "createdAt": _now(), "problemPrompt": prompt,
        "changeReason": change_reason[:500], "name": None, "note": None,
        "annotationUpdatedAt": None,
        "sourceSchemaFingerprint": source_schema_fingerprint(semantic["sources"]),
        "snapshotId": snapshot_id,
        "summary": semantic["summary"], "questions": semantic["questions"],
        "assumptions": semantic["assumptions"], "warnings": semantic["warnings"],
        "sources": semantic["sources"], "steps": semantic["steps"],
        "finalOutputStepId": semantic["finalOutputStepId"],
        "changeSet": deepcopy(plan.get("changeSet", [])),
        "validationAtCreation": {
            "overall": "blocked" if blockers else "passed",
            "compiledMHash": semantic["compiledMHash"],
            "issues": [{key: deepcopy(value) for key, value in item.items() if key != "gate"} for item in blockers],
        },
        "runtimeSummary": None, "reviewHash": "",
    }
    revision["reviewHash"] = compute_review_hash(revision)
    return revision


def _validate_continuation_proposal_shape(proposal: Any) -> dict[str, Any]:
    """Fail closed on planner output before it can influence persisted semantics."""
    allowed = {"summary", "questions", "assumptions", "warnings", "changeReason", "changes"}
    if not isinstance(proposal, dict) or set(proposal) != allowed:
        raise InputError("PQPC_DOCUMENT_INVALID", "planner", "Continuation planner must return a strict typed change proposal")
    for key, limit in (("summary", 2_000), ("changeReason", 500)):
        if not isinstance(proposal[key], str) or not proposal[key].strip() or len(proposal[key]) > limit:
            raise InputError("PQPC_DOCUMENT_INVALID", f"planner.{key}", "Expected bounded non-empty text")
    for key in ("questions", "assumptions", "warnings"):
        values = proposal[key]
        if not isinstance(values, list) or len(values) > 20 or not all(
            isinstance(value, str) and len(value) <= 1_000 for value in values
        ):
            raise InputError("PQPC_DOCUMENT_INVALID", f"planner.{key}", "Expected at most 20 bounded strings")
    changes = proposal["changes"]
    if not isinstance(changes, list) or len(changes) > 50 or (not changes and not proposal["questions"]):
        raise InputError("PQPC_DOCUMENT_INVALID", "planner.changes", "Continuation requires changes or a clarification question")
    change_fields = {
        "insertStep": {"type", "afterStepId", "stepDraft"},
        "updateStep": {"type", "stepId", "stepDraft"},
        "deleteStep": {"type", "stepId"},
        "moveStep": {"type", "stepId", "position"},
        "setFinalOutput": {"type", "stepId"},
    }
    draft_fields = {"clientRef", "variableName", "actionDescription", "operationType", "parameters", "inputs"}
    update_fields = draft_fields - {"clientRef"}
    forbidden_names = {
        "rawm", "mcode", "expressiontext", "url", "path", "localpath", "credential",
        "token", "password", "connectionstring", "workbookbase64",
    }

    def scan_keys(value: Any, path: str) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key.casefold() in forbidden_names:
                    raise InputError("PQV2_POLICY_VIOLATION", f"{path}.{key}", "Forbidden planner field")
                scan_keys(item, f"{path}.{key}")
        elif isinstance(value, list):
            for item_index, item in enumerate(value):
                scan_keys(item, f"{path}[{item_index}]")

    for index, change in enumerate(changes):
        path = f"planner.changes[{index}]"
        kind = change.get("type") if isinstance(change, dict) else None
        expected = change_fields.get(kind)
        if expected is None or set(change) != expected:
            raise InputError("PQPC_DOCUMENT_INVALID", path, "Change fields do not match the typed variant")
        if kind in {"updateStep", "deleteStep", "moveStep", "setFinalOutput"} and (
            not isinstance(change["stepId"], str) or not change["stepId"]
        ):
            raise InputError("PQPC_DOCUMENT_INVALID", path + ".stepId", "Step reference is required")
        if kind == "insertStep" and change["afterStepId"] is not None and (
            not isinstance(change["afterStepId"], str) or not change["afterStepId"]
        ):
            raise InputError("PQPC_DOCUMENT_INVALID", path + ".afterStepId", "Insertion anchor must be text or null")
        if kind == "moveStep" and (
            isinstance(change["position"], bool) or not isinstance(change["position"], int)
        ):
            raise InputError("PQPC_DOCUMENT_INVALID", path + ".position", "Move position must be an integer")
        if kind in {"insertStep", "updateStep"}:
            draft = change["stepDraft"]
            expected_draft = draft_fields if kind == "insertStep" else update_fields
            if not isinstance(draft, dict) or set(draft) != expected_draft:
                raise InputError("PQPC_DOCUMENT_INVALID", path + ".stepDraft", "Step draft fields do not match the typed variant")
            if not isinstance(draft["inputs"], list):
                raise InputError("PQPC_DOCUMENT_INVALID", path + ".stepDraft.inputs", "Step inputs must be an array")
        scan_keys(change, path)
    return proposal


def _clarification_response(
    questions: Any, assumptions: Any, warnings: Any,
) -> dict[str, Any]:
    def clean(values: Any, field: str, *, required: bool = False) -> list[str]:
        if not isinstance(values, list) or len(values) > 20 or any(
            not isinstance(value, str) or not value.strip() or len(value) > 1_000 for value in values
        ):
            raise InputError("PQPC_DOCUMENT_INVALID", field, "Clarification text must be bounded and non-empty")
        result = list(dict.fromkeys(value.strip() for value in values))
        if required and not result:
            raise InputError("PQPC_DOCUMENT_INVALID", field, "Clarification needs at least one question")
        return result

    return {
        "status": "needsClarification",
        "questions": clean(questions, "questions", required=True),
        "assumptions": clean(assumptions, "assumptions"),
        "warnings": clean(warnings, "warnings"),
    }


def _continuation_plan(
    base: dict[str, Any], proposal: Any, *, source_catalog: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Apply a strict typed change proposal while preserving unaffected step IDs."""
    proposal = _validate_continuation_proposal_shape(proposal)
    changes = proposal["changes"]
    result = {
        "snapshotId": base["snapshotId"], "summary": proposal["summary"],
        "questions": proposal["questions"], "assumptions": proposal["assumptions"],
        "warnings": proposal["warnings"],
        "sources": deepcopy(source_catalog if source_catalog is not None else base["sources"]),
        "steps": deepcopy(base["steps"]), "finalOutputStepId": base["finalOutputStepId"],
        "changeSet": [], "changeReason": proposal["changeReason"],
    }
    insert_ids: dict[str, str] = {}
    for index, change in enumerate(changes):
        if not isinstance(change, dict) or change.get("type") != "insertStep":
            continue
        draft = change.get("stepDraft")
        client_ref = draft.get("clientRef") if isinstance(draft, dict) else None
        if not isinstance(client_ref, str) or not client_ref or client_ref in insert_ids:
            raise InputError("PQPC_DOCUMENT_INVALID", f"planner.changes[{index}].stepDraft.clientRef", "Inserted steps need unique clientRef values")
        insert_ids[client_ref] = _random_id("stp")

    def resolve_ref(value: Any) -> Any:
        return insert_ids.get(value, value) if isinstance(value, str) else value

    def resolve_inputs(values: list[Any]) -> list[Any]:
        resolved: list[Any] = []
        for item in values:
            if isinstance(item, str):
                resolved.append(resolve_ref(item))
            elif isinstance(item, dict):
                updated = deepcopy(item)
                if "ref" in updated:
                    updated["ref"] = resolve_ref(updated["ref"])
                resolved.append(updated)
            else:
                resolved.append(deepcopy(item))
        return resolved

    for index, raw_change in enumerate(changes):
        change = deepcopy(raw_change)
        kind = change.get("type") if isinstance(change, dict) else None
        steps = result["steps"]
        if "stepId" in change:
            change["stepId"] = resolve_ref(change["stepId"])
        if "afterStepId" in change:
            change["afterStepId"] = resolve_ref(change["afterStepId"])
        if kind in {"insertStep", "updateStep"}:
            change["stepDraft"]["inputs"] = resolve_inputs(change["stepDraft"]["inputs"])
        step_id = change.get("stepId")
        position = next((i for i, step in enumerate(steps) if step["stepId"] == step_id), None)
        if kind == "insertStep":
            draft = change.get("stepDraft")
            new_step = {
                "stepId": insert_ids[raw_change["stepDraft"]["clientRef"]],
                "variableName": draft["variableName"], "actionDescription": draft["actionDescription"],
                "operation": {"type": draft["operationType"], "parameters": deepcopy(draft["parameters"])},
                "inputs": [
                    item if isinstance(item, dict) else {"kind": "step", "ref": item}
                    for item in deepcopy(draft["inputs"])
                ],
            }
            after = change.get("afterStepId")
            insert_at = 0 if after is None else next((i + 1 for i, item in enumerate(steps) if item["stepId"] == after), None)
            if insert_at is None:
                raise InputError("PQV2_DEPENDENCY_INVALID", f"planner.changes[{index}].afterStepId", "Insertion anchor does not exist")
            steps.insert(insert_at, new_step)
            change["stepId"] = new_step["stepId"]
        elif position is None:
            raise InputError("PQV2_DEPENDENCY_INVALID", f"planner.changes[{index}].stepId", "Target step does not exist")
        elif kind == "updateStep":
            draft = change.get("stepDraft")
            updated = deepcopy(steps[position])
            for field in ("variableName", "actionDescription", "inputs"):
                if field in draft:
                    updated[field] = deepcopy(draft[field])
            if "operationType" in draft or "parameters" in draft:
                updated["operation"] = {
                    "type": draft.get("operationType", updated["operation"]["type"]),
                    "parameters": deepcopy(draft.get("parameters", updated["operation"]["parameters"])),
                }
            steps[position] = updated
        elif kind == "deleteStep":
            steps.pop(position)
            if result["finalOutputStepId"] == step_id:
                result["finalOutputStepId"] = None
        elif kind == "moveStep":
            new_position = change.get("position")
            if isinstance(new_position, bool) or not isinstance(new_position, int) or not 1 <= new_position <= len(steps):
                raise InputError("PQPC_DOCUMENT_INVALID", f"planner.changes[{index}].position", "Move position is invalid")
            item = steps.pop(position)
            steps.insert(new_position - 1, item)
        elif kind == "setFinalOutput":
            result["finalOutputStepId"] = step_id
        result["changeSet"].append({key: deepcopy(value) for key, value in change.items() if key != "stepDraft"})
    for index, step in enumerate(result["steps"]):
        step["position"] = index + 1
    return result


def _manual_edit_plan(
    base: dict[str, Any], changes: Any, change_reason: Any,
    *, source_catalog: list[dict[str, Any]],
) -> dict[str, Any]:
    """Normalize UI edit shapes into the same deterministic typed patch engine."""
    if not isinstance(change_reason, str) or not change_reason.strip() or len(change_reason) > 500:
        raise InputError("PQPC_DOCUMENT_INVALID", "changeReason", "A bounded change reason is required")
    if not isinstance(changes, list) or not 1 <= len(changes) <= 50:
        raise InputError("PQPC_DOCUMENT_INVALID", "changes", "Manual edit requires 1-50 changes")
    by_id = {step["stepId"]: step for step in base["steps"]}
    normalized_changes: list[dict[str, Any]] = []
    allowed_change_fields = {
        "insertStep": {"type", "afterStepId", "stepDraft"},
        "updateStep": {"type", "stepId", "stepDraft"},
        "deleteStep": {"type", "stepId"},
        "moveStep": {"type", "stepId", "position"},
        "setFinalOutput": {"type", "stepId"},
    }
    draft_fields = {"variableName", "actionDescription", "operationType", "parameters", "inputs"}
    for index, value in enumerate(changes):
        path = f"changes[{index}]"
        kind = value.get("type") if isinstance(value, dict) else None
        expected = allowed_change_fields.get(kind)
        if expected is None or set(value) != expected:
            raise InputError("PQPC_DOCUMENT_INVALID", path, "Manual change fields do not match the typed variant")
        change = deepcopy(value)
        if kind == "insertStep":
            draft = change["stepDraft"]
            if not isinstance(draft, dict) or set(draft) != draft_fields:
                raise InputError("PQPC_DOCUMENT_INVALID", path + ".stepDraft", "Insert step fields do not match schema")
            draft["clientRef"] = f"manual_{index}"
        elif kind == "updateStep":
            step_id = change["stepId"]
            existing = by_id.get(step_id)
            draft = change["stepDraft"]
            if existing is None:
                raise InputError("PQV2_DEPENDENCY_INVALID", path + ".stepId", "Target step does not exist")
            if not isinstance(draft, dict) or not draft or set(draft) - draft_fields:
                raise InputError("PQPC_DOCUMENT_INVALID", path + ".stepDraft", "Update step fields do not match schema")
            change["stepDraft"] = {
                "variableName": deepcopy(draft.get("variableName", existing["variableName"])),
                "actionDescription": deepcopy(draft.get("actionDescription", existing["actionDescription"])),
                "operationType": deepcopy(draft.get("operationType", existing["operation"]["type"])),
                "parameters": deepcopy(draft.get("parameters", existing["operation"]["parameters"])),
                "inputs": deepcopy(draft.get("inputs", existing["inputs"])),
            }
        normalized_changes.append(change)
    proposal = {
        "summary": base["summary"], "questions": deepcopy(base["questions"]),
        "assumptions": deepcopy(base["assumptions"]), "warnings": deepcopy(base["warnings"]),
        "changeReason": change_reason.strip(), "changes": normalized_changes,
    }
    return _continuation_plan(base, proposal, source_catalog=source_catalog)


def _collect_column_ids(value: Any, result: set[str]) -> None:
    """Collect lineage references from persisted Typed structures."""
    if isinstance(value, dict):
        column_id = value.get("columnId")
        if isinstance(column_id, str):
            result.add(column_id)
        column_ids = value.get("columnIds")
        if isinstance(column_ids, list):
            result.update(item for item in column_ids if isinstance(item, str))
        for item in value.values():
            _collect_column_ids(item, result)
    elif isinstance(value, list):
        for item in value:
            _collect_column_ids(item, result)


def _descendant_impact_report(document: dict[str, Any], edited_revision_id: str | None) -> dict[str, Any]:
    """Conservatively identify old descendants requiring review after an edit.

    Phase 2 never replays or rewrites those descendants.  The report therefore
    describes review scope rather than claiming a deterministic repair.
    """
    children: dict[str, list[dict[str, Any]]] = {}
    for revision in document["revisions"]:
        parent = revision["parentRevisionId"]
        if parent is not None:
            children.setdefault(parent, []).append(revision)
    for items in children.values():
        items.sort(key=lambda item: (item["createdAt"], item["revisionId"]))

    descendants: list[dict[str, Any]] = []
    pending = list(children.get(str(edited_revision_id), []))
    while pending:
        revision = pending.pop(0)
        descendants.append(revision)
        pending[0:0] = children.get(revision["revisionId"], [])

    affected_steps: set[str] = set()
    affected_columns: set[str] = set()
    issues: list[dict[str, Any]] = []
    for revision in descendants:
        step_ids = sorted({step["stepId"] for step in revision["steps"]})
        column_ids: set[str] = set()
        _collect_column_ids(revision["steps"], column_ids)
        affected_steps.update(step_ids)
        affected_columns.update(column_ids)
        issues.append({
            "code": "PQPC_DESCENDANT_REVIEW_REQUIRED",
            "revisionId": revision["revisionId"],
            "stepIds": step_ids,
            "columnIds": sorted(column_ids),
            "reason": (
                "This descendant belongs to the original branch and may no longer match the edited problem; "
                "it was preserved without replay, deletion or repair."
            ),
        })
    return {
        "affectedRevisionIds": [item["revisionId"] for item in descendants],
        "affectedStepIds": sorted(affected_steps),
        "affectedColumnIds": sorted(affected_columns),
        "issues": issues,
    }
