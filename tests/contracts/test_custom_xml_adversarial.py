from __future__ import annotations
import hashlib
from pathlib import Path
import shutil
import tempfile
import unittest
from xml.etree import ElementTree as ET
from zipfile import ZipFile
from tests.support.oracle import (
    build_problem_chain_xml,
    inspect_problem_chain_parts,
)
from tests.support.custom_xml_runtime import (
    invoke_com,
    sample_document,
)
from tests.support.xml_contract_validator import (
    ContractError,
    MAX_CANONICAL_JSON_BYTES,
    canonical_json,
    compute_review_hash,
    decode_xml,
    encode_xml,
    validate_document,
)
from tests.support.xml_contract_fixtures import (
    document,
)
ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "excel" / "excel_mcp_sales_input.xlsx"
PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
CONTENT_TYPE_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
CUSTOM_XML_PROPS_REL = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/customXmlProps"
)
CUSTOM_XML_PROPS_TYPE = (
    "application/vnd.openxmlformats-officedocument.customXmlProperties+xml"
)

class CustomXmlAdversarialContractTests(unittest.TestCase):
    def assert_contract_error(self, code: str, action) -> ContractError:
        with self.assertRaises(ContractError) as caught:
            action()
        self.assertEqual(code, caught.exception.code)
        return caught.exception

    def test_default_policy_rejects_sample_rows_hidden_inside_source_metadata(self) -> None:
        value = document()
        sentinel = "CELL_SENTINEL_MUST_NOT_ENTER_WORKBOOK"
        value["revisions"][0]["sources"][0]["sampleRows"] = [[sentinel]]
        value["revisions"][0]["reviewHash"] = compute_review_hash(value["revisions"][0])

        self.assert_contract_error("PQPC_DOCUMENT_INVALID", lambda: validate_document(value))

    def test_enabled_sample_store_enforces_hash_shape_and_twenty_by_two_hundred_bound(self) -> None:
        value = document()
        value["samplePersistence"].update(
            enabled=True,
            warningAcceptedAt="2026-10-13T21:00:00+07:00",
        )
        value["sampleStore"] = {
            "not-a-content-hash": {
                "rows": [[f"row-{row}"] for row in range(21)],
            }
        }

        self.assert_contract_error("PQPC_DOCUMENT_INVALID", lambda: validate_document(value))

    def test_canonical_size_boundary_accepts_exact_limit_and_rejects_one_more_byte(self) -> None:
        exact = document()
        bucket = exact["revisions"][0]["validationAtCreation"]
        bucket["padding"] = ""
        padding = MAX_CANONICAL_JSON_BYTES - len(canonical_json(exact))
        self.assertGreater(padding, 0)
        bucket["padding"] = "x" * padding
        self.assertEqual(MAX_CANONICAL_JSON_BYTES, len(canonical_json(exact)))
        validate_document(exact)

        over = document()
        over_bucket = over["revisions"][0]["validationAtCreation"]
        over_bucket["padding"] = ""
        over_padding = MAX_CANONICAL_JSON_BYTES + 1 - len(canonical_json(over))
        over_bucket["padding"] = "x" * over_padding
        self.assertEqual(MAX_CANONICAL_JSON_BYTES + 1, len(canonical_json(over)))
        self.assert_contract_error("PQPC_HISTORY_LIMIT", lambda: validate_document(over))

    def test_forbidden_derived_fields_are_rejected_at_arbitrary_depth(self) -> None:
        for field in ("branchTip", "latestRevisionId"):
            with self.subTest(field=field):
                value = document()
                value["revisions"][0]["validationAtCreation"] = {
                    "nested": [{"deeper": {field: "rev_000000000000000000000001"}}]
                }
                self.assert_contract_error(
                    "PQPC_DOCUMENT_INVALID", lambda value=value: validate_document(value)
                )

    def test_dtd_and_entity_variants_are_rejected_before_parsing(self) -> None:
        valid = encode_xml(document())
        for prefix in (
            '<!DoCtYpE x [<!EnTiTy leak SYSTEM "file:///c:/secret">]>',
            '<!\nDOCTYPE x [<!\nENTITY leak SYSTEM "file:///c:/secret">]>',
        ):
            with self.subTest(prefix=prefix):
                self.assert_contract_error(
                    "PQPC_DOCUMENT_INVALID", lambda prefix=prefix: decode_xml(prefix + valid)
                )

