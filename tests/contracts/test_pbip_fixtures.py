"""W-03: structural fixture tests only; not Desktop/schema-runtime proof."""

import json
import tempfile
import unittest
from pathlib import Path

from examples.pbip_fixtures import (
    PAGE_ID, VISUAL_ID, VARIANTS, fixture_manifest, make_retail_pbip, make_fixture_bundle,
)
from pbip_assistant.pbip import inventory_pbip


class RetailPbipFixtureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)

    def make(self, variant="modern", suffix="project"):
        return make_retail_pbip(self.base / suffix, variant=variant)

    def test_modern_tree_and_internal_references(self):
        root = self.make()
        manifest = fixture_manifest(root)
        files = set(manifest["files_sha256"])
        self.assertEqual(len(files), 15)
        self.assertIn("Retail.pbip", files)
        self.assertIn("Retail.Report/definition.pbir", files)
        self.assertIn("Retail.SemanticModel/definition.pbism", files)
        self.assertIn("Retail.SemanticModel/definition/database.tmdl", files)
        self.assertIn("Retail.SemanticModel/definition/model.tmdl", files)
        self.assertIn("Retail.SemanticModel/definition/relationships.tmdl", files)
        self.assertEqual(len([p for p in files if "/tables/" in p]), 4)
        self.assertIn(f"Retail.Report/definition/pages/{PAGE_ID}/visuals/{VISUAL_ID}/visual.json", files)
        pbip = json.loads((root / "Retail.pbip").read_text(encoding="utf-8"))
        report = root / pbip["artifacts"][0]["report"]["path"]
        self.assertTrue(report.is_dir())
        binding = json.loads((report / "definition.pbir").read_text(encoding="utf-8"))
        target = (report / binding["datasetReference"]["byPath"]["path"]).resolve()
        self.assertEqual(target, (root / "Retail.SemanticModel").resolve())
        self.assertTrue((target / "definition.pbism").is_file())
        pages = json.loads((report / "definition/pages/pages.json").read_text(encoding="utf-8"))
        self.assertEqual(pages["pageOrder"], [PAGE_ID])
        self.assertEqual(pages["activePageName"], PAGE_ID)
        visual = json.loads((report / f"definition/pages/{PAGE_ID}/visuals/{VISUAL_ID}/visual.json").read_text(encoding="utf-8"))
        projection = visual["visual"]["query"]["queryState"]["Data"]["projections"][0]
        self.assertEqual(projection["field"]["Measure"]["Property"], "Gross Sales")
        self.assertEqual(projection["field"]["Measure"]["Expression"]["SourceRef"]["Entity"], "FactOrders")

    def test_json_syntax_schema_identifiers_and_versions(self):
        root = self.make()
        json_paths = [path for path in root.rglob("*") if path.is_file() and (path.suffix in (".json", ".pbip", ".pbir", ".pbism"))]
        self.assertEqual(len(json_paths), 8)
        for path in json_paths:
            with self.subTest(path=path.name):
                data = json.loads(path.read_text(encoding="utf-8"))
                self.assertTrue(data["$schema"].startswith("https://developer.microsoft.com/json-schemas/fabric/"))
                self.assertTrue(data["$schema"].endswith("/schema.json"))
        self.assertEqual(json.loads((root / "Retail.Report/definition/version.json").read_text())["version"], "2.0.0")
        self.assertIn("themeCollection", json.loads((root / "Retail.Report/definition/report.json").read_text()))
        self.assertEqual(json.loads((root / "Retail.Report/definition.pbir").read_text())["version"], "4.0")
        self.assertEqual(json.loads((root / "Retail.SemanticModel/definition.pbism").read_text())["version"], "4.0")

    def test_tmdl_contains_four_tables_three_relationships_and_m_sources(self):
        root = self.make()
        model = root / "Retail.SemanticModel/definition"
        table_text = {p.stem: p.read_text(encoding="utf-8") for p in (model / "tables").glob("*.tmdl")}
        self.assertEqual(set(table_text), {"FactOrders", "DimProduct", "DimCustomer", "DimDate"})
        self.assertIn("measure 'Gross Sales'", table_text["FactOrders"])
        self.assertIn("measure 'Order Count'", table_text["FactOrders"])
        self.assertIn("\t/// Synthetic gross sales; not net sales.\n\tmeasure 'Gross Sales'", table_text["FactOrders"])
        self.assertNotIn("\t\tdescription:", table_text["FactOrders"])
        self.assertIn("#table(type table", table_text["FactOrders"])
        self.assertIn("defaultPowerBIDataSourceVersion: powerBI_V3", (model / "model.tmdl").read_text())
        self.assertEqual((model / "relationships.tmdl").read_text().count("relationship "), 3)

    def test_manifest_is_exact_deterministic_and_source_is_read_only(self):
        first = self.make(suffix="first")
        before = fixture_manifest(first)
        second = self.make(suffix="second")
        self.assertEqual(before, fixture_manifest(second))
        inventory = inventory_pbip(first)
        self.assertEqual(inventory["file_count"], len(before["files_sha256"]))
        self.assertFalse(inventory["reports"][0]["patch_eligible"])
        self.assertEqual(before, fixture_manifest(first))
        self.assertEqual(before["desktop_validation"], "desktop_not_run")
        self.assertEqual(before["schema_validation"], "not_run")
        self.assertFalse(before["patch_eligible"])
        self.assertIn("Retail.Report/definition.pbir", before["protected_or_out_of_scope_paths"])
        self.assertNotIn("Retail.Report/definition.pbir", before["candidate_patch_paths_only_after_future_validation"])
        self.assertTrue(all(p.startswith("Retail.Report/definition/") or p.startswith("Retail.SemanticModel/definition/") for p in before["candidate_patch_paths_only_after_future_validation"]))

    def test_legacy_is_separate_view_only_shape(self):
        root = self.make("legacy")
        self.assertTrue((root / "Retail.Report/report.json").is_file())
        self.assertFalse((root / "Retail.Report/definition").exists())
        report = inventory_pbip(root)["reports"][0]
        self.assertEqual(report["format"], "PBIR-legacy")
        self.assertFalse(report["external_edit_candidate"])

    def test_negative_variants_have_expected_faults(self):
        self.assertEqual(len(VARIANTS), 8)
        unsupported = self.make("unsupported_schema", "schema")
        visual = json.loads((unsupported / f"Retail.Report/definition/pages/{PAGE_ID}/visuals/{VISUAL_ID}/visual.json").read_text())
        self.assertIn("/99.0.0/", visual["$schema"])
        duplicate = self.make("duplicate_measure", "duplicate")
        self.assertEqual((duplicate / "Retail.SemanticModel/definition/tables/FactOrders.tmdl").read_text().count("measure 'Gross Sales'"), 2)
        broken = self.make("broken_relative_link", "broken")
        link = json.loads((broken / "Retail.Report/definition.pbir").read_text())["datasetReference"]["byPath"]["path"]
        self.assertFalse((broken / "Retail.Report" / link).exists())
        missing = self.make("missing_binding", "missing")
        self.assertNotIn("datasetReference", json.loads((missing / "Retail.Report/definition.pbir").read_text()))
        protected = self.make("protected_files", "protected")
        paths = fixture_manifest(protected)["protected_or_out_of_scope_paths"]
        self.assertIn("Retail.Report/mobileState.json", paths)
        self.assertIn("Retail.Report/semanticModelDiagramLayout.json", paths)
        self.assertIn("Retail.SemanticModel/diagramLayout.json", paths)
        changed = self.make("hash_change", "changed")
        baseline = self.make("modern", "baseline")
        changed_files = {p for p, hash_ in fixture_manifest(changed)["files_sha256"].items()
                         if fixture_manifest(baseline)["files_sha256"][p] != hash_}
        self.assertEqual(changed_files, {"Retail.SemanticModel/definition/tables/DimProduct.tmdl"})

    def test_existing_destination_cannot_be_overwritten(self):
        root = self.make()
        before = fixture_manifest(root)
        with self.assertRaises(FileExistsError):
            make_retail_pbip(root)
        self.assertEqual(before, fixture_manifest(root))

    def test_committed_fixture_matches_generated_bytes_and_manifest(self):
        committed = Path(__file__).resolve().parents[1] / "fixtures" / "pbip"
        source = committed / "Retail"
        expected = json.loads((committed / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(expected, fixture_manifest(source))
        regenerated = make_fixture_bundle(self.base / "bundle")
        self.assertEqual(expected, fixture_manifest(regenerated))


if __name__ == "__main__":
    unittest.main()
