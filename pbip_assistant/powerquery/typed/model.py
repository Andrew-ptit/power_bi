"""Typed catalog, canonical IDs and side-effect-free value helpers."""

from __future__ import annotations

from copy import deepcopy
from typing import Any
from ...errors import InputError
from datetime import datetime, timezone
import hashlib
import json
import re
import secrets

SCHEMA_VERSION = "2.0"

MAX_STEPS = 50

MAX_SOURCES = 20

MAX_INPUTS = 20

MAX_ACTIVE_PREVIEWS = 5

MAX_PROBLEM_RESULT_CACHE_BYTES = 64 * 1024 * 1024

MAX_STEP_DIAGNOSTIC_CACHE_ENTRIES = 5

MAX_STEP_DIAGNOSTIC_CACHE_BYTES = 32 * 1024 * 1024

MAX_STEP_DIAGNOSTIC_STAGING_BYTES = 48 * 1024 * 1024

MAX_COMPILED_M_CHARS = 16_000

TYPED_COMPILER_POLICY_VERSION = "pq-typed-compiler-v1"

TYPED_SCHEMA_POLICY_VERSION = "pq-typed-schema-v2"

DESTINATION_MARKER = "localDataCopilot.pqTypedResult.v2"

VARIABLE = re.compile(r"^[A-Z][A-Za-z0-9]{0,63}$")

CLIENT_REF = re.compile(r"^[a-z][a-z0-9_]{0,63}$")

M_RESERVED = frozenset({"and", "as", "each", "else", "error", "false", "if", "in", "is", "let", "meta", "not", "null", "or", "otherwise", "section", "shared", "then", "true", "try", "type"})

OPERATION_ARITY: dict[str, tuple[int, int]] = {
    "source.workbookTable": (0, 0),
    "source.usedRange": (0, 0),
    "table.filterRows": (1, 1),
    "table.selectColumns": (1, 1),
    "table.removeColumns": (1, 1),
    "table.renameColumns": (1, 1),
    "table.changeTypes": (1, 1),
    "table.addColumn": (1, 1),
    "table.sortRows": (1, 1),
    "table.distinctRows": (1, 1),
    "table.groupRows": (1, 1),
    "table.aggregateRows": (1, 1),
    "table.appendTables": (2, 20),
    "table.mergeTables": (2, 2),
    "table.expandTableColumn": (1, 1),
}

TYPE_NAMES = frozenset({"any", "text", "number", "integer", "logical", "date", "datetime", "datetimezone", "time", "duration"})

AGGREGATIONS = frozenset({"rowCount", "countNonNull", "countDistinct", "sum", "average", "min", "max"})

JOIN_KINDS = frozenset({"inner", "leftOuter", "rightOuter", "fullOuter", "leftAnti", "rightAnti"})

FUNCTIONS = frozenset({"text.trim", "text.upper", "text.lower", "text.length", "number.round", "date.year", "date.month", "date.day"})

COMPARE_OPERATORS = frozenset({"eq", "ne", "gt", "gte", "lt", "lte", "contains", "startsWith", "endsWith", "isNull", "isNotNull"})

PARAMETER_KEYS: dict[str, set[str]] = {
    "source.workbookTable": {"sourceId"},
    "source.usedRange": {"sourceId"},
    "table.filterRows": {"predicate", "onEvaluationError"},
    "table.selectColumns": {"columnIds", "columns"},
    "table.removeColumns": {"columnIds", "columns"},
    "table.renameColumns": {"renames"},
    "table.changeTypes": {"conversions"},
    "table.addColumn": {"newColumnName", "newColumnId", "dataType", "expression", "onEvaluationError"},
    "table.sortRows": {"keys"},
    "table.distinctRows": {"scope", "columnIds", "columns"},
    "table.groupRows": {"keyColumnIds", "keyColumns", "aggregations"},
    "table.aggregateRows": {"keyColumnIds", "aggregations"},
    "table.appendTables": {"schemaMode"},
    "table.mergeTables": {"keyPairs", "joinKind", "nestedColumnName", "nestedColumnId"},
    "table.expandTableColumn": {"nestedColumn", "nestedColumnId", "columns"},
}

EXPRESSION_KEYS: dict[str, set[str]] = {
    "literal": {"kind", "valueType", "value"},
    "columnRef": {"kind", "columnId", "columnName", "column"},
    "compare": {"kind", "operator", "left", "right"},
    "arithmetic": {"kind", "operator", "left", "right"},
    "boolean": {"kind", "operator", "operands"},
    "not": {"kind", "operand"},
    "ifThenElse": {"kind", "condition", "then", "else"},
    "coalesce": {"kind", "values"},
    "functionCall": {"kind", "function", "args"},
    "safeDivide": {"kind", "numerator", "denominator", "onZero"},
}


def _compatible_types(left: str, right: str) -> bool:
    if "any" in {left, right} or left == right:
        return True
    return {left, right} <= {"number", "integer"}


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _content_id(prefix: str, value: Any) -> str:
    return f"{prefix}_{_digest(value)[:24]}"


def _random_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(12)}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _list_of_strings(value: Any, path: str) -> list[str]:
    if not isinstance(value, list) or len(value) > 20 or not all(isinstance(item, str) and len(item) <= 1000 for item in value):
        raise InputError("CODEX_RESPONSE_INVALID", path, "Expected at most 20 bounded strings")
    return list(value)


def _strict_keys(value: Any, allowed: set[str], required: set[str], path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise InputError("PQV2_JSON_INVALID", path, "Expected an object")
    unknown = set(value) - allowed
    missing = required - set(value)
    if unknown or missing:
        detail = f"Unknown fields: {sorted(unknown)}" if unknown else f"Missing fields: {sorted(missing)}"
        raise InputError("PQV2_JSON_INVALID", path, detail)
    return value


def _issue(gate: str, code: str, path: str, target: str, reason: str, remedy: str) -> dict[str, str]:
    return {"gate": gate, "code": code, "path": path, "target": target, "reason": reason, "remedy": remedy}


def _replace_refs(value: Any, replacements: dict[str, str]) -> Any:
    if isinstance(value, str):
        return replacements.get(value, value)
    if isinstance(value, list):
        return [_replace_refs(item, replacements) for item in value]
    if isinstance(value, dict):
        return {key: _replace_refs(item, replacements) for key, item in value.items()}
    return value


def _infer_type(values: list[Any]) -> str:
    present = [value for value in values if value is not None and value != ""]
    if not present:
        return "any"
    if all(isinstance(value, bool) for value in present):
        return "logical"
    if all(isinstance(value, int) and not isinstance(value, bool) for value in present):
        return "integer"
    if all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in present):
        return "number"
    if all(isinstance(value, str) for value in present):
        return "text"
    return "any"


def _public_sources(catalog: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{key: deepcopy(value) for key, value in source.items() if key != "sampleRows"} for source in catalog]
