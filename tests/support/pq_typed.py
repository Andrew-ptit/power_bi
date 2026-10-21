from __future__ import annotations

import base64
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from pbip_assistant.errors import InputError
from pbip_assistant.pq_code_m import PQPreviewStore
from pbip_assistant.pq_typed import DESTINATION_MARKER, TypedPlanStore, build_source_catalog, compile_m
from tests.support.excel_plan import FIXTURE_ROOT, office_snapshot
from tests.support.pq_code_m import FakePQRunner
from tests.support.workbook_fingerprint import repack


class FakeTypedPlanner:
    def __init__(self) -> None:
        self.payload = None

    def propose(self, payload: dict) -> dict:
        self.payload = payload
        sales = next(item for item in payload["sourceCatalog"] if item.get("objectName") == "SalesTable")
        return {
            "summary": "Lọc doanh thu, tính lợi nhuận và sắp xếp giảm dần.",
            "questions": [], "assumptions": [], "warnings": [],
            "steps": [
                {
                    "clientRef": "sales_source", "variableName": "SalesSource",
                    "actionDescription": "Đọc SalesTable.", "operationType": "source.workbookTable",
                    "inputs": [], "parameters": {"sourceId": sales["sourceId"]},
                },
                {
                    "clientRef": "filtered_sales", "variableName": "FilteredSales",
                    "actionDescription": "Giữ doanh thu lớn hơn 1000.", "operationType": "table.filterRows",
                    "inputs": ["sales_source"],
                    "parameters": {
                        "predicate": {
                            "kind": "compare", "operator": "gt",
                            "left": {"kind": "columnRef", "columnName": "Gross Revenue"},
                            "right": {"kind": "literal", "valueType": "number", "value": 1000},
                        },
                        "onEvaluationError": "block",
                    },
                },
                {
                    "clientRef": "added_profit", "variableName": "AddedProfit",
                    "actionDescription": "Tạo Profit từ doanh thu và chiết khấu.", "operationType": "table.addColumn",
                    "inputs": ["filtered_sales"],
                    "parameters": {
                        "newColumnName": "Profit", "dataType": "number", "onEvaluationError": "block",
                        "expression": {
                            "kind": "arithmetic", "operator": "subtract",
                            "left": {"kind": "columnRef", "columnName": "Gross Revenue"},
                            "right": {"kind": "columnRef", "columnName": "Discount Value"},
                        },
                    },
                },
                {
                    "clientRef": "sorted_profit", "variableName": "SortedProfit",
                    "actionDescription": "Sắp xếp Profit giảm dần.", "operationType": "table.sortRows",
                    "inputs": ["added_profit"],
                    "parameters": {"keys": [{"column": "Profit", "direction": "descending"}]},
                },
            ],
            "finalOutputRef": "sorted_profit",
        }


class CatalogTypedPlanner:
    def propose(self, payload: dict) -> dict:
        sales = next(item for item in payload["sourceCatalog"] if item.get("objectName") == "SalesTable")
        commission = next(item for item in payload["sourceCatalog"] if item.get("objectName") == "CommissionTable")
        steps = [
            {"clientRef": "sales", "variableName": "SalesSource", "actionDescription": "Read sales.", "operationType": "source.workbookTable", "inputs": [], "parameters": {"sourceId": sales["sourceId"]}},
            {"clientRef": "commission", "variableName": "CommissionSource", "actionDescription": "Read commission.", "operationType": "source.workbookTable", "inputs": [], "parameters": {"sourceId": commission["sourceId"]}},
            {"clientRef": "selected", "variableName": "SelectedSales", "actionDescription": "Select columns.", "operationType": "table.selectColumns", "inputs": ["sales"], "parameters": {"columns": ["SaleID", "Region", "Gross Revenue"]}},
            {"clientRef": "removed", "variableName": "RemovedRegion", "actionDescription": "Remove Region.", "operationType": "table.removeColumns", "inputs": ["selected"], "parameters": {"columns": ["Region"]}},
            {"clientRef": "renamed", "variableName": "RenamedRevenue", "actionDescription": "Rename revenue.", "operationType": "table.renameColumns", "inputs": ["removed"], "parameters": {"renames": [{"column": "Gross Revenue", "newName": "Revenue"}]}},
            {"clientRef": "typed", "variableName": "TypedRevenue", "actionDescription": "Type revenue.", "operationType": "table.changeTypes", "inputs": ["renamed"], "parameters": {"conversions": [{"column": "Revenue", "targetType": "number", "culture": None}]}},
            {"clientRef": "distinct", "variableName": "DistinctSales", "actionDescription": "Distinct rows.", "operationType": "table.distinctRows", "inputs": ["typed"], "parameters": {"scope": "columns", "columns": ["SaleID"]}},
            {"clientRef": "grouped", "variableName": "GroupedSales", "actionDescription": "Group by SaleID.", "operationType": "table.groupRows", "inputs": ["distinct"], "parameters": {"keyColumns": ["SaleID"], "aggregations": [{"function": "sum", "column": "Revenue", "outputName": "RevenueTotal"}]}},
            {"clientRef": "aggregate", "variableName": "AggregatedSales", "actionDescription": "Aggregate to one row.", "operationType": "table.aggregateRows", "inputs": ["sales"], "parameters": {"aggregations": [{"function": "rowCount", "outputName": "Rows"}, {"function": "sum", "column": "Gross Revenue", "outputName": "TotalRevenue"}]}},
            {"clientRef": "append", "variableName": "AppendedSales", "actionDescription": "Append sales twice.", "operationType": "table.appendTables", "inputs": ["sales", "sales"], "parameters": {"schemaMode": "strict"}},
            {"clientRef": "merge", "variableName": "MergedCommission", "actionDescription": "Merge commission.", "operationType": "table.mergeTables", "inputs": ["sales", "commission"], "parameters": {"keyPairs": [{"leftColumn": "Gross Revenue", "rightColumn": "Min Net Revenue"}], "joinKind": "leftOuter", "nestedColumnName": "Commission"}},
            {"clientRef": "expand", "variableName": "ExpandedCommission", "actionDescription": "Expand rate.", "operationType": "table.expandTableColumn", "inputs": ["merge"], "parameters": {"nestedColumn": "Commission", "columns": [{"column": "Commission Rate", "newName": "CommissionRate"}]}},
        ]
        return {"summary": "Exercise the full typed catalog.", "questions": [], "assumptions": [], "warnings": [], "steps": steps, "finalOutputRef": "expand"}


class InvalidSingleSourcePlanner(FakeTypedPlanner):
    def propose(self, payload: dict) -> dict:
        response = super().propose(payload)
        response["steps"][0]["parameters"]["sourceId"] = "src_not_authoritative"
        return response


class InvalidMultiSourcePlanner(CatalogTypedPlanner):
    def propose(self, payload: dict) -> dict:
        response = super().propose(payload)
        response["steps"][0]["parameters"]["sourceId"] = "src_not_authoritative"
        return response


class ValidButWrongSingleSourcePlanner(FakeTypedPlanner):
    def propose(self, payload: dict) -> dict:
        response = super().propose(payload)
        other = next(
            source for source in payload["sourceCatalog"]
            if source.get("kind") == "excelTable" and source.get("objectName") != "SalesTable"
        )
        response["steps"][0]["parameters"]["sourceId"] = other["sourceId"]
        return response


class WrongKindSingleSourcePlanner(FakeTypedPlanner):
    def propose(self, payload: dict) -> dict:
        response = super().propose(payload)
        response["steps"][0]["operationType"] = "source.usedRange"
        return response


class ReversedSelectPlanner:
    def propose(self, payload: dict) -> dict:
        source = next(item for item in payload["sourceCatalog"] if item.get("objectName") == "SalesTable")
        names = [item["name"] for item in source["columns"][:3]]
        return {
            "summary": "Select a subset without reordering it.",
            "questions": [], "assumptions": [], "warnings": [],
            "steps": [
                {
                    "clientRef": "source", "variableName": "SalesSource",
                    "actionDescription": "Read sales.", "operationType": "source.workbookTable",
                    "inputs": [], "parameters": {"sourceId": source["sourceId"]},
                },
                {
                    "clientRef": "selected", "variableName": "SelectedColumns",
                    "actionDescription": "Select columns.", "operationType": "table.selectColumns",
                    "inputs": ["source"], "parameters": {"columns": list(reversed(names))},
                },
            ],
            "finalOutputRef": "selected",
        }


class ValidWrongSingleSourcePlanner(FakeTypedPlanner):
    def propose(self, payload: dict) -> dict:
        response = super().propose(payload)
        other = next(item for item in payload["sourceCatalog"] if item.get("objectName") == "CommissionTable")
        response["steps"][0]["parameters"]["sourceId"] = other["sourceId"]
        return response


