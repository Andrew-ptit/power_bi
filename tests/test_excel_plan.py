from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from pbip_assistant.errors import InputError
from pbip_assistant.excel_plan import OPERATIONS, create_fixture_plan, local_source_path, validate_current_plan
from pbip_assistant.xlsx import profile_workbook


FIXTURE_ROOT = Path(__file__).with_name("fixtures_excel_mcp")


def office_snapshot(path: Path) -> dict:
    profile = profile_workbook(path, include_preview=True, preview_limit=20)
    tables = []
    for sheet in profile["sheets"]:
        rows = sheet.get("preview", {}).get("rows", [])
        for table in sheet["tables"]:
            tables.append({
                "sheet": sheet["name"],
                "name": table["name"],
                "headers": table["columns"],
                "rows": rows,
            })
    return {
        "name": path.name,
        "url": path.resolve().as_uri(),
        "activeSheet": "Sales",
        "tables": tables,
    }


class ExcelFixturePlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source = Path(self.temp.name) / "excel_mcp_sales_input.xlsx"
        self.source.write_bytes((FIXTURE_ROOT / self.source.name).read_bytes())
        self.prompt = json.loads((FIXTURE_ROOT / "manifest.json").read_text(encoding="utf-8"))["prompt"]
        self.workbook = office_snapshot(self.source)

    def test_fixture_plan_is_review_ready_and_preview_matches_manifest(self) -> None:
        plan = create_fixture_plan(self.prompt, self.workbook)
        manifest = json.loads((FIXTURE_ROOT / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(plan["status"], "review_ready")
        self.assertEqual([item["id"] for item in plan["operations"]], [item.id for item in OPERATIONS])
        self.assertEqual(plan["preview"]["label"], "Simulated preview — chưa ghi Excel")
        columns = plan["preview"]["afterColumns"]
        rows = [dict(zip(columns, row, strict=True)) for row in plan["preview"]["afterRows"]]
        self.assertEqual(rows, manifest["expected_rows"])
        self.assertFalse(plan["hardBlockers"])

    def test_plan_blocks_missing_schema_and_unsaved_workbook(self) -> None:
        missing = json.loads(json.dumps(self.workbook))
        missing["tables"] = [table for table in missing["tables"] if table["name"] != "CommissionTable"]
        missing["url"] = ""
        plan = create_fixture_plan(self.prompt, missing)
        self.assertEqual(plan["status"], "blocked")
        self.assertEqual({item["code"] for item in plan["hardBlockers"]}, {"SCHEMA_MISMATCH", "WORKBOOK_UNSAVED"})
        self.assertIsNone(plan["preview"])

    def test_plan_rejects_long_prompt_and_remote_path(self) -> None:
        with self.assertRaises(InputError) as prompt_error:
            create_fixture_plan("x" * 4001, self.workbook)
        self.assertEqual(prompt_error.exception.code, "PROMPT_LIMIT")
        remote = dict(self.workbook, url="https://tenant.sharepoint.com/book.xlsx")
        with self.assertRaises(InputError) as path_error:
            local_source_path(remote)
        self.assertEqual(path_error.exception.code, "REMOTE_WORKBOOK_UNSUPPORTED")

    def test_approval_is_bound_to_exact_plan_and_ordered_operations(self) -> None:
        plan = create_fixture_plan(self.prompt, self.workbook)
        expected_ids = [item.id for item in OPERATIONS]
        validated, workbook = validate_current_plan(
            prompt=self.prompt,
            workbook=self.workbook,
            snapshot_id=plan["snapshotId"],
            plan_revision_id=plan["planRevisionId"],
            operation_ids=expected_ids,
        )
        self.assertEqual(validated["planRevisionId"], plan["planRevisionId"])
        self.assertEqual(workbook["name"], self.source.name)
        with self.assertRaises(InputError) as stale:
            validate_current_plan(
                prompt=self.prompt + " changed",
                workbook=self.workbook,
                snapshot_id=plan["snapshotId"],
                plan_revision_id=plan["planRevisionId"],
                operation_ids=expected_ids,
            )
        self.assertEqual(stale.exception.code, "PLAN_STALE")
        with self.assertRaises(InputError) as scope:
            validate_current_plan(
                prompt=self.prompt,
                workbook=self.workbook,
                snapshot_id=plan["snapshotId"],
                plan_revision_id=plan["planRevisionId"],
                operation_ids=expected_ids[:-1],
            )
        self.assertEqual(scope.exception.code, "APPROVAL_SCOPE")


if __name__ == "__main__":
    unittest.main()
