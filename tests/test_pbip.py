import tempfile
import unittest
from pathlib import Path

from pbip_assistant.errors import InputError
from pbip_assistant.pbip import create_snapshot, inventory_pbip, snapshot_matches
from tests.fixtures import make_pbip, make_xlsx


class PbipInventoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_inventory_modern_pbir_and_tmdl(self):
        result = inventory_pbip(make_pbip(self.root / "Retail"))
        self.assertEqual(result["reports"][0]["format"], "PBIR")
        self.assertFalse(result["reports"][0]["patch_eligible"])
        self.assertEqual(result["semantic_models"][0]["format"], "TMDL")
        self.assertEqual(result["reports"][0]["schema_validation"], "not_run")
        self.assertEqual(result["patch_readiness"], "inventory_only")

    def test_legacy_report_is_read_only_inventory(self):
        result = inventory_pbip(make_pbip(self.root / "Legacy", legacy=True))
        self.assertEqual(result["reports"][0]["format"], "PBIR-legacy")
        self.assertFalse(result["reports"][0]["external_edit_candidate"])

    def test_snapshot_detects_excel_and_model_changes(self):
        project = make_pbip(self.root / "Retail")
        excel = make_xlsx(self.root / "Sales.xlsx")
        snapshot = create_snapshot(project, [excel])
        self.assertTrue(snapshot_matches(snapshot))
        excel.write_bytes(excel.read_bytes() + b"changed")
        self.assertFalse(snapshot_matches(snapshot))

    def test_snapshot_detects_pbip_metadata_change(self):
        project = make_pbip(self.root / "Retail")
        excel = make_xlsx(self.root / "Sales.xlsx")
        snapshot = create_snapshot(project, [excel])
        (project / "Retail.SemanticModel" / "definition" / "model.tmdl").write_text("model Changed\n", encoding="utf-8")
        self.assertFalse(snapshot_matches(snapshot))

    def test_missing_pbip_file_is_rejected(self):
        project = make_pbip(self.root / "Retail")
        (project / "Retail.pbip").unlink()
        with self.assertRaises(InputError) as caught:
            inventory_pbip(project)
        self.assertEqual(caught.exception.code, "INVALID_PBIP")

    def test_symlink_inside_project_is_rejected(self):
        project = make_pbip(self.root / "Retail")
        link = project / "external.txt"
        try:
            link.symlink_to(self.root / "outside.txt")
        except OSError:
            self.skipTest("Symlinks are not available on this machine")
        with self.assertRaises(InputError) as caught:
            inventory_pbip(project)
        self.assertEqual(caught.exception.code, "UNSAFE_PBIP_PATH")


if __name__ == "__main__":
    unittest.main()
