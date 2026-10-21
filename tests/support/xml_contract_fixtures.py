from __future__ import annotations

import base64
from copy import deepcopy
import json
import unittest

from tests.support.xml_contract_validator import (
    ContractError, MAX_CANONICAL_JSON_BYTES, canonical_json, compute_history_hash,
    compute_review_hash, decode_xml, encode_xml, select_problem_chain_part,
    source_schema_fingerprint, validate_document,
)


def source() -> dict:
    return {
        "sourceId": "src_ignored", "kind": "excelTable", "sheetName": "Sales",
        "objectName": "tblSales", "sampleOnly": True, "totalRows": 3,
        "columns": [
            {"columnId": "col_ignored", "ordinal": 0, "name": "OrderID", "inferredType": "text", "nullable": False},
            {"columnId": "col_ignored2", "ordinal": 1, "name": "Qty", "inferredType": "integer", "nullable": True},
        ],
    }


def revision(number: int = 1, parent: str | None = None) -> dict:
    result = {
        "revisionId": f"rev_{number:024x}", "parentRevisionId": parent,
        "originKind": "problem", "createdAt": "2026-10-12T10:00:00+07:00",
        "problemPrompt": "Chuẩn hóa dữ liệu bán hàng", "changeReason": "Initial problem",
        "name": None, "note": None, "annotationUpdatedAt": None,
        "sourceSchemaFingerprint": source_schema_fingerprint([source()]), "snapshotId": "snap_fixture",
        "summary": "Chuẩn hóa bảng", "questions": [], "assumptions": [], "warnings": [],
        "sources": [source()],
        "steps": [{"stepId": "stp_source", "operation": {"type": "source.workbookTable"}}],
        "finalOutputStepId": "stp_source", "changeSet": [], "validationAtCreation": {},
        "runtimeSummary": None, "reviewHash": "",
    }
    result["reviewHash"] = compute_review_hash(result)
    return result


def document(revisions: list[dict] | None = None) -> dict:
    values = revisions or [revision()]
    return {
        "schemaVersion": "1.0", "chainId": "chain_fixture", "planId": "plan_fixture",
        "storageVersion": 1, "headRevisionId": values[-1]["revisionId"],
        "samplePersistence": {"enabled": False, "warningAcceptedAt": None, "maxRows": 20, "maxColumns": 200},
        "sampleStore": {}, "revisions": values,
    }


