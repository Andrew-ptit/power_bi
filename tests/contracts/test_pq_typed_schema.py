from __future__ import annotations

import json
from pathlib import Path
import re
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from pbip_assistant.errors import InputError
from pbip_assistant.pq_typed import (
    AI_SCHEMA_PATH,
    EXPRESSION_KEYS,
    OPERATION_ARITY,
    CodexTypedRunner,
    _codex_failure_code,
    _load_and_preflight_ai_schema,
)


class TypedPlannerSchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.schema = _load_and_preflight_ai_schema()
        self.definitions = self.schema["$defs"]

    def _step_definitions(self) -> list[dict]:
        result = []
        for variant in self.schema["properties"]["steps"]["items"]["anyOf"]:
            result.append(self.definitions[variant["$ref"].removeprefix("#/$defs/")])
        return result

    def _matches(self, instance: object, schema: dict) -> bool:
        """Small standard-library oracle for the schema features used here."""
        if "$ref" in schema:
            return self._matches(instance, self.definitions[schema["$ref"].removeprefix("#/$defs/")])
        if "anyOf" in schema and not any(self._matches(instance, item) for item in schema["anyOf"]):
            return False
        if "enum" in schema and instance not in schema["enum"]:
            return False
        expected = schema.get("type")
        if expected is not None:
            expected_types = expected if isinstance(expected, list) else [expected]
            checks = {
                "object": lambda: isinstance(instance, dict),
                "array": lambda: isinstance(instance, list),
                "string": lambda: isinstance(instance, str),
                "number": lambda: isinstance(instance, (int, float)) and not isinstance(instance, bool),
                "integer": lambda: isinstance(instance, int) and not isinstance(instance, bool),
                "boolean": lambda: isinstance(instance, bool),
                "null": lambda: instance is None,
            }
            if not any(checks[item]() for item in expected_types):
                return False
        if isinstance(instance, dict) and schema.get("type") == "object":
            properties = schema["properties"]
            if any(key not in instance for key in schema["required"]):
                return False
            if schema.get("additionalProperties") is False and any(key not in properties for key in instance):
                return False
            if any(not self._matches(instance[key], properties[key]) for key in instance if key in properties):
                return False
        if isinstance(instance, list) and schema.get("type") == "array":
            if len(instance) < schema.get("minItems", 0) or len(instance) > schema.get("maxItems", 2**31):
                return False
            if "items" in schema and any(not self._matches(item, schema["items"]) for item in instance):
                return False
        if isinstance(instance, str):
            if len(instance) < schema.get("minLength", 0) or len(instance) > schema.get("maxLength", 2**31):
                return False
            if "pattern" in schema and re.fullmatch(schema["pattern"], instance) is None:
                return False
        return True

    @staticmethod
    def _step(operation: str, inputs: list[str], parameters: dict, index: int = 1) -> dict:
        return {
            "clientRef": f"step_{index}", "variableName": f"TypedStep{index}",
            "actionDescription": "Synthetic schema test.", "operationType": operation,
            "inputs": inputs, "parameters": parameters,
        }

    def _draft(self, step: dict) -> dict:
        return {
            "summary": "Synthetic.", "questions": [], "assumptions": [], "warnings": [],
            "steps": [step], "finalOutputRef": step["clientRef"],
        }

    def test_schema_has_exactly_one_strict_variant_for_every_catalog_operation(self) -> None:
        variants = self._step_definitions()
        operations = [item["properties"]["operationType"]["enum"][0] for item in variants]
        self.assertEqual(len(operations), 15)
        self.assertEqual(set(operations), set(OPERATION_ARITY))
        self.assertEqual(len(operations), len(set(operations)))
        for variant in variants:
            self.assertIs(variant["additionalProperties"], False)
            self.assertEqual(set(variant["required"]), set(variant["properties"]))
            operation = variant["properties"]["operationType"]["enum"][0]
            input_def = self.definitions[variant["properties"]["inputs"]["$ref"].removeprefix("#/$defs/")]
            self.assertEqual(input_def.get("minItems", 0), OPERATION_ARITY[operation][0])
            self.assertEqual(input_def["maxItems"], OPERATION_ARITY[operation][1])

    def test_all_ten_expression_nodes_are_recursive_strict_and_name_based(self) -> None:
        expression_refs = self.definitions["expression"]["anyOf"]
        nodes = [self.definitions[item["$ref"].removeprefix("#/$defs/")] for item in expression_refs]
        kinds = [node["properties"]["kind"]["enum"][0] for node in nodes]
        self.assertEqual(set(kinds), set(EXPRESSION_KEYS))
        self.assertEqual(len(kinds), 10)
        for node in nodes:
            self.assertIs(node["additionalProperties"], False)
            self.assertEqual(set(node["required"]), set(node["properties"]))
        column_ref = next(node for node in nodes if node["properties"]["kind"]["enum"] == ["columnRef"])
        self.assertIn("columnName", column_ref["properties"])
        self.assertNotIn("columnId", column_ref["properties"])
        self.assertNotIn("rawM", json.dumps(self.schema))

    def test_every_object_schema_is_closed_and_requires_all_properties(self) -> None:
        checked = 0

        def walk(value: object) -> None:
            nonlocal checked
            if isinstance(value, dict):
                if value.get("type") == "object":
                    checked += 1
                    self.assertIs(value.get("additionalProperties"), False)
                    self.assertEqual(set(value.get("required", [])), set(value.get("properties", {})))
                for item in value.values():
                    walk(item)
            elif isinstance(value, list):
                for item in value:
                    walk(item)

        walk(self.schema)
        self.assertGreaterEqual(checked, 1 + 15 + 10)

    def test_preflight_rejects_schema_drift_before_codex(self) -> None:
        broken = json.loads(AI_SCHEMA_PATH.read_text(encoding="utf-8"))
        broken["$defs"]["filterParameters"].pop("additionalProperties")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "broken.json"
            path.write_text(json.dumps(broken), encoding="utf-8")
            with self.assertRaises(InputError) as caught:
                _load_and_preflight_ai_schema(path)
        self.assertEqual(caught.exception.code, "CODEX_SCHEMA_INVALID")

    def test_parameter_contracts_exclude_raw_code_and_external_access_fields(self) -> None:
        forbidden = {"rawM", "mCode", "mExpression", "url", "path", "credential"}
        for variant in self._step_definitions():
            parameters_ref = variant["properties"]["parameters"]["$ref"].removeprefix("#/$defs/")
            parameters = self.definitions[parameters_ref]
            self.assertFalse(forbidden & set(parameters["properties"]))
            self.assertIs(parameters["additionalProperties"], False)

    def test_golden_drafts_cover_all_fifteen_operations(self) -> None:
        literal = {"kind": "literal", "valueType": "number", "value": 1}
        column = {"kind": "columnRef", "columnName": "Sales"}
        examples = {
            "source.workbookTable": ([], {"sourceId": "src_sales"}),
            "source.usedRange": ([], {"sourceId": "src_range"}),
            "table.filterRows": (["source"], {"predicate": {"kind": "compare", "operator": "gt", "left": column, "right": literal}, "onEvaluationError": "block"}),
            "table.selectColumns": (["source"], {"columns": ["Sales"]}),
            "table.removeColumns": (["source"], {"columns": ["Sales"]}),
            "table.renameColumns": (["source"], {"renames": [{"column": "Sales", "newName": "Revenue"}]}),
            "table.changeTypes": (["source"], {"conversions": [{"column": "Sales", "targetType": "number", "culture": None}]}),
            "table.addColumn": (["source"], {"newColumnName": "Tax", "dataType": "number", "expression": literal, "onEvaluationError": "block"}),
            "table.sortRows": (["source"], {"keys": [{"column": "Sales", "direction": "descending"}]}),
            "table.distinctRows": (["source"], {"scope": "all", "columns": None}),
            "table.groupRows": (["source"], {"keyColumns": ["Region"], "aggregations": [{"function": "sum", "column": "Sales", "outputName": "Total"}]}),
            "table.aggregateRows": (["source"], {"aggregations": [{"function": "rowCount", "column": None, "outputName": "Rows"}]}),
            "table.appendTables": (["left", "right"], {"schemaMode": "strict"}),
            "table.mergeTables": (["left", "right"], {"keyPairs": [{"leftColumn": "Code", "rightColumn": "Code"}], "joinKind": "leftOuter", "nestedColumnName": "Product"}),
            "table.expandTableColumn": (["merged"], {"nestedColumn": "Product", "columns": [{"column": "Category", "newName": None}]}),
        }
        self.assertEqual(set(examples), set(OPERATION_ARITY))
        for index, (operation, (inputs, parameters)) in enumerate(examples.items(), 1):
            self.assertTrue(self._matches(self._draft(self._step(operation, inputs, parameters, index)), self.schema), operation)

    def test_golden_drafts_cover_all_ten_expression_nodes(self) -> None:
        literal = {"kind": "literal", "valueType": "number", "value": 1}
        column = {"kind": "columnRef", "columnName": "Sales"}
        compare = {"kind": "compare", "operator": "gt", "left": column, "right": literal}
        expressions = {
            "literal": literal,
            "columnRef": column,
            "compare": compare,
            "arithmetic": {"kind": "arithmetic", "operator": "add", "left": column, "right": literal},
            "boolean": {"kind": "boolean", "operator": "and", "operands": [compare, compare]},
            "not": {"kind": "not", "operand": compare},
            "ifThenElse": {"kind": "ifThenElse", "condition": compare, "then": literal, "else": literal},
            "coalesce": {"kind": "coalesce", "values": [column, literal]},
            "functionCall": {"kind": "functionCall", "function": "number.round", "args": [column, literal]},
            "safeDivide": {"kind": "safeDivide", "numerator": column, "denominator": literal, "onZero": "null"},
        }
        self.assertEqual(set(expressions), set(EXPRESSION_KEYS))
        for index, (kind, expression) in enumerate(expressions.items(), 1):
            step = self._step("table.addColumn", ["source"], {
                "newColumnName": "Result", "dataType": "any", "expression": expression,
                "onEvaluationError": "block",
            }, index)
            self.assertTrue(self._matches(self._draft(step), self.schema), kind)

    def test_schema_rejects_wrong_parameters_arity_raw_access_and_unknown_function(self) -> None:
        invalid = [
            self._step("table.sortRows", ["source"], {"keys": [], "rawM": "Web.Contents(\"https://example.test\")"}),
            self._step("table.mergeTables", ["source"], {"keyPairs": [], "joinKind": "inner", "nestedColumnName": "Nested"}),
            self._step("source.workbookTable", [], {"sourceId": "src", "url": "https://example.test"}),
            self._step("table.addColumn", ["source"], {
                "newColumnName": "X", "dataType": "any", "onEvaluationError": "block",
                "expression": {"kind": "functionCall", "function": "web.fetch", "args": [{"kind": "literal", "valueType": "text", "value": "secret"}]},
            }),
        ]
        for step in invalid:
            self.assertFalse(self._matches(self._draft(step), self.schema), step["operationType"])


class CodexTypedRunnerFailureTests(unittest.TestCase):
    def test_failure_classifier_uses_stable_sanitized_codes(self) -> None:
        cases = {
            "invalid_json_schema: secret-cell-value": "CODEX_SCHEMA_INVALID",
            "ERROR authentication required secret-cell-value": "CODEX_AUTH_REQUIRED",
            "HTTP 429 too many requests secret-cell-value": "CODEX_RATE_LIMITED",
            "exceeded retry limit, last status: 429 Too Many Requests": "CODEX_RATE_LIMITED",
            "transport broke secret-cell-value": "CODEX_FAILED",
        }
        for stderr, expected in cases.items():
            code, detail = _codex_failure_code(stderr)
            self.assertEqual(code, expected)
            self.assertNotIn("secret-cell-value", detail)

    @patch("pbip_assistant.adapters.codex.typed.find_codex_executable", return_value="codex")
    @patch("pbip_assistant.adapters.codex.typed.subprocess.run")
    def test_runner_maps_invalid_schema_without_exposing_stderr(self, run, _find) -> None:
        run.return_value = SimpleNamespace(
            returncode=1, stdout="", stderr="invalid_json_schema secret-cell-value",
        )
        with self.assertRaises(InputError) as caught:
            CodexTypedRunner().propose({"operationCatalog": sorted(OPERATION_ARITY)})
        self.assertEqual(caught.exception.code, "CODEX_SCHEMA_INVALID")
        self.assertNotIn("secret-cell-value", str(caught.exception))

    @patch("pbip_assistant.adapters.codex.typed.find_codex_executable", return_value="codex")
    @patch("pbip_assistant.adapters.codex.typed.subprocess.run")
    def test_runner_returns_valid_json_object(self, run, _find) -> None:
        expected = {
            "summary": "Không cần biến đổi.", "questions": [], "assumptions": [], "warnings": [],
            "steps": [], "finalOutputRef": None,
        }
        run.return_value = SimpleNamespace(returncode=0, stdout=json.dumps(expected), stderr="")
        self.assertEqual(CodexTypedRunner().propose({"operationCatalog": []}), expected)
        instruction = run.call_args.kwargs["input"]
        self.assertIn("table.mergeTables creates a nested table column", instruction)
        self.assertIn("table.expandTableColumn", instruction)


if __name__ == "__main__":
    unittest.main()
