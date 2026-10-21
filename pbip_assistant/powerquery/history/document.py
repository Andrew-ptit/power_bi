"""Canonical persisted Problem Chain validation and hash contracts."""

from __future__ import annotations

from copy import deepcopy
from typing import Any
from ...errors import InputError
from datetime import datetime
import hashlib
import json
import math
import re
from ...core.limits import MAX_PROMPT_CHARS
from ..typed.validation import _normalize_steps
from ..typed.compiler import compile_m

SCHEMA_VERSION = "1.0"

TYPE_INFERENCE_POLICY = "pq-infer-v1"

MAX_REVISIONS = 50

MAX_CANONICAL_JSON_BYTES = 2 * 1024 * 1024

MAX_PENDING_MUTATIONS = 5

_REVISION_ID = re.compile(r"^rev_[0-9a-f]{24}$")

_CHAIN_ID = re.compile(r"^chain_[0-9a-f]{24}$")

_PLAN_ID = re.compile(r"^plan_[0-9a-f]{24}$")

_HASH = re.compile(r"^sha256:[0-9a-f]{64}$")

_FORBIDDEN_KEYS = {
    "branchTip", "latestRevisionId", "approval", "approvalId", "previewId",
    "applyId", "sessionToken", "workbookBase64", "resultWorkbookBase64",
    "rawM", "mCode", "expressionText", "sampleRows", "url", "path",
    "localPath", "credential", "password", "connectionString",
}

_FORBIDDEN_KEYS_CASEFOLD = frozenset(key.casefold() for key in _FORBIDDEN_KEYS)

_CHAIN_DOCUMENT_KEYS = {
    "schemaVersion", "chainId", "planId", "storageVersion", "headRevisionId",
    "samplePersistence", "sampleStore", "revisions",
}

_DOCUMENT_KEYS = _CHAIN_DOCUMENT_KEYS | {"archivedChains"}

_REVISION_KEYS = {
    "revisionId", "parentRevisionId", "originKind", "createdAt", "problemPrompt",
    "changeReason", "name", "note", "annotationUpdatedAt",
    "sourceSchemaFingerprint", "snapshotId", "summary", "questions",
    "assumptions", "warnings", "sources", "steps", "finalOutputStepId",
    "changeSet", "validationAtCreation", "runtimeSummary", "reviewHash",
}

_SOURCE_COMMON_KEYS = {
    "sourceId", "kind", "sheetName", "schemaHash", "sampleOnly", "columns",
    "totalRows", "totalColumns",
}

_SOURCE_TABLE_KEYS = _SOURCE_COMMON_KEYS | {"objectName"}

_SOURCE_RANGE_KEYS = _SOURCE_COMMON_KEYS | {"headerRow", "runtimeAlias"}

_COLUMN_KEYS = {"columnId", "ordinal", "name", "inferredType", "nullable"}


def _reject_non_finite(value: Any, path: str = "$") -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise InputError("PQPC_DOCUMENT_INVALID", path, "Non-finite JSON numbers are forbidden")
    if isinstance(value, list):
        for index, item in enumerate(value):
            _reject_non_finite(item, f"{path}[{index}]")
    elif isinstance(value, dict):
        for key, item in value.items():
            _reject_non_finite(item, f"{path}.{key}")


def canonical_json(value: Any) -> bytes:
    _reject_non_finite(value)
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise InputError("PQPC_DOCUMENT_INVALID", "$", "Value is not canonical JSON data") from exc


def _hash(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value)).hexdigest()


def compute_history_hash(document: dict[str, Any]) -> str:
    """Hash the canonical document; no historyHash field exists in the payload."""
    return _hash(document)


def compute_review_hash(revision: dict[str, Any]) -> str:
    return _hash({
        "problemPrompt": revision["problemPrompt"],
        "sourceSchemaFingerprint": revision["sourceSchemaFingerprint"],
        "summary": revision["summary"],
        "questions": revision["questions"],
        "assumptions": revision["assumptions"],
        "warnings": revision["warnings"],
        "sources": revision["sources"],
        "steps": revision["steps"],
        "finalOutputStepId": revision["finalOutputStepId"],
    })


def _scan_forbidden(value: Any, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            child = f"{path}.{key}"
            validation_issue_path = key == "path" and ".validationAtCreation.issues[" in child
            if key.casefold() in _FORBIDDEN_KEYS_CASEFOLD and not validation_issue_path:
                code = "PQV2_POLICY_VIOLATION" if key.casefold() in {"rawm", "mcode", "expressiontext"} else "PQPC_DOCUMENT_INVALID"
                raise InputError(code, child, f"Persisted field {key!r} is forbidden")
            _scan_forbidden(item, child)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _scan_forbidden(item, f"{path}[{index}]")


def _normalized_schema_source(source: Any, path: str) -> dict[str, Any]:
    if not isinstance(source, dict):
        raise InputError("PQPC_DOCUMENT_INVALID", path, "Source must be an object")
    kind = source.get("kind")
    if kind not in {"excelTable", "usedRange"}:
        raise InputError("PQPC_DOCUMENT_INVALID", path + ".kind", "Unsupported source kind")
    columns = source.get("columns")
    if not isinstance(columns, list) or not columns:
        raise InputError("PQPC_DOCUMENT_INVALID", path + ".columns", "Source columns are required")
    normalized_columns: list[dict[str, Any]] = []
    allowed_types = {"any", "text", "integer", "number", "logical", "date", "datetime"}
    for index, column in enumerate(columns):
        column_path = f"{path}.columns[{index}]"
        if not isinstance(column, dict):
            raise InputError("PQPC_DOCUMENT_INVALID", column_path, "Column must be an object")
        column_type = column.get("inferredType", column.get("type"))
        if column.get("ordinal") != index or isinstance(column.get("ordinal"), bool):
            raise InputError("PQPC_DOCUMENT_INVALID", column_path + ".ordinal", "Ordinals must be contiguous")
        if not isinstance(column.get("name"), str) or not column["name"] or len(column["name"]) > 255:
            raise InputError("PQPC_DOCUMENT_INVALID", column_path + ".name", "Column name is invalid")
        if column_type not in allowed_types:
            raise InputError("PQPC_DOCUMENT_INVALID", column_path + ".type", "Normalized type is invalid")
        normalized_columns.append({"ordinal": index, "name": column["name"], "type": column_type})
    if kind == "excelTable":
        if not isinstance(source.get("objectName"), str) or not source["objectName"]:
            raise InputError("PQPC_DOCUMENT_INVALID", path + ".objectName", "Table name is required")
        return {"kind": kind, "objectName": source["objectName"], "columns": normalized_columns}
    if not isinstance(source.get("sheetName"), str) or not source["sheetName"]:
        raise InputError("PQPC_DOCUMENT_INVALID", path + ".sheetName", "Sheet name is required")
    header_row = source.get("headerRow")
    if isinstance(header_row, bool) or not isinstance(header_row, int) or header_row < 1:
        raise InputError("PQPC_DOCUMENT_INVALID", path + ".headerRow", "Header row must be positive")
    return {
        "kind": kind, "sheetName": source["sheetName"], "headerRow": header_row,
        "columns": normalized_columns,
    }


def _validate_persisted_source(source: Any, path: str) -> None:
    if not isinstance(source, dict):
        raise InputError("PQPC_DOCUMENT_INVALID", path, "Source must be an object")
    kind = source.get("kind")
    allowed = _SOURCE_TABLE_KEYS if kind == "excelTable" else _SOURCE_RANGE_KEYS if kind == "usedRange" else set()
    required = {"sourceId", "kind", "columns", "objectName"} if kind == "excelTable" else {
        "sourceId", "kind", "columns", "sheetName", "headerRow",
    }
    if not allowed or set(source) - allowed or required - set(source):
        raise InputError("PQPC_DOCUMENT_INVALID", path, "Source fields do not match the persisted schema")
    for key in ("sourceId", "sheetName", "schemaHash", "runtimeAlias", "objectName"):
        if key in source and (not isinstance(source[key], str) or not source[key]):
            raise InputError("PQPC_DOCUMENT_INVALID", f"{path}.{key}", "Expected non-empty text")
    if "schemaHash" in source and not _HASH.fullmatch(source["schemaHash"]):
        raise InputError("PQPC_DOCUMENT_INVALID", path + ".schemaHash", "Expected SHA-256")
    if "sampleOnly" in source and not isinstance(source["sampleOnly"], bool):
        raise InputError("PQPC_DOCUMENT_INVALID", path + ".sampleOnly", "Expected boolean")
    for key in ("totalRows", "totalColumns"):
        if key in source and (isinstance(source[key], bool) or not isinstance(source[key], int) or source[key] < 0):
            raise InputError("PQPC_DOCUMENT_INVALID", f"{path}.{key}", "Expected non-negative integer")
    columns = source.get("columns")
    if not isinstance(columns, list) or not columns:
        raise InputError("PQPC_DOCUMENT_INVALID", path + ".columns", "Columns are required")
    for index, column in enumerate(columns):
        column_path = f"{path}.columns[{index}]"
        if not isinstance(column, dict) or set(column) != _COLUMN_KEYS:
            raise InputError("PQPC_DOCUMENT_INVALID", column_path, "Column fields do not match schema")
        if not isinstance(column["columnId"], str) or not column["columnId"]:
            raise InputError("PQPC_DOCUMENT_INVALID", column_path + ".columnId", "Column ID is required")
        if not isinstance(column["nullable"], bool):
            raise InputError("PQPC_DOCUMENT_INVALID", column_path + ".nullable", "Expected boolean")
    _normalized_schema_source(source, path)


def source_schema_fingerprint(sources: list[dict[str, Any]]) -> str:
    if not isinstance(sources, list) or not sources:
        raise InputError("PQPC_DOCUMENT_INVALID", "sources", "At least one referenced source is required")
    normalized = [_normalized_schema_source(source, f"sources[{index}]") for index, source in enumerate(sources)]
    normalized.sort(key=lambda item: (
        item["kind"], item.get("objectName", ""), item.get("sheetName", ""), item.get("headerRow", 0),
    ))
    identities = [
        (item["kind"], item.get("objectName"), item.get("sheetName"), item.get("headerRow"))
        for item in normalized
    ]
    if len(identities) != len(set(identities)):
        raise InputError("PQPC_DOCUMENT_INVALID", "sources", "Duplicate source schema identity")
    return _hash({"typeInferencePolicy": TYPE_INFERENCE_POLICY, "sources": normalized})


def _persisted_sources(plan: dict[str, Any]) -> list[dict[str, Any]]:
    sources = plan.get("sources")
    steps = plan.get("steps")
    if not isinstance(sources, list) or not isinstance(steps, list):
        raise InputError("PQPC_DOCUMENT_INVALID", "typedPlan", "Typed plan sources and steps are required")
    source_by_id = {
        source.get("sourceId"): source for source in sources
        if isinstance(source, dict) and isinstance(source.get("sourceId"), str)
    }
    used_ids: set[str] = set()
    for index, step in enumerate(steps):
        if not isinstance(step, dict) or not str(step.get("operation", {}).get("type", "")).startswith("source."):
            continue
        source_id = step.get("operation", {}).get("parameters", {}).get("sourceId")
        if not isinstance(source_id, str) or source_id not in source_by_id:
            raise InputError(
                "PQV2_SOURCE_NOT_FOUND", f"steps[{index}].operation.parameters.sourceId",
                "Source step does not resolve to a persisted workbook source",
            )
        used_ids.add(source_id)
    selected = [{key: deepcopy(value) for key, value in source.items() if key != "sampleRows"}
                for source in sources if isinstance(source, dict) and source.get("sourceId") in used_ids]
    if not selected or len(selected) != len(used_ids):
        raise InputError("PQV2_SOURCE_NOT_FOUND", "steps", "Every source step must resolve to a persisted source")
    _scan_forbidden(selected)
    for index, source in enumerate(selected):
        _validate_persisted_source(source, f"sources[{index}]")
    return selected


def _analyze_semantic_plan(plan: Any) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if not isinstance(plan, dict):
        raise InputError("PQPC_DOCUMENT_INVALID", "typedPlan", "Typed plan must be an object")
    # A full TypedPlanStore public response may include ephemeral preview and
    # approval envelopes.  They are intentionally ignored here; only semantic
    # fields copied below are scanned and persisted.
    _scan_forbidden(plan.get("steps"), "typedPlan.steps")
    sources = _persisted_sources(plan)
    normalized, final_step, blockers, generated_warnings = _normalize_steps(
        plan.get("steps"), plan.get("finalOutputStepId"), sources, draft=False,
    )
    public = {
        "steps": normalized, "finalOutputStepId": final_step,
        "summary": plan.get("summary", ""), "questions": plan.get("questions", []),
        "assumptions": plan.get("assumptions", []),
        "warnings": [*plan.get("warnings", []), *generated_warnings], "sources": sources,
    }
    for key in ("summary",):
        if not isinstance(public[key], str) or not public[key] or len(public[key]) > 2_000:
            raise InputError("PQPC_DOCUMENT_INVALID", key, "A bounded non-empty summary is required")
    for key in ("questions", "assumptions", "warnings"):
        if not isinstance(public[key], list) or len(public[key]) > 20 or not all(isinstance(v, str) and len(v) <= 1_000 for v in public[key]):
            raise InputError("PQPC_DOCUMENT_INVALID", key, "Expected at most 20 bounded strings")
    compiled_hash = None
    if not blockers:
        compile_probe = {
            "sources": sources, "steps": public["steps"], "finalOutputStepId": final_step,
        }
        compiled = compile_m(compile_probe)
        compiled_hash = "sha256:" + hashlib.sha256(compiled.encode("utf-8")).hexdigest()
    return {**public, "compiledMHash": compiled_hash}, blockers


def _validate_semantic_plan(plan: Any) -> dict[str, Any]:
    public, blockers = _analyze_semantic_plan(plan)
    if blockers:
        first = blockers[0]
        raise InputError(first["code"], first["path"], first["reason"])
    return public


def _validate_revision(revision: Any, path: str) -> None:
    if not isinstance(revision, dict) or set(revision) != _REVISION_KEYS:
        raise InputError("PQPC_DOCUMENT_INVALID", path, "Revision fields do not match schema")
    if not _REVISION_ID.fullmatch(str(revision["revisionId"])):
        raise InputError("PQPC_DOCUMENT_INVALID", path + ".revisionId", "Invalid revision ID")
    parent = revision["parentRevisionId"]
    if parent is not None and not _REVISION_ID.fullmatch(str(parent)):
        raise InputError("PQPC_DOCUMENT_INVALID", path + ".parentRevisionId", "Invalid parent revision ID")
    if revision["originKind"] not in {"problem", "manualEdit", "repairPatch"}:
        raise InputError("PQPC_DOCUMENT_INVALID", path + ".originKind", "Invalid origin kind")
    if not isinstance(revision["problemPrompt"], str) or not 1 <= len(revision["problemPrompt"]) <= MAX_PROMPT_CHARS:
        raise InputError("PQPC_DOCUMENT_INVALID", path + ".problemPrompt", "Prompt must contain 1-4000 characters")
    _scan_forbidden(revision, path)
    for key in ("createdAt",):
        try:
            parsed = datetime.fromisoformat(str(revision[key]).replace("Z", "+00:00"))
        except ValueError as exc:
            raise InputError("PQPC_DOCUMENT_INVALID", f"{path}.{key}", "Timestamp is invalid") from exc
        if parsed.tzinfo is None:
            raise InputError("PQPC_DOCUMENT_INVALID", f"{path}.{key}", "Timestamp requires an offset")
    if revision["annotationUpdatedAt"] is not None:
        raise InputError("PQPC_DOCUMENT_INVALID", path + ".annotationUpdatedAt", "Annotations are unsupported")
    if revision["name"] is not None or revision["note"] is not None:
        raise InputError("PQPC_DOCUMENT_INVALID", path + ".name", "Annotations are unsupported")
    for key, limit in (("changeReason", 500), ("snapshotId", 256)):
        if not isinstance(revision[key], str) or not revision[key] or len(revision[key]) > limit:
            raise InputError("PQPC_DOCUMENT_INVALID", f"{path}.{key}", "Expected bounded non-empty text")
    if not isinstance(revision["changeSet"], list):
        raise InputError("PQPC_DOCUMENT_INVALID", path + ".changeSet", "Expected an array")
    sources = revision["sources"]
    for index, source in enumerate(sources if isinstance(sources, list) else []):
        _validate_persisted_source(source, f"{path}.sources[{index}]")
    if revision["sourceSchemaFingerprint"] != source_schema_fingerprint(sources):
        raise InputError("PQPC_HASH_MISMATCH", path + ".sourceSchemaFingerprint", "Source schema fingerprint mismatch")
    semantic, blockers = _analyze_semantic_plan(revision)
    if semantic["steps"] != revision["steps"] or semantic["finalOutputStepId"] != revision["finalOutputStepId"]:
        raise InputError("PQPC_DOCUMENT_INVALID", path + ".steps", "Typed plan is not canonically normalized")
    if revision["reviewHash"] != compute_review_hash(revision):
        raise InputError("PQPC_HASH_MISMATCH", path + ".reviewHash", "Review hash mismatch")
    if not isinstance(revision["validationAtCreation"], dict):
        raise InputError("PQPC_DOCUMENT_INVALID", path + ".validationAtCreation", "Validation evidence must be an object")
    expected_validation = {
        "overall": "blocked" if blockers else "passed",
        "compiledMHash": semantic["compiledMHash"],
        "issues": [{key: deepcopy(value) for key, value in item.items() if key != "gate"} for item in blockers],
    }
    validation_at_creation = revision["validationAtCreation"]
    # Compatibility for revisions created before the flat-final-output gate.
    # They remain loadable as immutable history so the user can add the missing
    # Expand step, but current compilation/preview still rejects the nested final.
    legacy_unexpanded_merge = (
        bool(blockers)
        and all(item.get("code") == "PQV2_NESTED_TABLE_NOT_EXPANDED" for item in blockers)
        and validation_at_creation.get("overall") == "passed"
        and validation_at_creation.get("issues") == []
        and isinstance(validation_at_creation.get("compiledMHash"), str)
        and re.fullmatch(r"sha256:[0-9a-f]{64}", validation_at_creation["compiledMHash"]) is not None
    )
    if not legacy_unexpanded_merge and any(
        validation_at_creation.get(key) != value for key, value in expected_validation.items()
    ):
        raise InputError("PQPC_DOCUMENT_INVALID", path + ".validationAtCreation", "Validation evidence does not match the typed pipeline")
    if revision["runtimeSummary"] is not None:
        raise InputError("PQPC_DOCUMENT_INVALID", path + ".runtimeSummary", "Runtime summary is unsupported")


def _validate_chain_fields(document: dict[str, Any], *, path: str = "$") -> None:
    """Validate one independent chain, without the portfolio archive field."""
    if set(document) != _CHAIN_DOCUMENT_KEYS:
        raise InputError("PQPC_DOCUMENT_INVALID", path, "Chain fields do not match schema")
    if document["schemaVersion"] != SCHEMA_VERSION:
        raise InputError("PQPC_DOCUMENT_INVALID", f"{path}.schemaVersion", "Unsupported schema version")
    if not _CHAIN_ID.fullmatch(str(document["chainId"])) or not _PLAN_ID.fullmatch(str(document["planId"])):
        raise InputError("PQPC_DOCUMENT_INVALID", f"{path}.chainId", "Invalid chain or plan ID")
    if isinstance(document["storageVersion"], bool) or not isinstance(document["storageVersion"], int) or document["storageVersion"] < 1:
        raise InputError("PQPC_DOCUMENT_INVALID", f"{path}.storageVersion", "Storage version must be positive")
    if document["samplePersistence"] != {"enabled": False, "warningAcceptedAt": None, "maxRows": 20, "maxColumns": 200} or document["sampleStore"] != {}:
        raise InputError("PQPC_DOCUMENT_INVALID", f"{path}.samplePersistence", "Persisting sample rows is unsupported")
    revisions = document["revisions"]
    if not isinstance(revisions, list) or not revisions:
        raise InputError("PQPC_DOCUMENT_INVALID", f"{path}.revisions", "A chain requires at least one revision")
    by_id: dict[str, dict[str, Any]] = {}
    roots = 0
    for index, revision in enumerate(revisions):
        revision_path = f"{path}.revisions[{index}]"
        _validate_revision(revision, revision_path)
        revision_id = revision["revisionId"]
        if revision_id in by_id:
            raise InputError("PQPC_DOCUMENT_INVALID", revision_path + ".revisionId", "Duplicate revision ID")
        by_id[revision_id] = revision
        roots += revision["parentRevisionId"] is None
    if roots != 1:
        raise InputError("PQPC_DOCUMENT_INVALID", f"{path}.revisions", "A chain must have exactly one root")
    for revision_id, revision in by_id.items():
        parent = revision["parentRevisionId"]
        if parent is not None and parent not in by_id:
            raise InputError("PQPC_DOCUMENT_INVALID", f"{path}.revision:{revision_id}.parentRevisionId", "Parent does not exist")
        visited: set[str] = set()
        cursor: str | None = revision_id
        while cursor is not None:
            if cursor in visited:
                raise InputError("PQPC_DOCUMENT_INVALID", f"{path}.revision:{revision_id}", "Revision cycle detected")
            visited.add(cursor)
            cursor = by_id[cursor]["parentRevisionId"] if cursor in by_id else None
    if document["headRevisionId"] not in by_id:
        raise InputError("PQPC_DOCUMENT_INVALID", f"{path}.headRevisionId", "Head revision does not exist")


def _bare_chain(document: dict[str, Any]) -> dict[str, Any]:
    return {key: deepcopy(document[key]) for key in _CHAIN_DOCUMENT_KEYS}


def validate_document(document: Any) -> dict[str, Any]:
    if not isinstance(document, dict) or (
        set(document) != _CHAIN_DOCUMENT_KEYS and set(document) != _DOCUMENT_KEYS
    ):
        raise InputError("PQPC_DOCUMENT_INVALID", "$", "Document fields do not match schema")
    _scan_forbidden(document)
    raw_archives = document.get("archivedChains", [])
    raw_total = len(document.get("revisions", [])) if isinstance(document.get("revisions"), list) else 0
    if isinstance(raw_archives, list):
        raw_total += sum(
            len(chain.get("revisions", []))
            for chain in raw_archives
            if isinstance(chain, dict) and isinstance(chain.get("revisions"), list)
        )
    if raw_total > MAX_REVISIONS:
        raise InputError("PQPC_HISTORY_LIMIT", "revisions", "Total revision count exceeds 50")
    active = _bare_chain(document)
    _validate_chain_fields(active)
    archives = document.get("archivedChains", [])
    if not isinstance(archives, list):
        raise InputError("PQPC_DOCUMENT_INVALID", "archivedChains", "Archived chains must be an array")
    seen_chains = {active["chainId"]}
    seen_revisions = {item["revisionId"] for item in active["revisions"]}
    total_revisions = len(active["revisions"])
    for index, chain in enumerate(archives):
        if not isinstance(chain, dict):
            raise InputError("PQPC_DOCUMENT_INVALID", f"archivedChains[{index}]", "Archived chain must be an object")
        _validate_chain_fields(chain, path=f"archivedChains[{index}]")
        if chain["chainId"] in seen_chains:
            raise InputError("PQPC_DOCUMENT_INVALID", f"archivedChains[{index}].chainId", "Duplicate chain ID")
        seen_chains.add(chain["chainId"])
        for revision in chain["revisions"]:
            if revision["revisionId"] in seen_revisions:
                raise InputError("PQPC_DOCUMENT_INVALID", f"archivedChains[{index}].revisions", "Duplicate revision ID across chains")
            seen_revisions.add(revision["revisionId"])
        total_revisions += len(chain["revisions"])
    if total_revisions > MAX_REVISIONS:
        raise InputError("PQPC_HISTORY_LIMIT", "revisions", "Total revision count exceeds 50")
    encoded = canonical_json(document)
    if len(encoded) > MAX_CANONICAL_JSON_BYTES:
        raise InputError("PQPC_HISTORY_LIMIT", "$", "Canonical JSON exceeds 2 MiB")
    return deepcopy(document)
