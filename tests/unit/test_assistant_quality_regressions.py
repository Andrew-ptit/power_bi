"""Adversarial Assistant quality cases with independent, synthetic oracles."""

from copy import deepcopy
import json
import tempfile
import unittest

from pbip_assistant.sources.assistant_session import AssistantSessionStore
from tests.support.assistant_flow import AssistantBranchPlanner


class DateGroupingPlanner:
    """No computed numbers: describe conversion and grouping for the real engine."""

    def propose(self, payload):
        response = AssistantBranchPlanner().propose(payload)
        for branch in response["branches"]:
            source = branch["plan"]["steps"][0]
            branch["plan"].update(steps=[source, {
                "clientRef": "typed", "variableName": "Typed", "actionDescription": "Convert date and amount",
                "operationType": "table.changeTypes", "inputs": ["source"],
                "parameters": {"conversions": [{"column": "Date", "targetType": "date"},
                                                {"column": "Amount", "targetType": "number"}]},
            }, {
                "clientRef": "grouped", "variableName": "Grouped", "actionDescription": "Sum by date",
                "operationType": "table.groupRows", "inputs": ["typed"],
                "parameters": {"keyColumns": ["Date"], "aggregations": [
                    {"function": "sum", "column": "Amount", "outputName": "Total"}]},
            }], finalOutputRef="grouped")
        return response


class WideFilteringPlanner:
    """Short draft whose repeated derived contracts exceed the card budget."""

    def propose(self, payload):
        response = AssistantBranchPlanner().propose(payload)
        for branch in response["branches"]:
            source = branch["plan"]["steps"][0]
            branch["controlTotal"] = None
            branch["plan"].update(steps=[source, {
                "clientRef": "positive", "variableName": "Positive", "actionDescription": "Keep positive amounts",
                "operationType": "table.filterRows", "inputs": ["source"],
                "parameters": {"predicate": {"kind": "compare", "operator": "gt",
                    "left": {"kind": "columnRef", "column": "Amount"},
                    "right": {"kind": "literal", "valueType": "text", "value": "0"}}},
            }, {
                "clientRef": "sorted", "variableName": "Sorted", "actionDescription": "Sort descending by amount",
                "operationType": "table.sortRows", "inputs": ["positive"],
                "parameters": {"keys": [{"column": "Amount", "direction": "descending"}]},
            }, {
                "clientRef": "unique", "variableName": "Unique", "actionDescription": "Keep distinct complete rows",
                "operationType": "table.distinctRows", "inputs": ["sorted"],
                "parameters": {"scope": "all"},
            }], finalOutputRef="unique")
        return response


class AssistantQualityRegressionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.store = AssistantSessionStore()
        self.addCleanup(self.store.close)
        self.store.bind_root(self.directory.name)

    def prepare(self, dates=("45292", "45293")):
        # Numeric date strings model the pre-normalization Office.js boundary.
        # The executor deliberately does not guess their epoch; that is the
        # workbook reader's responsibility, exercised separately in JS/live QA.
        self.store.ingest([{"kind": "workbook", "mode": "compute", "payload": {
            "name": "Transactions", "origin": "Workbook!Synthetic!Transactions", "sheet": "Synthetic",
            "table": True, "header": ["Date", "Amount", "PrivateText"],
            "rows": [[dates[0], "10", "SYNTHETIC_PRIVATE_CELL_A"],
                     [dates[1], "20", "SYNTHETIC_PRIVATE_CELL_B"]],
            "sampleOrdinals": [0, 1], "totalRows": 2,
        }}])
        self.store.understand()
        return self.store.plan_draft("Sum amount by date", [], True, DateGroupingPlanner())

    def test_date_conversion_data_loss_warning_survives_public_projection(self):
        drafted = self.prepare()
        response = self.store.run_branches(drafted["planningHash"])
        public = response["branches"][0]
        # Independent arithmetic oracle: 10 + 20 = 30. A matching sum alone
        # cannot prove that the two distinct date groups were preserved.
        self.assertEqual(public["rows"], [[None, "30"]])
        self.assertTrue(public["reconciliation"]["passed"])
        private = self.store._branch_results["A"]["result"]["warnings"]
        self.assertEqual([warning["code"] for warning in private], ["AF_EXECUTOR_DATE_NULL"])
        self.assertEqual(public.get("warningCount"), 1)
        self.assertEqual([{key: warning[key] for key in ("code", "path")} for warning in public.get("warnings", [])], private)
        self.assertTrue(public["warnings"][0]["message"])

    def test_algorithm_parameters_remain_reviewable_after_execution_and_restore(self):
        drafted = self.prepare(("2024-01-01", "2024-01-02"))
        original = deepcopy(self.store._planning["branches"][0]["plan"])
        response = self.store.run_branches(drafted["planningHash"])
        # Two actual dates must stay separate, even though both branches sum 30.
        self.assertEqual(response["branches"][0]["rows"], [["2024-01-01", "10"], ["2024-01-02", "20"]])
        restored = self.store.state()
        final = next(step for step in original["steps"] if step["stepId"] == original["finalOutputStepId"])
        for branch in (drafted["branches"][0], response["branches"][0], restored["branches"][0]):
            self.assertEqual(branch.get("normalizedSteps"), [{key: value for key, value in step.items()
                if key != "outputContract"} for step in original["steps"]])
            self.assertEqual(branch.get("finalOutputStepId"), original["finalOutputStepId"])
            self.assertEqual(branch.get("finalOutputContract"), final["outputContract"])
            self.assertTrue(branch["steps"])
            encoded = json.dumps(branch["normalizedSteps"])
            self.assertNotIn("sampleRows", encoded)
            self.assertNotIn("SYNTHETIC_PRIVATE_CELL", encoded)
        self.assertEqual(restored["planningHash"], drafted["planningHash"])

    def test_public_algorithm_projection_is_owned_and_excludes_source_samples(self):
        drafted = self.prepare(("2024-01-01", "2024-01-02"))
        expected = deepcopy(self.store._planning["branches"][0]["plan"])
        projected = drafted["branches"][0].get("normalizedSteps")
        self.assertIsNotNone(projected)
        projected[1]["operation"]["parameters"]["conversions"][0]["targetType"] = "text"
        drafted["branches"][0]["finalOutputContract"]["columns"][0]["name"] = "Mutated public schema"
        self.assertEqual(self.store._planning["branches"][0]["plan"], expected)

    def test_public_warnings_never_forward_raw_messages_or_unbound_paths(self):
        drafted = self.prepare()
        self.store.run_branches(drafted["planningHash"])
        result = self.store._branch_results["A"]["result"]
        warning = result["warnings"][0]
        warning["message"] = "SYNTHETIC_PRIVATE_CELL_A"
        warning["row"] = ["SYNTHETIC_PRIVATE_CELL_B"]
        result["warnings"].append({"code": "AF_EXECUTOR_DATE_NULL", "path": "C:/private/source.xlsx"})
        public = self.store.state()["branches"][0]
        self.assertEqual(public.get("warningCount"), 1)
        self.assertEqual(set(public["warnings"][0]), {"code", "path", "message"})
        self.assertNotIn("SYNTHETIC_PRIVATE_CELL", json.dumps(public["warnings"]))
        self.assertNotIn("private/source.xlsx", json.dumps(public["warnings"]))

    def test_valid_hundred_column_plan_keeps_complete_algorithm_within_card_budget(self):
        header = ["Amount", *["Column" + str(index) for index in range(1, 100)]]
        self.store.ingest([{"kind": "workbook", "mode": "compute", "payload": {
            "name": "Transactions", "origin": "Workbook!Synthetic!Transactions", "sheet": "Synthetic",
            "table": True, "header": header, "rows": [["10", *["1"] * 99], ["20", *["2"] * 99]],
            "sampleOrdinals": [0, 1], "totalRows": 2,
        }}])
        self.store.understand()
        drafted = self.store.plan_draft("Keep distinct positive rows sorted by amount", [], True, WideFilteringPlanner())
        plans = [branch["plan"] for branch in self.store._planning["branches"]]
        # The fixture specifically crosses the old budget through repeated
        # derived contracts, while its real algorithm remains short.
        self.assertGreater(len(json.dumps([plan["steps"] for plan in plans]).encode("utf-8")), 64 * 1024)
        self.assertLessEqual(len(json.dumps(drafted, ensure_ascii=False).encode("utf-8")), 64 * 1024)
        executed = self.store.run_branches(drafted["planningHash"])
        self.assertEqual(executed["branches"][0]["rows"], [["20", *["2"] * 99], ["10", *["1"] * 99]])
        for view in (drafted, executed, self.store.state()):
            for branch, original in zip(view["branches"], plans):
                self.assertEqual(branch["normalizedSteps"], [{key: value for key, value in step.items()
                    if key != "outputContract"} for step in original["steps"]])
                final = next(step for step in original["steps"] if step["stepId"] == original["finalOutputStepId"])
                self.assertEqual(branch["finalOutputContract"], final["outputContract"])
                self.assertEqual(branch["finalOutputStepId"], final["stepId"])


if __name__ == "__main__":
    unittest.main()
