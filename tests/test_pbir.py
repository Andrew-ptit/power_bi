import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from examples.pbip_fixtures import PAGE_ID, VISUAL_ID, make_retail_pbip
from pbip_assistant.pbir import SUPPORTED_SCHEMAS, catalog_pbir


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*") if path.is_file()
    }


class PbirCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)

    def _make(self, variant: str = "modern") -> Path:
        return make_retail_pbip(self.base / variant, variant=variant)

    def test_modern_fixture_passes_pinned_static_gate_without_writes(self):
        root = self._make()
        before = _hashes(root)

        result = catalog_pbir(root)

        self.assertEqual(_hashes(root), before)
        self.assertFalse(result["patch_eligible"])
        self.assertTrue(result["static_patch_candidate"])
        report = result["reports"][0]
        self.assertEqual(report["static_validation"], "static_pass")
        self.assertEqual(report["schema_validation"], "not_run")
        self.assertEqual(report["desktop_validation"], "not_run")
        self.assertEqual(report["dataset_reference"]["target"], "Retail.SemanticModel")
        self.assertEqual(report["pages"][0]["display_name"], "Overview")
        self.assertEqual(report["visuals"][0]["visual_type"], "cardVisual")
        self.assertEqual(report["visuals"][0]["bindings"], [
            {"kind": "measure", "entity": "FactOrders", "property": "Gross Sales"}
        ])

    def test_filter_and_bookmark_catalog_redacts_literal_values(self):
        root = self._make()
        report_root = root / "Retail.Report"
        report_path = report_root / "definition" / "report.json"
        report_doc = json.loads(report_path.read_text(encoding="utf-8"))
        report_doc["filterConfig"] = {"filters": [{
            "field": {"Column": {"Expression": {"SourceRef": {"Entity": "DimCustomer"}}, "Property": "City"}},
            "values": ["Synthetic Secret City"],
        }]}
        _write_json(report_path, report_doc)
        _write_json(report_root / "definition" / "bookmarks" / "bookmarks.json", {
            "$schema": SUPPORTED_SCHEMAS["bookmarks_metadata"],
            "items": [{"name": "south_view"}],
        })
        _write_json(report_root / "definition" / "bookmarks" / "south_view.bookmark.json", {
            "$schema": SUPPORTED_SCHEMAS["bookmark"],
            "displayName": "Synthetic South view",
            "name": "south_view",
            "explorationState": {"activeSection": PAGE_ID, "values": ["Synthetic Secret City"]},
        })

        result = catalog_pbir(root)["reports"][0]

        self.assertFalse(result["patch_eligible"])
        self.assertTrue(result["static_patch_candidate"])
        self.assertEqual(result["bookmarks"][0]["name"], "south_view")
        self.assertTrue(result["bookmarks"][0]["contains_literal_values"])
        self.assertEqual(result["filters"][0]["filter_count"], 1)
        self.assertTrue(result["filters"][0]["contains_literal_values"])
        self.assertNotIn("Synthetic Secret City", json.dumps(result))

    def test_legacy_report_is_view_only(self):
        report = catalog_pbir(self._make("legacy"))["reports"][0]
        self.assertEqual(report["format"], "PBIR-legacy")
        self.assertEqual(report["static_validation"], "view_only")
        self.assertFalse(report["patch_eligible"])
        self.assertIn("PBIR_LEGACY_VIEW_ONLY", {issue["code"] for issue in report["issues"]})

    def test_unknown_schema_is_view_only(self):
        report = catalog_pbir(self._make("unsupported_schema"))["reports"][0]
        self.assertEqual(report["static_validation"], "view_only")
        self.assertFalse(report["patch_eligible"])
        self.assertIn("PBIR_SCHEMA_UNSUPPORTED", {issue["code"] for issue in report["issues"]})

    def test_missing_dataset_binding_is_blocked(self):
        report = catalog_pbir(self._make("missing_binding"))["reports"][0]
        self.assertEqual(report["static_validation"], "blocked")
        self.assertFalse(report["patch_eligible"])
        self.assertIn("PBIR_REQUIRED_FIELD_MISSING", {issue["code"] for issue in report["issues"]})

    def test_data_visual_without_semantic_binding_is_blocked(self):
        root = self._make()
        path = root / "Retail.Report" / "definition" / "pages" / PAGE_ID / "visuals" / VISUAL_ID / "visual.json"
        document = json.loads(path.read_text(encoding="utf-8"))
        document["visual"].pop("query")
        _write_json(path, document)

        report = catalog_pbir(root)["reports"][0]

        self.assertEqual(report["static_validation"], "blocked")
        self.assertIn("PBIR_VISUAL_BINDING_MISSING", {issue["code"] for issue in report["issues"]})

    def test_by_path_outside_project_is_blocked(self):
        root = self._make()
        path = root / "Retail.Report" / "definition.pbir"
        document = json.loads(path.read_text(encoding="utf-8"))
        document["datasetReference"]["byPath"]["path"] = "../../Outside.SemanticModel"
        _write_json(path, document)

        report = catalog_pbir(root)["reports"][0]

        self.assertEqual(report["static_validation"], "blocked")
        self.assertIn("PBIR_DATASET_PATH_OUTSIDE_PROJECT", {issue["code"] for issue in report["issues"]})

    def test_absolute_or_backslash_by_path_is_blocked(self):
        root = self._make()
        path = root / "Retail.Report" / "definition.pbir"
        document = json.loads(path.read_text(encoding="utf-8"))
        document["datasetReference"]["byPath"]["path"] = "C:\\Outside.SemanticModel"
        _write_json(path, document)

        report = catalog_pbir(root)["reports"][0]

        self.assertIn("PBIR_DATASET_PATH_UNSAFE", {issue["code"] for issue in report["issues"]})
        self.assertFalse(report["patch_eligible"])

    def test_definition_file_outside_allowlist_forces_view_only(self):
        root = self._make()
        unsupported = root / "Retail.Report" / "definition" / "private" / "state.json"
        _write_json(unsupported, {"$schema": "synthetic"})

        report = catalog_pbir(root)["reports"][0]

        self.assertEqual(report["static_validation"], "view_only")
        self.assertIn("definition/private/state.json", report["out_of_allowlist_paths"])
        self.assertIn("PBIR_PATH_NOT_ALLOWED", {issue["code"] for issue in report["issues"]})

    def test_missing_schema_is_blocked(self):
        root = self._make()
        path = root / "Retail.Report" / "definition" / "report.json"
        document = json.loads(path.read_text(encoding="utf-8"))
        del document["$schema"]
        _write_json(path, document)

        report = catalog_pbir(root)["reports"][0]

        self.assertEqual(report["static_validation"], "blocked")
        self.assertIn("PBIR_SCHEMA_MISSING", {issue["code"] for issue in report["issues"]})

    def test_protected_files_are_reported_but_never_allowlisted(self):
        root = self._make("protected_files")

        report = catalog_pbir(root)["reports"][0]

        self.assertFalse(report["patch_eligible"])
        self.assertTrue(report["static_patch_candidate"])
        self.assertIn("definition.pbir", report["protected_paths"])
        self.assertIn("mobileState.json", report["protected_paths"])
        self.assertIn("semanticModelDiagramLayout.json", report["protected_paths"])
        self.assertNotIn("definition.pbir", report["allowed_definition_paths"])

    def test_malformed_json_is_blocked(self):
        root = self._make()
        path = root / "Retail.Report" / "definition" / "report.json"
        path.write_text("{not-json", encoding="utf-8")

        report = catalog_pbir(root)["reports"][0]

        self.assertEqual(report["static_validation"], "blocked")
        self.assertIn("PBIR_INVALID_JSON", {issue["code"] for issue in report["issues"]})

    def test_missing_pages_metadata_is_blocked(self):
        root = self._make()
        (root / "Retail.Report" / "definition" / "pages" / "pages.json").unlink()
        report = catalog_pbir(root)["reports"][0]
        self.assertEqual(report["static_validation"], "blocked")
        self.assertIn("PBIR_REQUIRED_FILE_MISSING", {issue["code"] for issue in report["issues"]})

    def test_visual_under_missing_page_is_blocked(self):
        root = self._make()
        (root / "Retail.Report" / "definition" / "pages" / PAGE_ID / "page.json").unlink()
        report = catalog_pbir(root)["reports"][0]
        self.assertEqual(report["static_validation"], "blocked")
        self.assertIn("PBIR_VISUAL_PAGE_INVALID", {issue["code"] for issue in report["issues"]})

    def test_by_path_existing_non_semantic_model_target_is_blocked(self):
        root = self._make()
        other = root / "OtherFolder"
        other.mkdir()
        path = root / "Retail.Report" / "definition.pbir"
        document = json.loads(path.read_text(encoding="utf-8"))
        document["datasetReference"]["byPath"]["path"] = "../OtherFolder"
        _write_json(path, document)
        report = catalog_pbir(root)["reports"][0]
        self.assertEqual(report["static_validation"], "blocked")
        self.assertIn("PBIR_DATASET_TARGET_INVALID", {issue["code"] for issue in report["issues"]})


if __name__ == "__main__":
    unittest.main()
