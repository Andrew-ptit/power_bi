from __future__ import annotations
import base64
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from zipfile import ZIP_DEFLATED, ZipFile
from tests.support.oracle import (
    MAX_DOCUMENT_BYTES,
    PROBLEM_CHAIN_NAMESPACE,
    PackageOracleError,
    build_problem_chain_xml,
    canonical_json_bytes,
    inspect_problem_chain_parts,
    parse_problem_chain_xml,
    semantic_workbook_snapshot,
    validate_document_limits,
)
from tests.support.custom_xml_runtime import invoke_com, sample_document
ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "excel" / "excel_mcp_sales_input.xlsx"
def rewrite_package(source: Path, target: Path, additions: dict[str, bytes]) -> None:
    with ZipFile(source) as reader, ZipFile(target, "w", ZIP_DEFLATED) as writer:
        for item in reader.infolist():
            if item.filename not in additions:
                writer.writestr(item, reader.read(item.filename))
        for name, payload in additions.items():
            writer.writestr(name, payload)

@unittest.skipUnless(shutil.which("powershell.exe"), "Windows PowerShell is unavailable")
class ProblemChainPackageOracleExcelSmoke(unittest.TestCase):
    def test_excel_com_round_trip_save_as_and_source_preservation(self) -> None:
        source_hash = hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
        before = semantic_workbook_snapshot(FIXTURE)
        xml, expected_hash = build_problem_chain_xml(sample_document())
        with tempfile.TemporaryDirectory(prefix="pqpc-com-") as folder:
            working = Path(folder) / "working.xlsx"
            save_as = Path(folder) / "save_as.xlsx"
            shutil.copyfile(FIXTURE, working)
            result = invoke_com(working, save_as, [xml])
            self.assertEqual(len(result["workingParts"]), 1)
            self.assertEqual(len(result["saveAsParts"]), 1)
            self.assertTrue(result["excelPidExited"])
            self.assertFalse(result["cleanupForced"])
            for workbook in (working, save_as):
                inspection = inspect_problem_chain_parts(workbook)
                self.assertEqual(inspection["count"], 1)
                self.assertEqual(inspection["parts"][0]["historyHash"], expected_hash)
                self.assertEqual(semantic_workbook_snapshot(workbook), before)
        self.assertEqual(hashlib.sha256(FIXTURE.read_bytes()).hexdigest(), source_hash)

