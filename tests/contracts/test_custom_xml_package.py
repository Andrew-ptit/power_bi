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

class ProblemChainPackageOracleUnitTests(unittest.TestCase):
    def test_unicode_round_trip_uses_canonical_payload_hash_and_no_samples(self) -> None:
        document = sample_document()
        sentinel = "SAMPLE_CELL_MUST_NOT_BE_STORED"
        xml, expected_hash = build_problem_chain_xml(document)
        parsed = parse_problem_chain_xml(xml)
        self.assertEqual(parsed["document"], document)
        self.assertEqual(parsed["historyHash"], expected_hash)
        self.assertNotIn(sentinel, xml)
        self.assertEqual(parsed["document"]["sampleStore"], {})
        self.assertFalse(parsed["document"]["samplePersistence"]["enabled"])

    def test_parser_rejects_corruption_noncanonical_json_and_wrong_hash(self) -> None:
        document = sample_document()
        xml, _ = build_problem_chain_xml(document)
        cases = [
            (xml.replace("base64", "base64!") , "PQPC_DOCUMENT_INVALID"),
            (xml.replace("sha256:", "sha256:bad"), "PQPC_HASH_MISMATCH"),
            (f'<!DOCTYPE x [<!ENTITY e SYSTEM "file:///c:/secret">]>{xml}', "PQPC_DOCUMENT_INVALID"),
        ]
        for value, code in cases:
            with self.subTest(code=code), self.assertRaises(PackageOracleError) as raised:
                parse_problem_chain_xml(value)
            self.assertEqual(raised.exception.code, code)

        pretty = json.dumps(document, ensure_ascii=False, indent=2).encode("utf-8")
        encoded = base64.b64encode(pretty).decode("ascii")
        noncanonical = xml.replace(
            base64.b64encode(canonical_json_bytes(document)).decode("ascii"), encoded
        )
        with self.assertRaises(PackageOracleError) as raised:
            parse_problem_chain_xml(noncanonical)
        self.assertEqual(raised.exception.code, "PQPC_DOCUMENT_INVALID")

    def test_limits_reject_51_revisions_and_more_than_two_mib(self) -> None:
        too_many = sample_document()
        too_many["revisions"] = [deepcopy(too_many["revisions"][0]) for _ in range(51)]
        with self.assertRaises(PackageOracleError) as raised:
            validate_document_limits(too_many)
        self.assertEqual(raised.exception.code, "PQPC_HISTORY_LIMIT")

        too_large = sample_document("x" * MAX_DOCUMENT_BYTES)
        with self.assertRaises(PackageOracleError) as raised:
            validate_document_limits(too_large)
        self.assertEqual(raised.exception.code, "PQPC_HISTORY_LIMIT")

    def test_package_oracle_rejects_duplicate_namespace_parts(self) -> None:
        first, _ = build_problem_chain_xml(sample_document("first"))
        second, _ = build_problem_chain_xml(sample_document("second"))
        with tempfile.TemporaryDirectory(prefix="pqpc-duplicate-") as folder:
            target = Path(folder) / "duplicate.xlsx"
            rewrite_package(FIXTURE, target, {
                "customXml/item91.xml": first.encode("utf-8"),
                "customXml/item92.xml": second.encode("utf-8"),
            })
            with self.assertRaises(PackageOracleError) as raised:
                inspect_problem_chain_parts(target)
            self.assertEqual(raised.exception.code, "PQPC_DUPLICATE_XML_PART")

    def test_semantic_snapshot_is_independent_of_custom_xml_parts(self) -> None:
        xml, _ = build_problem_chain_xml(sample_document())
        with tempfile.TemporaryDirectory(prefix="pqpc-semantic-") as folder:
            target = Path(folder) / "with-custom-xml.xlsx"
            rewrite_package(FIXTURE, target, {"customXml/item91.xml": xml.encode("utf-8")})
            self.assertEqual(semantic_workbook_snapshot(target), semantic_workbook_snapshot(FIXTURE))

