from __future__ import annotations

import base64
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from pbip_assistant.errors import InputError
from pbip_assistant.excel_connector import PowerShellExcelRunner, apply_export_to_copy, decode_workbook_export
from pbip_assistant.excel_plan import create_fixture_plan
from tests.test_excel_plan import FIXTURE_ROOT, office_snapshot


class FakeExcelRunner:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows
        self.requests: list[dict] = []

    def apply(self, request: dict) -> dict:
        self.requests.append(request)
        return {
            "ok": True,
            "connector": "fake",
            "excelVersion": "test",
            "calculationState": "done",
            "changedTargets": [operation["target"] for operation in request["operations"]],
            "formulas": {operation["targetColumn"]: operation["formula"] for operation in request["operations"]},
            "rows": self.rows,
            "formulaErrors": [],
        }


class ExcelCopyCoordinatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source = Path(self.temp.name) / "excel_mcp_sales_input.xlsx"
        self.payload = (FIXTURE_ROOT / self.source.name).read_bytes()
        self.source.write_bytes(self.payload)
        self.manifest = json.loads((FIXTURE_ROOT / "manifest.json").read_text(encoding="utf-8"))
        self.workbook = office_snapshot(self.source)
        self.plan = create_fixture_plan(self.manifest["prompt"], self.workbook)

    def test_decode_export_rejects_invalid_payload(self) -> None:
        self.assertEqual(decode_workbook_export(base64.b64encode(self.payload).decode("ascii")), self.payload)
        for value, code in (("not-base64", "WORKBOOK_EXPORT_INVALID"), (base64.b64encode(b"plain").decode(), "WORKBOOK_EXPORT_INVALID")):
            with self.subTest(value=value), self.assertRaises(InputError) as raised:
                decode_workbook_export(value)
            self.assertEqual(raised.exception.code, code)

    def test_connector_timeout_trace_exposes_only_last_stage(self) -> None:
        trace = PowerShellExcelRunner._last_trace("noise\n[w21] open-copy\n[w21] calculate\n")
        self.assertEqual(trace, "calculate")

    def test_apply_creates_only_copy_and_reconciles_runtime(self) -> None:
        source_hash = hashlib.sha256(self.source.read_bytes()).hexdigest()
        copy_path = self.source.with_name("result.xlsx")
        runner = FakeExcelRunner(self.manifest["expected_rows"])
        result = apply_export_to_copy(
            workbook=self.workbook,
            workbook_bytes=self.payload,
            plan=self.plan,
            runner=runner,
            copy_path_factory=lambda _: copy_path,
        )
        self.assertEqual(result["status"], "excel_runtime_verified")
        self.assertTrue(result["reconciliation"]["matched"])
        self.assertTrue(copy_path.is_file())
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), source_hash)
        self.assertEqual(runner.requests[0]["workbookPath"], str(copy_path.resolve()))
        self.assertNotEqual(runner.requests[0]["workbookPath"], str(self.source.resolve()))
        self.assertEqual([item["id"] for item in runner.requests[0]["operations"]], [
            "op-net-revenue", "op-return-rate", "op-commission", "op-sales-rank",
        ])

    def test_copy_never_overwrites_existing_destination(self) -> None:
        copy_path = self.source.with_name("existing.xlsx")
        copy_path.write_bytes(b"keep-me")
        runner = FakeExcelRunner(self.manifest["expected_rows"])
        with self.assertRaises(InputError) as raised:
            apply_export_to_copy(
                workbook=self.workbook,
                workbook_bytes=self.payload,
                plan=self.plan,
                runner=runner,
                copy_path_factory=lambda _: copy_path,
            )
        self.assertEqual(raised.exception.code, "COPY_EXISTS")
        self.assertEqual(copy_path.read_bytes(), b"keep-me")
        self.assertFalse(runner.requests)

    def test_runtime_mismatch_is_not_marked_verified(self) -> None:
        rows = json.loads(json.dumps(self.manifest["expected_rows"]))
        rows[0]["Net Revenue"] = -1
        result = apply_export_to_copy(
            workbook=self.workbook,
            workbook_bytes=self.payload,
            plan=self.plan,
            runner=FakeExcelRunner(rows),
            copy_path_factory=lambda source: source.with_name("mismatch.xlsx"),
        )
        self.assertEqual(result["status"], "runtime_failed")
        self.assertFalse(result["reconciliation"]["matched"])

    def test_changed_preview_is_blocked_before_copy_or_runner(self) -> None:
        changed = deepcopy(self.workbook)
        sales = next(table for table in changed["tables"] if table["name"] == "SalesTable")
        sales["rows"][0][4] = -1
        copy_path = self.source.with_name("must-not-exist.xlsx")
        runner = FakeExcelRunner(self.manifest["expected_rows"])
        with self.assertRaises(InputError) as raised:
            apply_export_to_copy(
                workbook=changed,
                workbook_bytes=self.payload,
                plan=self.plan,
                runner=runner,
                copy_path_factory=lambda _: copy_path,
            )
        self.assertEqual(raised.exception.code, "SOURCE_CHANGED")
        self.assertFalse(copy_path.exists())
        self.assertFalse(runner.requests)

    def test_destination_must_remain_beside_source(self) -> None:
        outside = Path(self.temp.name).parent / "outside.xlsx"
        with self.assertRaises(InputError) as raised:
            apply_export_to_copy(
                workbook=self.workbook,
                workbook_bytes=self.payload,
                plan=self.plan,
                runner=FakeExcelRunner(self.manifest["expected_rows"]),
                copy_path_factory=lambda _: outside,
            )
        self.assertEqual(raised.exception.code, "DESTINATION_UNSAFE")


if __name__ == "__main__":
    unittest.main()
