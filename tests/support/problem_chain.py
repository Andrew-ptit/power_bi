from __future__ import annotations

from copy import deepcopy
import json
import re
import subprocess
import time
import unittest
from unittest import mock

from pbip_assistant.errors import InputError
from pbip_assistant.problem_chain import (
    MAX_CANONICAL_JSON_BYTES,
    MAX_PENDING_MUTATIONS,
    CodexProblemChainPlanner,
    ProblemChainStore,
    _load_and_preflight_continuation_schema,
    canonical_json,
    compute_history_hash,
    compute_review_hash,
    source_schema_fingerprint,
    validate_document,
)


def typed_plan(*, summary: str = "Đọc bảng Sales.") -> dict:
    source = {
        "sourceId": "src_sales", "kind": "excelTable", "sheetName": "Sales",
        "objectName": "tblSales", "schemaHash": "sha256:" + "1" * 64,
        "sampleOnly": False, "totalRows": 2, "totalColumns": 2,
        "columns": [
            {"columnId": "col_order", "name": "OrderID", "inferredType": "text", "nullable": False, "ordinal": 0},
            {"columnId": "col_qty", "name": "Qty", "inferredType": "integer", "nullable": False, "ordinal": 1},
        ],
    }
    return {
        "snapshotId": "snap_test", "summary": summary,
        "questions": [], "assumptions": [], "warnings": [], "sources": [source],
        "steps": [{
            "stepId": "stp_source", "position": 1, "variableName": "SalesSource",
            "actionDescription": "Đọc tblSales.",
            "operation": {"type": "source.workbookTable", "parameters": {"sourceId": "src_sales"}},
            "inputs": [],
            "outputContract": {"kind": "table", "schemaHash": "sha256:" + "2" * 64, "columns": source["columns"]},
        }],
        "finalOutputStepId": "stp_source", "changeSet": [],
    }


class FakeContinuationPlanner:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def propose(self, payload: dict) -> dict:
        self.calls.append(deepcopy(payload))
        return {
            "summary": "Tiếp tục xử lý Sales.", "questions": [], "assumptions": [], "warnings": [],
            "changeReason": "Added next problem",
            "changes": [
                {
                    "type": "insertStep", "afterStepId": "stp_source",
                    "stepDraft": {
                        "clientRef": "selected", "variableName": "SelectedSales",
                        "actionDescription": "Chọn OrderID và Qty.",
                        "operationType": "table.selectColumns",
                        "parameters": {"columnIds": ["col_order", "col_qty"]},
                        "inputs": ["stp_source"],
                    },
                },
                {"type": "setFinalOutput", "stepId": "selected"},
            ],
        }


class LiteralCollisionPlanner:
    def propose(self, payload: dict) -> dict:
        return {
            "summary": "Lọc OrderID theo literal.", "questions": [], "assumptions": [], "warnings": [],
            "changeReason": "Test reference resolver",
            "changes": [{
                "type": "insertStep", "afterStepId": "stp_source",
                "stepDraft": {
                    "clientRef": "selected", "variableName": "SelectedRows",
                    "actionDescription": "selected",
                    "operationType": "table.filterRows",
                    "parameters": {
                        "predicate": {
                            "kind": "compare", "operator": "eq",
                            "left": {"kind": "columnRef", "columnId": "col_order"},
                            "right": {"kind": "literal", "valueType": "text", "value": "selected"},
                        },
                        "onEvaluationError": "block",
                    },
                    "inputs": ["stp_source"],
                },
            }, {"type": "setFinalOutput", "stepId": "selected"}],
        }


class AppendSecondSourcePlanner:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def propose(self, payload: dict) -> dict:
        self.calls.append(deepcopy(payload))
        return {
            "summary": "Nối thêm bảng SalesArchive.", "questions": [], "assumptions": [], "warnings": [],
            "changeReason": "Append second workbook table",
            "changes": [{
                "type": "insertStep", "afterStepId": "stp_source",
                "stepDraft": {
                    "clientRef": "archive", "variableName": "SalesArchiveSource",
                    "actionDescription": "Đọc tblSalesArchive.",
                    "operationType": "source.workbookTable",
                    "parameters": {"sourceId": "src_archive"}, "inputs": [],
                },
            }, {
                "type": "insertStep", "afterStepId": "archive",
                "stepDraft": {
                    "clientRef": "appended", "variableName": "AppendedSales",
                    "actionDescription": "Nối Sales và SalesArchive.",
                    "operationType": "table.appendTables",
                    "parameters": {"schemaMode": "strict"},
                    "inputs": ["stp_source", "archive"],
                },
            }, {"type": "setFinalOutput", "stepId": "appended"}],
        }


class MissingSourceContinuationPlanner:
    def propose(self, payload: dict) -> dict:
        return {
            "summary": "Read a missing source.", "questions": [], "assumptions": [], "warnings": [],
            "changeReason": "Attempt missing source",
            "changes": [{
                "type": "insertStep", "afterStepId": "stp_source",
                "stepDraft": {
                    "clientRef": "missing", "variableName": "MissingSource",
                    "actionDescription": "Read a source that is not in the workbook catalog.",
                    "operationType": "source.workbookTable",
                    "parameters": {"sourceId": "src_missing"}, "inputs": [],
                },
            }, {"type": "setFinalOutput", "stepId": "missing"}],
        }


class MissingFinalThenValidPlanner(FakeContinuationPlanner):
    def propose(self, payload: dict) -> dict:
        self.calls.append(deepcopy(payload))
        if len(self.calls) == 1:
            return {
                "summary": "Replace the source but forget the final output.",
                "questions": [], "assumptions": [], "warnings": [],
                "changeReason": "Invalid first structural delta",
                "changes": [{
                    "type": "insertStep", "afterStepId": "stp_source",
                    "stepDraft": {
                        "clientRef": "replacement_source",
                        "variableName": "ReplacementSource",
                        "actionDescription": "Read the same persisted source.",
                        "operationType": "source.workbookTable",
                        "parameters": {"sourceId": "src_sales"}, "inputs": [],
                    },
                }, {"type": "deleteStep", "stepId": "stp_source"}],
            }
        return {
            "summary": "Continue with a valid final table.",
            "questions": [], "assumptions": [], "warnings": [],
            "changeReason": "Corrected structural delta",
            "changes": [{
                "type": "insertStep", "afterStepId": "stp_source",
                "stepDraft": {
                    "clientRef": "selected", "variableName": "SelectedSales",
                    "actionDescription": "Select OrderID and Qty.",
                    "operationType": "table.selectColumns",
                    "parameters": {"columnIds": ["col_order", "col_qty"]},
                    "inputs": ["stp_source"],
                },
            }, {"type": "setFinalOutput", "stepId": "selected"}],
        }


