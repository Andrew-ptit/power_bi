from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile

from examples.excel_mcp_fixtures import (
    COMMISSION_ROWS,
    EXPECTED_ROWS,
    SALES_ROWS,
    build_manifest,
    build_workbook,
    generate,
)
from pbip_assistant.xlsx import profile_workbook


FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "excel"


class ExcelMcpFixtureTests(unittest.TestCase):
    def test_committed_fixture_is_deterministic_and_matches_manifest(self) -> None:
        expected_bytes = build_workbook()
        committed = (FIXTURE_ROOT / "excel_mcp_sales_input.xlsx").read_bytes()
        manifest = json.loads((FIXTURE_ROOT / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(committed, expected_bytes)
        self.assertEqual(manifest, build_manifest(expected_bytes))
        self.assertEqual(manifest["workbook"]["sha256"], hashlib.sha256(committed).hexdigest())
        with tempfile.TemporaryDirectory() as folder:
            generated_manifest = generate(Path(folder))
            self.assertEqual(generated_manifest.read_bytes(), (FIXTURE_ROOT / "manifest.json").read_bytes())
            self.assertEqual((Path(folder) / "excel_mcp_sales_input.xlsx").read_bytes(), committed)

    def test_current_read_only_parser_profiles_both_excel_mcp_sheets(self) -> None:
        workbook_path = FIXTURE_ROOT / "excel_mcp_sales_input.xlsx"
        before = hashlib.sha256(workbook_path.read_bytes()).hexdigest()
        result = profile_workbook(workbook_path, include_preview=True, preview_limit=20)
        by_name = {sheet["name"]: sheet for sheet in result["sheets"]}
        self.assertEqual(set(by_name), {"Sales", "Dim_Commission"})
        self.assertEqual(by_name["Sales"]["row_count"], 6)
        self.assertEqual(by_name["Dim_Commission"]["row_count"], 3)
        self.assertEqual(by_name["Sales"]["tables"][0]["name"], "SalesTable")
        self.assertEqual(by_name["Dim_Commission"]["tables"][0]["name"], "CommissionTable")
        self.assertTrue(all(sheet["mapping_ready"] for sheet in by_name.values()))
        self.assertEqual(by_name["Sales"]["formula_cache"]["cell_count"], 0)
        self.assertEqual(hashlib.sha256(workbook_path.read_bytes()).hexdigest(), before)

    def test_source_has_no_formula_and_manifest_has_four_control_outputs(self) -> None:
        workbook_path = FIXTURE_ROOT / "excel_mcp_sales_input.xlsx"
        with ZipFile(workbook_path) as archive:
            worksheet_xml = b"".join(
                archive.read(name)
                for name in archive.namelist()
                if name.startswith("xl/worksheets/sheet") and name.endswith(".xml")
            )
        self.assertNotIn(b"<f", worksheet_xml)
        manifest = json.loads((FIXTURE_ROOT / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(len(manifest["expected_operations"]), 4)
        self.assertEqual(manifest["expected_rows"], list(EXPECTED_ROWS))
        self.assertIn("Dim_Commission", manifest["prompt"])

    def test_control_outputs_follow_declared_business_rules(self) -> None:
        net_revenues = [row[4] - row[5] - row[6] for row in SALES_ROWS]
        sorted_net = sorted(net_revenues)
        calculated = []
        for row, net_revenue in zip(SALES_ROWS, net_revenues, strict=True):
            rate = max(rate for minimum, rate in COMMISSION_ROWS if minimum <= net_revenue)
            percentile = sorted_net.index(net_revenue) / (len(sorted_net) - 1)
            rank = "Top 10%" if percentile >= 0.9 else "Top 20%" if percentile >= 0.8 else "Bottom"
            calculated.append({
                "SaleID": row[0],
                "Net Revenue": net_revenue,
                "Return Rate": round(row[8] / row[7], 10) if row[7] else 0,
                "Commission Value": round(net_revenue * rate, 10),
                "Sales Rank": rank,
            })
        self.assertEqual(calculated, list(EXPECTED_ROWS))


if __name__ == "__main__":
    unittest.main()
