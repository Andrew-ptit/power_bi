import hashlib
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from examples.pbip_fixtures import make_retail_pbip
from pbip_assistant.errors import InputError
from pbip_assistant.tmdl import catalog_tmdl


ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "tools" / "tmdl_bridge" / "TmdlBridge.csproj"
BRIDGE = ROOT / "tools" / "tmdl_bridge" / "bin" / "Release" / "net8.0" / "TmdlBridge.dll"


def file_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*")) if path.is_file()
    }


@unittest.skipUnless(shutil.which("dotnet"), "dotnet is required for official TMDL parser tests")
class TmdlCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        build = subprocess.run(
            ["dotnet", "build", str(PROJECT), "-c", "Release", "--no-restore"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        if build.returncode:
            raise unittest.SkipTest("pinned TMDL bridge dependencies were not restored")

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)

    def model(self, variant: str = "modern", suffix: str = "project") -> Path:
        root = make_retail_pbip(self.base / suffix, variant=variant)
        return root / "Retail.SemanticModel" / "definition"

    def test_catalog_tables_columns_measures_relationships_and_m_read_only(self) -> None:
        model = self.model()
        before = file_hashes(model)
        result = catalog_tmdl(model, bridge_path=BRIDGE)
        self.assertEqual(result["parseValidation"], "passed")
        self.assertEqual(result["access"], "read_only")
        self.assertFalse(result["patchEligible"])
        self.assertEqual(result["tableCount"], 4)
        self.assertEqual(result["relationshipCount"], 3)
        fact = next(table for table in result["tables"] if table["name"] == "FactOrders")
        self.assertEqual(len(fact["columns"]), 8)
        gross = next(measure for measure in fact["measures"] if measure["name"] == "Gross Sales")
        self.assertEqual(gross["description"], "Synthetic gross sales; not net sales.")
        self.assertEqual(gross["formatString"], "#,0.00")
        self.assertIn("SUMX", gross["expression"])
        self.assertEqual(fact["partitions"][0]["sourceType"], "M")
        self.assertIn("#table", fact["partitions"][0]["expression"])
        self.assertEqual(file_hashes(model), before)

    def test_duplicate_measure_is_blocked(self) -> None:
        model = self.model("duplicate_measure", "duplicate")
        before = file_hashes(model)
        with self.assertRaises(InputError) as caught:
            catalog_tmdl(model, bridge_path=BRIDGE)
        self.assertEqual(caught.exception.code, "INVALID_TMDL")
        self.assertEqual(file_hashes(model), before)

    def test_missing_relationship_column_is_blocked(self) -> None:
        model = self.model(suffix="missing")
        relationships = model / "relationships.tmdl"
        relationships.write_text(
            relationships.read_text(encoding="utf-8").replace("DimProduct.ProductID", "DimProduct.MissingColumn", 1),
            encoding="utf-8",
        )
        before = file_hashes(model)
        with self.assertRaises(InputError) as caught:
            catalog_tmdl(model, bridge_path=BRIDGE)
        self.assertEqual(caught.exception.code, "INVALID_TMDL")
        self.assertEqual(file_hashes(model), before)

    def test_malformed_tmdl_is_blocked_without_echoing_source(self) -> None:
        model = self.model(suffix="malformed")
        secret = "do-not-echo-this-test-value"
        (model / "tables" / "FactOrders.tmdl").write_text(
            f"table FactOrders\n\tunknownProperty: {secret}\n", encoding="utf-8"
        )
        with self.assertRaises(InputError) as caught:
            catalog_tmdl(model, bridge_path=BRIDGE)
        self.assertEqual(caught.exception.code, "INVALID_TMDL")
        self.assertNotIn(secret, str(caught.exception))

    def test_missing_bridge_is_a_hard_block(self) -> None:
        model = self.model()
        with self.assertRaises(InputError) as caught:
            catalog_tmdl(model, bridge_path=self.base / "missing.dll")
        self.assertEqual(caught.exception.code, "TMDL_BRIDGE_UNAVAILABLE")


if __name__ == "__main__":
    unittest.main()
