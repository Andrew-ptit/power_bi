import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
PROJECT = HERE / "TmdlSpike.csproj"
VALID = HERE / "fixtures" / "valid"
INVALID = HERE / "fixtures" / "invalid"


def folder_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def run_spike(*args: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["dotnet", "run", "--project", str(PROJECT), "--no-restore", "--", *(str(arg) for arg in args)],
        cwd=HERE,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


@unittest.skipUnless(shutil.which("dotnet"), "dotnet SDK is required for the isolated W-06 spike")
class TmdlSerializerSpikeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        build = subprocess.run(
            ["dotnet", "build", str(PROJECT), "--no-restore"],
            cwd=HERE,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        if build.returncode:
            raise AssertionError(build.stdout + build.stderr)

    def test_catalog_and_roundtrip_preserve_semantics_and_source(self) -> None:
        before = folder_hash(VALID)
        with tempfile.TemporaryDirectory() as temporary:
            first = Path(temporary) / "first"
            second = Path(temporary) / "second"
            result = run_spike("roundtrip", VALID, first)
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["database"], "SpikeRetail")
            self.assertEqual(payload["tableCount"], 2)
            self.assertEqual(payload["relationshipCount"], 1)
            fact = next(table for table in payload["tables"] if table["name"] == "FactOrders")
            self.assertEqual(fact["measures"][0]["description"], "Synthetic gross sales; not net sales.")
            self.assertEqual(fact["measures"][0]["formatString"], "#,0.00")
            self.assertEqual(folder_hash(VALID), before)

            second_result = run_spike("roundtrip", first, second)
            self.assertEqual(second_result.returncode, 0, second_result.stderr)
            self.assertEqual(folder_hash(first), folder_hash(second))

    def test_invalid_tmdl_is_rejected_without_source_change(self) -> None:
        before = folder_hash(INVALID)
        result = run_spike("inspect", INVALID)
        self.assertEqual(result.returncode, 10)
        self.assertIn("INVALID_TMDL", result.stderr)
        self.assertEqual(folder_hash(INVALID), before)

    def test_existing_output_is_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            existing = Path(temporary) / "existing"
            existing.mkdir()
            marker = existing / "keep.txt"
            marker.write_text("keep", encoding="utf-8")
            result = run_spike("roundtrip", VALID, existing)
            self.assertEqual(result.returncode, 11)
            self.assertEqual(marker.read_text(encoding="utf-8"), "keep")


if __name__ == "__main__":
    unittest.main()
