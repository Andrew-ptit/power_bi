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

@unittest.skipUnless(shutil.which("powershell.exe"), "Windows PowerShell is unavailable")
class CustomXmlPackageLinkageTests(unittest.TestCase):
    def test_excel_package_has_complete_custom_xml_relationships_and_content_type(self) -> None:
        source_hash = hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
        xml, expected_hash = build_problem_chain_xml(sample_document())
        with tempfile.TemporaryDirectory(prefix="pqpc-adversarial-") as folder:
            folder_path = Path(folder)
            working = folder_path / "working.xlsx"
            save_as = folder_path / "save-as.xlsx"
            shutil.copyfile(FIXTURE, working)
            result = invoke_com(working, save_as, [xml])
            self.assertTrue(result["excelPidExited"])
            self.assertFalse(result["cleanupForced"])

            for workbook in (working, save_as):
                with self.subTest(workbook=workbook.name), ZipFile(workbook) as archive:
                    inspection = inspect_problem_chain_parts(workbook)
                    self.assertEqual(1, inspection["count"])
                    part = inspection["parts"][0]
                    self.assertEqual(expected_hash, part["historyHash"])

                    item_name = part["partName"]
                    suffix = item_name.removeprefix("customXml/item").removesuffix(".xml")
                    props_name = f"customXml/itemProps{suffix}.xml"
                    rels_name = f"customXml/_rels/item{suffix}.xml.rels"
                    self.assertIn(props_name, archive.namelist())
                    self.assertIn(rels_name, archive.namelist())

                    rels = ET.fromstring(archive.read(rels_name))
                    relationships = rels.findall(f"{{{PACKAGE_REL_NS}}}Relationship")
                    self.assertEqual(1, len(relationships))
                    self.assertEqual(CUSTOM_XML_PROPS_REL, relationships[0].attrib["Type"])
                    self.assertEqual(f"itemProps{suffix}.xml", relationships[0].attrib["Target"])

                    content_types = ET.fromstring(archive.read("[Content_Types].xml"))
                    overrides = {
                        node.attrib["PartName"]: node.attrib["ContentType"]
                        for node in content_types.findall(f"{{{CONTENT_TYPE_NS}}}Override")
                    }
                    self.assertEqual(
                        CUSTOM_XML_PROPS_TYPE,
                        overrides.get(f"/customXml/itemProps{suffix}.xml"),
                    )

        self.assertEqual(source_hash, hashlib.sha256(FIXTURE.read_bytes()).hexdigest())

