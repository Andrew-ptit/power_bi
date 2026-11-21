"""Bốn hành trình engine synthetic; không phải Office.js/Excel live E2E."""

from contextlib import contextmanager
from copy import deepcopy
from decimal import Decimal
import hashlib
import json
import unittest
from unittest.mock import patch

from pbip_assistant.errors import InputError
from pbip_assistant.sources.assistant_apply import apply_result, read_result_sheet, verify_values_only
from pbip_assistant.sources.assistant_approval import approval_state, issue_approval
from pbip_assistant.sources.assistant_brief import build_brief
from pbip_assistant.sources.assistant_decisions import build_decisions, freeze_blocked
from pbip_assistant.sources.assistant_pack import load_pack
from pbip_assistant.sources.assistant_preview import temp_workspace
from pbip_assistant.sources.assistant_reconcile import assert_approvable
from pbip_assistant.sources.assistant_record import detect_stale, record_hash
from pbip_assistant.sources.assistant_spec import build_spec
from tests.support.paths import FIXTURES, ROOT
from tests.unit.test_assistant_brief import inputs
from tests.unit.test_assistant_record import build, context
from tests.unit.test_assistant_spec import load


SOURCE = FIXTURES / "source/orders_synthetic.xlsx"


def file_state(paths):
    return {path: (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns,
                   path.stat().st_size) for path in paths}


class AssistantEngineE2ETests(unittest.TestCase):
    @contextmanager
    def preserved(self, scenario):
        root = FIXTURES / "assistant" / scenario
        paths = [SOURCE, root / "wl1_snapshot.json", *sorted((root / "source").rglob("*.csv"))]
        before = file_state(paths)
        directory = None
        try:
            with temp_workspace() as directory:
                self.assertFalse(directory.resolve().is_relative_to(ROOT.resolve()))
                yield directory
        finally:
            if directory is not None:
                self.assertFalse(directory.exists())
            self.assertEqual(file_state(paths), before)

    def positive_flow(self, scenario, dimensions, target):
        with self.preserved(scenario) as directory:
            data = context(scenario)
            assert_approvable(data["reconciliation"])
            golden_apply = load(scenario, "wl6_apply.json")
            spec, preview = data["spec"], data["preview"]
            approval = issue_approval(spec, preview, approved_by="user",
                                      approved_at=golden_apply["approval"]["approvedAt"])
            marker = ("LOCAL_DATA_COPILOT|" + target + "|spec=" + spec["fingerprint"] +
                      "|preview=" + preview["previewHash"] + "|labels=" + ",".join(spec["labels"]))
            source = SOURCE.read_bytes()
            output = apply_result(source, result=data["result"], target_sheet=target, marker=marker,
                labels=spec["labels"], approval=approval, spec=spec, preview=preview,
                applied_at=golden_apply["appliedAt"])
            self.assertEqual(approval_state(approval), {"consumed": True, "singleUse": True})
            self.assertFalse(output["apply"]["workbookSaved"])
            verify_values_only(output["workbook"])
            path = directory / "result.xlsx"
            path.write_bytes(output["workbook"])
            readback = read_result_sheet(path.read_bytes(), target)
            self.assertEqual(readback, data["result"])
            self.assertEqual((len(readback["rows"]), len(readback["columns"])), dimensions)
            index = 4 if scenario == "tp-fin" else 1
            self.assertEqual(sum((row[index] for row in readback["rows"]), Decimal("0")),
                             Decimal(data["reconciliation"]["controlTotalResult"]))
            # Record được ghép sau Apply/read-back thành công trong hành trình caller này.
            record = build(data)
            self.assertFalse(record["stale"])
            self.assertEqual(record["hash"], record_hash(record))
            self.assertEqual(record["steps"], spec["steps"])
            self.assertEqual(record["snapshot"]["sourceFingerprint"], output["apply"]["source"]["before"])
            self.assertIsNone(detect_stale(record, current_snapshot=data["snapshot"],
                                         current_decisions=data["decisions"],
                                         current_source_evidence=data["source_evidence"]))
            audit = directory / "record.json"
            audit.write_text(json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                             encoding="utf-8", newline="\n")
            self.assertEqual(record_hash(json.loads(audit.read_text(encoding="utf-8"))), record["hash"])
            self.assertEqual({item.name for item in directory.iterdir()}, {"result.xlsx", "record.json"})
            return data, record

    def test_t_e2e_fin_full_wl1_through_record_bytes_and_source_preservation(self):
        data, record = self.positive_flow("tp-fin", (23, 9), "PnL_Result")
        self.assertFalse(data["data"][2]["pack"]["genericMode"])
        self.assertTrue(data["reconciliation"]["passed"])
        self.assertEqual([len(record[key]) for key in ("decisions", "assumptions", "steps", "reconciliations")],
                         [8, 5, 14, 1])

    def test_t_e2e_sales_generic_success_with_not_applicable_bridge(self):
        data, record = self.positive_flow("tp-sales", (4, 4), "Sales_Result")
        self.assertTrue(data["data"][2]["pack"]["genericMode"])
        self.assertTrue(data["data"][2]["pack"]["notice"])
        self.assertFalse(data["reconciliation"]["bridge"]["applicable"])
        self.assertTrue(data["reconciliation"]["passed"])
        self.assertEqual([len(record[key]) for key in ("decisions", "assumptions", "steps", "reconciliations")],
                         [4, 3, 10, 1])

    def test_t_e2e_unknown_three_unresolved_policies_never_freeze_or_choose_for_user(self):
        with self.preserved("tp-fin") as directory:
            data = inputs("tp-fin")
            unresolved = {"SP-1", "SP-2", "SP-3"}
            brief = build_brief(data[0]["tables"], data[1], data[2], data[3],
                                "Báo cáo synthetic, người dùng chưa chắc ba policy.",
                                policy_unresolved=unresolved)
            problems = {problem["id"]: problem for problem in brief["subProblems"]}
            declared = {policy["subProblemId"]: policy["status"] for policy in data[3]["policies"]}
            for identifier in unresolved:
                self.assertEqual(problems[identifier]["status"], declared[identifier])
                self.assertIsNone(problems[identifier]["chosenOptionId"])
                self.assertEqual({option["id"] for option in problems[identifier]["options"]}, {"A", "B"})
            self.assertEqual({item["id"] for item in brief["scenarios"]}, {"A", "B"})
            self.assertIsNotNone(brief["delta"])
            self.assertTrue(brief["assumptions"])
            self.assertIn("unverified", brief["labels"])
            choices = {key: "A" for key, problem in problems.items()
                       if key not in unresolved and problem["status"] != "missing_data"}
            acks = {key: "out_of_scope" for key, problem in problems.items() if problem["status"] == "missing_data"}
            decisions = build_decisions(brief, choices=choices, acknowledgements=acks,
                decision_metadata={"decidedBy": "user", "decidedAt": "2026-10-29T10:00:00+07:00"})
            self.assertTrue(freeze_blocked(brief, decisions)["blocked"])
            self.assertFalse(unresolved & {entry["subProblemId"] for entry in decisions["decisions"]})
            with self.assertRaises(InputError) as caught:
                build_spec(brief, decisions, data[3], created_at="2026-10-29T10:01:00+07:00")
            self.assertEqual(caught.exception.code, "AF_MISSING_DATA")
            self.assertEqual(list(directory.iterdir()), [])

    def test_t_e2e_nopack_fin_is_fail_closed_as_user_confirmed_without_fake_finance(self):
        # Người dùng chốt negative case; fallback generic trên FIN chưa được engine hỗ trợ.
        with self.preserved("tp-fin") as directory:
            data = inputs("tp-fin")
            generic = load_pack("generic")
            self.assertFalse(data[2]["pack"]["genericMode"])
            self.assertEqual(data[2]["pack"]["id"], "fin-pl-v1")
            self.assertIsNone(data[2]["pack"]["notice"])
            before = deepcopy(data[2])
            with patch("pbip_assistant.sources.assistant_brief.measure_set",
                       side_effect=AssertionError("Không được tính/bịa số finance khi pack sai")):
                with self.assertRaises(InputError) as caught:
                    build_brief(data[0]["tables"], data[1], data[2], generic,
                                "Không có finance pack trong kịch bản synthetic.")
            self.assertEqual(caught.exception.code, "AF_BRIEF_INVALID")
            self.assertEqual(data[2], before)
            self.assertEqual(list(directory.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
