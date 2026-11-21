"""Keep the new synthetic fixtures compatible with the current read-only slice."""

from pathlib import Path
import unittest

from pbip_assistant.pbip import create_snapshot, inventory_pbip, snapshot_matches
from pbip_assistant.xlsx import profile_workbook
from tests.support.pbip_fixtures import fixture_manifest


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


class FixtureIntegrationTests(unittest.TestCase):
    def test_existing_read_only_adapters_accept_new_baselines_without_writing_them(self) -> None:
        pbip = FIXTURES / "pbip" / "Retail"
        workbook = FIXTURES / "source" / "orders_synthetic.xlsx"
        before = fixture_manifest(pbip)["files_sha256"]
        workbook_bytes = workbook.read_bytes()

        profile = profile_workbook(workbook)
        self.assertEqual(profile["sheets"][0]["row_count"], 6)
        order_date = next(column for column in profile["sheets"][0]["columns"] if column["name"] == "OrderDate")
        self.assertEqual(order_date["data_types"], {"date": 6})
        inventory = inventory_pbip(pbip)
        self.assertEqual(inventory["reports"][0]["format"], "PBIR")
        self.assertEqual(inventory["patch_readiness"], "inventory_only")
        snapshot = create_snapshot(pbip, [workbook])
        self.assertTrue(snapshot_matches(snapshot))

        self.assertEqual(fixture_manifest(pbip)["files_sha256"], before)
        self.assertEqual(workbook.read_bytes(), workbook_bytes)


if __name__ == "__main__":
    unittest.main()
