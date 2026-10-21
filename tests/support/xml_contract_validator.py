"""Pure-Python oracle for the Problem Chain Custom XML storage contract.

This module is deliberately isolated from product code.  Wave 0 uses it to make
the proposed envelope, canonicalization, hashing, size and tree rules executable
before any Office.js persistence is integrated into the add-in.
"""

from __future__ import annotations

import base64
import binascii
from copy import deepcopy
from datetime import datetime
import hashlib
import json
import math
import re
from typing import Any, Iterable
import xml.etree.ElementTree as ET


NAMESPACE = "urn:local-data-copilot:pq-problem-chain:v1"
ROOT_TAG = f"{{{NAMESPACE}}}problemChain"
PAYLOAD_TAG = f"{{{NAMESPACE}}}payload"
SCHEMA_VERSION = "1.0"
TYPE_INFERENCE_POLICY = "pq-infer-v1"
MAX_REVISIONS = 50
MAX_CANONICAL_JSON_BYTES = 2 * 1024 * 1024
MAX_PROMPT_CHARS = 4_000

_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_REVISION_ID = re.compile(r"^rev_[0-9a-f]{24}$")
_CHAIN_ID = re.compile(r"^chain_[A-Za-z0-9_-]{1,128}$")
_PLAN_ID = re.compile(r"^plan_[A-Za-z0-9_-]{1,128}$")
_XML_DECLARATION_RISK = re.compile(r"<!\s*(?:DOCTYPE|ENTITY)\b", re.IGNORECASE)

DOCUMENT_KEYS = {
    "schemaVersion", "chainId", "planId", "storageVersion", "headRevisionId",
    "samplePersistence", "sampleStore", "revisions",
}
SAMPLE_POLICY_KEYS = {"enabled", "warningAcceptedAt", "maxRows", "maxColumns"}
SAMPLE_ENTRY_KEYS = {"rows"}
SOURCE_COMMON_KEYS = {
    "sourceId", "kind", "sheetName", "schemaHash", "sampleOnly", "columns",
    "totalRows", "totalColumns",
}
SOURCE_TABLE_KEYS = SOURCE_COMMON_KEYS | {"objectName"}
SOURCE_USED_RANGE_KEYS = SOURCE_COMMON_KEYS | {"headerRow", "runtimeAlias"}
COLUMN_KEYS = {"columnId", "ordinal", "name", "inferredType", "type", "nullable"}
REVISION_KEYS = {
    "revisionId", "parentRevisionId", "originKind", "createdAt", "problemPrompt",
    "changeReason", "name", "note", "annotationUpdatedAt",
    "sourceSchemaFingerprint", "snapshotId", "summary", "questions",
    "assumptions", "warnings", "sources", "steps", "finalOutputStepId",
    "changeSet", "validationAtCreation", "runtimeSummary", "reviewHash",
}
RUNTIME_SUMMARY_KEYS = {
    "previewedAt", "excelVersion", "refreshSucceeded", "sourceRows", "resultRows",
    "resultColumns", "outputColumnNames", "compiledMHash",
}
FORBIDDEN_PERSISTED_KEYS = {
    "branchTip", "latestRevisionId", "approval", "approvalId", "previewId",
    "applyId", "sessionToken", "workbookBase64", "resultWorkbookBase64",
}


class ContractError(ValueError):
    """Stable error code plus path for a Wave 0 contract failure."""

    def __init__(self, code: str, path: str, detail: str) -> None:
        self.code = code
        self.path = path
        self.detail = detail
        super().__init__(f"{code} at {path}: {detail}")


def _reject_non_finite(value: Any) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ContractError("PQPC_DOCUMENT_INVALID", "$", "Non-finite JSON numbers are forbidden")
    if isinstance(value, list):
        for item in value:
            _reject_non_finite(item)
    elif isinstance(value, dict):
        for item in value.values():
            _reject_non_finite(item)


def canonical_json(value: Any) -> bytes:
    """Return the one permitted JSON byte representation for hashes and storage."""
    _reject_non_finite(value)
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ContractError("PQPC_DOCUMENT_INVALID", "$", "Value is not canonical JSON data") from exc


def sha256(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value)).hexdigest()


def compute_review_hash(revision: dict[str, Any]) -> str:
    """Hash semantic review content; deliberately exclude identity and annotations."""
    basis = {
        "problemPrompt": revision["problemPrompt"],
        "sourceSchemaFingerprint": revision["sourceSchemaFingerprint"],
        "summary": revision["summary"],
        "questions": revision["questions"],
        "assumptions": revision["assumptions"],
        "warnings": revision["warnings"],
        "sources": revision["sources"],
        "steps": revision["steps"],
        "finalOutputStepId": revision["finalOutputStepId"],
    }
    return sha256(basis)


def compute_history_hash(document: dict[str, Any]) -> str:
    """Hash the complete canonical JSON payload (the hash lives in the XML wrapper)."""
    return sha256(document)


def _normalized_schema_source(source: dict[str, Any], path: str) -> dict[str, Any]:
    if not isinstance(source, dict):
        raise ContractError("PQPC_DOCUMENT_INVALID", path, "Source must be an object")
    kind = source.get("kind")
    if kind not in {"excelTable", "usedRange"}:
        raise ContractError("PQPC_DOCUMENT_INVALID", path + ".kind", "Unsupported source kind")
    columns = source.get("columns")
    if not isinstance(columns, list) or not columns:
        raise ContractError("PQPC_DOCUMENT_INVALID", path + ".columns", "Columns must be non-empty")
    normalized_columns = []
    allowed_types = {"any", "text", "integer", "number", "logical", "date", "datetime"}
    for index, column in enumerate(columns):
        column_path = f"{path}.columns[{index}]"
        if not isinstance(column, dict):
            raise ContractError("PQPC_DOCUMENT_INVALID", column_path, "Column must be an object")
        ordinal = column.get("ordinal")
        name = column.get("name")
        column_type = column.get("inferredType", column.get("type"))
        if ordinal != index or isinstance(ordinal, bool):
            raise ContractError("PQPC_DOCUMENT_INVALID", column_path + ".ordinal", "Ordinals must be contiguous and ordered")
        if not isinstance(name, str) or not name or len(name) > 255:
            raise ContractError("PQPC_DOCUMENT_INVALID", column_path + ".name", "Column name is invalid")
        if column_type not in allowed_types:
            raise ContractError("PQPC_DOCUMENT_INVALID", column_path + ".type", "Normalized type is invalid")
        normalized_columns.append({"ordinal": ordinal, "name": name, "type": column_type})
    if kind == "excelTable":
        object_name = source.get("objectName")
        if not isinstance(object_name, str) or not object_name:
            raise ContractError("PQPC_DOCUMENT_INVALID", path + ".objectName", "Table name is required")
        return {"kind": kind, "objectName": object_name, "columns": normalized_columns}
    sheet_name = source.get("sheetName")
    header_row = source.get("headerRow")
    if not isinstance(sheet_name, str) or not sheet_name:
        raise ContractError("PQPC_DOCUMENT_INVALID", path + ".sheetName", "Sheet name is required")
    if isinstance(header_row, bool) or not isinstance(header_row, int) or header_row < 1:
        raise ContractError("PQPC_DOCUMENT_INVALID", path + ".headerRow", "Header row must be positive")
    return {
        "kind": kind, "sheetName": sheet_name, "headerRow": header_row,
        "columns": normalized_columns,
    }


def source_schema_fingerprint(sources: list[dict[str, Any]]) -> str:
    """Hash schema only, independent of workbook identity, samples and source IDs."""
    if not isinstance(sources, list) or not sources:
        raise ContractError("PQPC_DOCUMENT_INVALID", "sources", "At least one referenced source is required")
    normalized = [_normalized_schema_source(item, f"sources[{index}]") for index, item in enumerate(sources)]
    normalized.sort(key=lambda item: (
        item["kind"], item.get("objectName", ""), item.get("sheetName", ""), item.get("headerRow", 0),
    ))
    identities = [
        (item["kind"], item.get("objectName"), item.get("sheetName"), item.get("headerRow"))
        for item in normalized
    ]
    if len(identities) != len(set(identities)):
        raise ContractError("PQPC_DOCUMENT_INVALID", "sources", "Duplicate source schema identity")
    return sha256({"typeInferencePolicy": TYPE_INFERENCE_POLICY, "sources": normalized})


def _exact_keys(value: Any, expected: set[str], path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError("PQPC_DOCUMENT_INVALID", path, "Expected an object")
    unknown = set(value) - expected
    missing = expected - set(value)
    if unknown or missing:
        detail = f"unknown={sorted(unknown)}, missing={sorted(missing)}"
        raise ContractError("PQPC_DOCUMENT_INVALID", path, detail)
    return value


def _timestamp(value: Any, path: str, *, nullable: bool = False) -> None:
    if value is None and nullable:
        return
    if not isinstance(value, str):
        raise ContractError("PQPC_DOCUMENT_INVALID", path, "Timestamp must be text")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractError("PQPC_DOCUMENT_INVALID", path, "Timestamp is not ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ContractError("PQPC_DOCUMENT_INVALID", path, "Timestamp must include an offset")


def _scan_forbidden_keys(value: Any, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            child = f"{path}.{key}"
            if key in FORBIDDEN_PERSISTED_KEYS:
                raise ContractError("PQPC_DOCUMENT_INVALID", child, "Runtime/derived secret field must not be persisted")
            _scan_forbidden_keys(item, child)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _scan_forbidden_keys(item, f"{path}[{index}]")


def _validate_runtime_summary(value: Any, path: str) -> None:
    if value is None:
        return
    summary = _exact_keys(value, RUNTIME_SUMMARY_KEYS, path)
    _timestamp(summary["previewedAt"], path + ".previewedAt")
    if not isinstance(summary["excelVersion"], str) or not summary["excelVersion"]:
        raise ContractError("PQPC_DOCUMENT_INVALID", path + ".excelVersion", "Excel version is required")
    if not isinstance(summary["refreshSucceeded"], bool):
        raise ContractError("PQPC_DOCUMENT_INVALID", path + ".refreshSucceeded", "Expected boolean")
    for key in ("sourceRows", "resultRows", "resultColumns"):
        if isinstance(summary[key], bool) or not isinstance(summary[key], int) or summary[key] < 0:
            raise ContractError("PQPC_DOCUMENT_INVALID", path + "." + key, "Expected non-negative integer")
    names = summary["outputColumnNames"]
    if not isinstance(names, list) or not all(isinstance(item, str) and item for item in names):
        raise ContractError("PQPC_DOCUMENT_INVALID", path + ".outputColumnNames", "Expected column names")
    if not _SHA256.fullmatch(summary["compiledMHash"] or ""):
        raise ContractError("PQPC_DOCUMENT_INVALID", path + ".compiledMHash", "Expected SHA-256")


def _validate_persisted_source(source: Any, path: str) -> None:
    """Reject cell samples and every field outside the persisted source contract."""
    if not isinstance(source, dict):
        raise ContractError("PQPC_DOCUMENT_INVALID", path, "Source must be an object")
    kind = source.get("kind")
    if kind == "excelTable":
        allowed = SOURCE_TABLE_KEYS
        required = {"kind", "objectName", "columns"}
    elif kind == "usedRange":
        allowed = SOURCE_USED_RANGE_KEYS
        required = {"kind", "sheetName", "headerRow", "columns"}
    else:
        raise ContractError("PQPC_DOCUMENT_INVALID", path + ".kind", "Unsupported source kind")
    unknown = set(source) - allowed
    missing = required - set(source)
    if unknown or missing:
        raise ContractError(
            "PQPC_DOCUMENT_INVALID", path,
            f"unknown={sorted(unknown)}, missing={sorted(missing)}",
        )
    for key in ("sourceId", "sheetName", "schemaHash", "runtimeAlias", "objectName"):
        if key in source and (not isinstance(source[key], str) or not source[key]):
            raise ContractError("PQPC_DOCUMENT_INVALID", path + "." + key, "Non-empty text is required")
    if "schemaHash" in source and not _SHA256.fullmatch(source["schemaHash"]):
        raise ContractError("PQPC_DOCUMENT_INVALID", path + ".schemaHash", "Expected SHA-256")
    if "sampleOnly" in source and not isinstance(source["sampleOnly"], bool):
        raise ContractError("PQPC_DOCUMENT_INVALID", path + ".sampleOnly", "Expected boolean")
    for key in ("totalRows", "totalColumns"):
        if key in source and (
            isinstance(source[key], bool) or not isinstance(source[key], int) or source[key] < 0
        ):
            raise ContractError("PQPC_DOCUMENT_INVALID", path + "." + key, "Expected non-negative integer")
    if "headerRow" in source and (
        isinstance(source["headerRow"], bool)
        or not isinstance(source["headerRow"], int)
        or source["headerRow"] < 1
    ):
        raise ContractError("PQPC_DOCUMENT_INVALID", path + ".headerRow", "Expected positive integer")
    columns = source.get("columns")
    if not isinstance(columns, list) or not columns:
        raise ContractError("PQPC_DOCUMENT_INVALID", path + ".columns", "Columns must be non-empty")
    for index, column in enumerate(columns):
        column_path = f"{path}.columns[{index}]"
        if not isinstance(column, dict):
            raise ContractError("PQPC_DOCUMENT_INVALID", column_path, "Column must be an object")
        unknown_column = set(column) - COLUMN_KEYS
        missing_column = {"ordinal", "name"} - set(column)
        type_fields = {key for key in ("type", "inferredType") if key in column}
        if unknown_column or missing_column or len(type_fields) != 1:
            raise ContractError(
                "PQPC_DOCUMENT_INVALID", column_path,
                f"unknown={sorted(unknown_column)}, missing={sorted(missing_column)}, "
                f"typeFields={sorted(type_fields)}",
            )
        if "columnId" in column and (not isinstance(column["columnId"], str) or not column["columnId"]):
            raise ContractError("PQPC_DOCUMENT_INVALID", column_path + ".columnId", "Non-empty text is required")
        if "nullable" in column and not isinstance(column["nullable"], bool):
            raise ContractError("PQPC_DOCUMENT_INVALID", column_path + ".nullable", "Expected boolean")


def _validate_sample_store(store: Any, policy: dict[str, Any]) -> None:
    if not isinstance(store, dict):
        raise ContractError("PQPC_DOCUMENT_INVALID", "$.sampleStore", "Sample store must be an object")
    for content_hash, entry_value in store.items():
        path = f"$.sampleStore[{content_hash!r}]"
        if not isinstance(content_hash, str) or not _SHA256.fullmatch(content_hash):
            raise ContractError("PQPC_DOCUMENT_INVALID", path, "Sample key must be a SHA-256 content hash")
        entry = _exact_keys(entry_value, SAMPLE_ENTRY_KEYS, path)
        rows = entry["rows"]
        if not isinstance(rows, list) or len(rows) > policy["maxRows"]:
            raise ContractError("PQPC_DOCUMENT_INVALID", path + ".rows", "Sample exceeds the 20-row limit")
        for row_index, row in enumerate(rows):
            row_path = f"{path}.rows[{row_index}]"
            if not isinstance(row, list) or len(row) > policy["maxColumns"]:
                raise ContractError("PQPC_DOCUMENT_INVALID", row_path, "Sample row exceeds the 200-column limit")
            for column_index, cell in enumerate(row):
                cell_path = f"{row_path}[{column_index}]"
                if cell is None or isinstance(cell, (str, bool, int)):
                    continue
                if isinstance(cell, float) and math.isfinite(cell):
                    continue
                raise ContractError(
                    "PQPC_DOCUMENT_INVALID", cell_path,
                    "Sample cells must be finite scalar JSON values",
                )
        if content_hash != sha256(entry):
            raise ContractError("PQPC_HASH_MISMATCH", path, "Sample content hash mismatch")


def validate_document(document: Any) -> dict[str, Any]:
    """Validate the proposed JSON storage contract and return a defensive copy."""
    document = _exact_keys(document, DOCUMENT_KEYS, "$")
    _scan_forbidden_keys(document)
    if document["schemaVersion"] != SCHEMA_VERSION:
        raise ContractError("PQPC_DOCUMENT_INVALID", "$.schemaVersion", "Unsupported schema version")
    if not _CHAIN_ID.fullmatch(document["chainId"] or ""):
        raise ContractError("PQPC_DOCUMENT_INVALID", "$.chainId", "Invalid chain ID")
    if not _PLAN_ID.fullmatch(document["planId"] or ""):
        raise ContractError("PQPC_DOCUMENT_INVALID", "$.planId", "Invalid plan ID")
    version = document["storageVersion"]
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise ContractError("PQPC_DOCUMENT_INVALID", "$.storageVersion", "Storage version must be positive")

    policy = _exact_keys(document["samplePersistence"], SAMPLE_POLICY_KEYS, "$.samplePersistence")
    if not isinstance(policy["enabled"], bool) or policy["maxRows"] != 20 or policy["maxColumns"] != 200:
        raise ContractError("PQPC_DOCUMENT_INVALID", "$.samplePersistence", "Sample limits must be 20 x 200")
    if policy["enabled"]:
        _timestamp(policy["warningAcceptedAt"], "$.samplePersistence.warningAcceptedAt")
    elif policy["warningAcceptedAt"] is not None or document["sampleStore"] != {}:
        raise ContractError(
            "PQPC_DOCUMENT_INVALID", "$.samplePersistence",
            "Disabled sample persistence requires null acknowledgement and an empty store",
        )
    _validate_sample_store(document["sampleStore"], policy)

    revisions = document["revisions"]
    if not isinstance(revisions, list) or not revisions:
        raise ContractError("PQPC_DOCUMENT_INVALID", "$.revisions", "A persisted chain requires one or more revisions")
    if len(revisions) > MAX_REVISIONS:
        raise ContractError("PQPC_HISTORY_LIMIT", "$.revisions", "Revision count exceeds 50")
    by_id: dict[str, dict[str, Any]] = {}
    root_count = 0
    for index, revision_value in enumerate(revisions):
        path = f"$.revisions[{index}]"
        revision = _exact_keys(revision_value, REVISION_KEYS, path)
        revision_id = revision["revisionId"]
        if not isinstance(revision_id, str) or not _REVISION_ID.fullmatch(revision_id):
            raise ContractError("PQPC_DOCUMENT_INVALID", path + ".revisionId", "Invalid revision ID")
        if revision_id in by_id:
            raise ContractError("PQPC_DOCUMENT_INVALID", path + ".revisionId", "Duplicate revision ID")
        by_id[revision_id] = revision
        parent = revision["parentRevisionId"]
        if parent is None:
            root_count += 1
        elif not isinstance(parent, str) or not _REVISION_ID.fullmatch(parent):
            raise ContractError("PQPC_DOCUMENT_INVALID", path + ".parentRevisionId", "Invalid parent revision ID")
        if revision["originKind"] not in {"problem", "manualEdit", "repairPatch"}:
            raise ContractError("PQPC_DOCUMENT_INVALID", path + ".originKind", "Invalid origin kind")
        _timestamp(revision["createdAt"], path + ".createdAt")
        _timestamp(revision["annotationUpdatedAt"], path + ".annotationUpdatedAt", nullable=True)
        if not isinstance(revision["problemPrompt"], str) or not 1 <= len(revision["problemPrompt"]) <= MAX_PROMPT_CHARS:
            raise ContractError("PQPC_DOCUMENT_INVALID", path + ".problemPrompt", "Prompt must be 1..4000 characters")
        if revision["name"] is not None and (not isinstance(revision["name"], str) or len(revision["name"]) > 128):
            raise ContractError("PQPC_DOCUMENT_INVALID", path + ".name", "Name exceeds 128 characters")
        if revision["note"] is not None and (not isinstance(revision["note"], str) or len(revision["note"]) > 4_000):
            raise ContractError("PQPC_DOCUMENT_INVALID", path + ".note", "Note exceeds 4000 characters")
        for key in ("changeReason", "summary", "snapshotId", "finalOutputStepId"):
            if not isinstance(revision[key], str) or not revision[key]:
                raise ContractError("PQPC_DOCUMENT_INVALID", path + "." + key, "Non-empty text is required")
        for key in ("questions", "assumptions", "warnings", "sources", "steps", "changeSet"):
            if not isinstance(revision[key], list):
                raise ContractError("PQPC_DOCUMENT_INVALID", path + "." + key, "Expected an array")
        for source_index, source in enumerate(revision["sources"]):
            _validate_persisted_source(source, f"{path}.sources[{source_index}]")
        if not isinstance(revision["validationAtCreation"], dict):
            raise ContractError("PQPC_DOCUMENT_INVALID", path + ".validationAtCreation", "Expected an object")
        if not _SHA256.fullmatch(revision["sourceSchemaFingerprint"] or ""):
            raise ContractError("PQPC_DOCUMENT_INVALID", path + ".sourceSchemaFingerprint", "Expected SHA-256")
        expected_schema_hash = source_schema_fingerprint(revision["sources"])
        if revision["sourceSchemaFingerprint"] != expected_schema_hash:
            raise ContractError("PQPC_HASH_MISMATCH", path + ".sourceSchemaFingerprint", "Source schema fingerprint mismatch")
        expected_review_hash = compute_review_hash(revision)
        if revision["reviewHash"] != expected_review_hash:
            raise ContractError("PQPC_HASH_MISMATCH", path + ".reviewHash", "Review hash mismatch")
        _validate_runtime_summary(revision["runtimeSummary"], path + ".runtimeSummary")

    if root_count != 1:
        raise ContractError("PQPC_DOCUMENT_INVALID", "$.revisions", "A chain must have exactly one root")
    for revision_id, revision in by_id.items():
        parent = revision["parentRevisionId"]
        if parent is not None and parent not in by_id:
            raise ContractError("PQPC_DOCUMENT_INVALID", f"revision:{revision_id}.parentRevisionId", "Parent does not exist")
        visited: set[str] = set()
        current: str | None = revision_id
        while current is not None:
            if current in visited:
                raise ContractError("PQPC_DOCUMENT_INVALID", f"revision:{revision_id}", "Revision cycle detected")
            visited.add(current)
            current = by_id[current]["parentRevisionId"] if current in by_id else None
    if document["headRevisionId"] not in by_id:
        raise ContractError("PQPC_DOCUMENT_INVALID", "$.headRevisionId", "Head revision does not exist")

    encoded = canonical_json(document)
    if len(encoded) > MAX_CANONICAL_JSON_BYTES:
        raise ContractError("PQPC_HISTORY_LIMIT", "$", "Canonical JSON exceeds 2 MiB")
    return deepcopy(document)


def encode_xml(document: dict[str, Any]) -> str:
    """Validate and encode a document into the exact v1 wrapper."""
    validated = validate_document(document)
    payload = base64.b64encode(canonical_json(validated)).decode("ascii")
    history_hash = compute_history_hash(validated)
    ET.register_namespace("ldc", NAMESPACE)
    root = ET.Element(ROOT_TAG, {"schemaVersion": SCHEMA_VERSION, "historyHash": history_hash})
    child = ET.SubElement(root, PAYLOAD_TAG, {"encoding": "base64"})
    child.text = payload
    return ET.tostring(root, encoding="unicode", short_empty_elements=False)


def decode_xml(xml: str) -> dict[str, Any]:
    """Decode one part with fail-closed XML and canonical JSON checks."""
    if not isinstance(xml, str) or not xml:
        raise ContractError("PQPC_DOCUMENT_INVALID", "xml", "XML text is required")
    if _XML_DECLARATION_RISK.search(xml):
        raise ContractError("PQPC_DOCUMENT_INVALID", "xml", "DTD and entity declarations are forbidden")
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise ContractError("PQPC_DOCUMENT_INVALID", "xml", "Malformed XML") from exc
    if root.tag != ROOT_TAG or set(root.attrib) != {"schemaVersion", "historyHash"}:
        raise ContractError("PQPC_DOCUMENT_INVALID", "xml", "Unexpected root or attributes")
    if root.attrib["schemaVersion"] != SCHEMA_VERSION or not _SHA256.fullmatch(root.attrib["historyHash"]):
        raise ContractError("PQPC_DOCUMENT_INVALID", "xml", "Invalid schema version or history hash")
    children = list(root)
    if len(children) != 1 or children[0].tag != PAYLOAD_TAG or children[0].attrib != {"encoding": "base64"}:
        raise ContractError("PQPC_DOCUMENT_INVALID", "xml.payload", "Expected exactly one Base64 payload")
    if (root.text or "").strip() or (children[0].tail or "").strip():
        raise ContractError("PQPC_DOCUMENT_INVALID", "xml", "Unexpected mixed XML content")
    try:
        raw = base64.b64decode(children[0].text or "", validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ContractError("PQPC_DOCUMENT_INVALID", "xml.payload", "Invalid Base64") from exc
    if len(raw) > MAX_CANONICAL_JSON_BYTES:
        raise ContractError("PQPC_HISTORY_LIMIT", "xml.payload", "Decoded JSON exceeds 2 MiB")
    try:
        document = json.loads(raw.decode("utf-8"), parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ContractError("PQPC_DOCUMENT_INVALID", "xml.payload", "Invalid UTF-8 JSON") from exc
    if raw != canonical_json(document):
        raise ContractError("PQPC_DOCUMENT_INVALID", "xml.payload", "JSON payload is not canonical")
    validate_document(document)
    if root.attrib["historyHash"] != compute_history_hash(document):
        raise ContractError("PQPC_HASH_MISMATCH", "xml.historyHash", "History hash mismatch")
    return document


def select_problem_chain_part(parts: Iterable[str]) -> dict[str, Any] | None:
    """Apply the 0/1/>1 namespace rule to already namespace-filtered part XML."""
    values = list(parts)
    if not values:
        return None
    if len(values) > 1:
        raise ContractError("PQPC_DUPLICATE_XML_PART", "customXmlParts", "More than one Problem Chain part exists")
    return decode_xml(values[0])

