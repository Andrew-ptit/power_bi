"""Metadata-only navigation and the local HTTP browse entry point."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from pbip_assistant.errors import InputError
from pbip_assistant.sources.preparation import inventory
from tests.integration import test_preparation_api


def _directory_link(link, target):
    if os.name == "nt":
        subprocess.run(["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(target)],
                       capture_output=True, check=True)
    else:
        link.symlink_to(target, target_is_directory=True)


class PreparationBrowseTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_browse_lists_folders_then_supported_files_sorted(self):
        folder = self.root / "sales" / "2026"
        folder.mkdir(parents=True)
        for name in ("Zulu", "alpha"):
            (folder / name).mkdir()
        for name in ("B.XLSX", "a.csv"):
            (folder / name).write_bytes(b"data")
        with patch.object(Path, "open", side_effect=PermissionError):
            result = inventory.browse_folder(self.root, "sales/2026")
        self.assertEqual([(item["name"], item["kind"]) for item in result["entries"]],
                         [("alpha", "folder"), ("Zulu", "folder"), ("a.csv", "file"), ("B.XLSX", "file")])
        self.assertEqual(result["breadcrumb"], [
            {"name": self.root.name, "relativePath": ""},
            {"name": "sales", "relativePath": "sales"},
            {"name": "2026", "relativePath": "sales/2026"},
        ])
        self.assertEqual(result["parentRelativePath"], "sales")
        self.assertEqual(result["relativePath"], "sales/2026")
        self.assertEqual(result["entries"][2]["size"], 4)
        self.assertEqual(result["entries"][3]["extension"], "xlsx")
        self.assertNotIn(str(self.root), str(result))

    def test_browse_skips_unsupported_and_hidden_files(self):
        for name in ("data.csv", "note.txt", ".hidden.xlsx"):
            (self.root / name).touch()
        (self.root / ".hidden").mkdir()
        result = inventory.browse_folder(self.root, "")
        self.assertEqual([item["name"] for item in result["entries"]], ["data.csv"])

    def test_browse_rejects_parent_escape_and_absolute_path(self):
        for path in ("../", str(self.root), "a/../b", "C:folder", "//host/share", "a\\..\\b"):
            with self.subTest(path=path):
                with self.assertRaises(InputError) as caught:
                    inventory.browse_folder(self.root, path)
                self.assertEqual(caught.exception.code, "DP_BROWSE_ESCAPE")

    def test_browse_excludes_and_rejects_reparse_points(self):
        target = self.root / "target"
        target.mkdir()
        link = self.root / "link"
        _directory_link(link, target)
        self.assertEqual(inventory.browse_folder(self.root, "")["entries"], [{"name": "target", "kind": "folder"}])
        with self.assertRaises(InputError) as caught:
            inventory.browse_folder(self.root, "link")
        self.assertEqual(caught.exception.code, "DP_BROWSE_ESCAPE")

        item = {"relativePath": "link", "fileName": "source.csv"}
        (target / "source.csv").write_bytes(b"Name,Amount\na,1\n")
        with self.assertRaises(InputError) as caught:
            inventory.inventory_selection(self.root, [item])
        self.assertEqual(caught.exception.code, "DP_BROWSE_ESCAPE")

    def test_inventory_rejects_a_source_path_replaced_with_a_reparse_point_as_stale(self):
        selected = self.root / "selected"
        selected.mkdir()
        (selected / "source.csv").write_bytes(b"Name,Amount\na,1\n")
        item = {"relativePath": "selected", "fileName": "source.csv"}
        result = inventory.inventory_selection(self.root, [item])
        moved = self.root / "moved"
        selected.rename(moved)
        _directory_link(selected, moved)
        file_id = result.public()["files"][0]["fileId"]
        for read in (lambda: inventory.verify_inventory(result), lambda: inventory.inventory_file_path(result, file_id)):
            with self.assertRaises(InputError) as caught:
                read()
            self.assertEqual(caught.exception.code, "DP_SOURCE_STALE")

    def test_browse_truncates_at_500(self):
        for number in reversed(range(501)):
            (self.root / f"{number:03d}.csv").touch()
        result = inventory.browse_folder(self.root, "")
        self.assertTrue(result["truncated"])
        self.assertEqual([item["name"] for item in result["entries"]], [f"{number:03d}.csv" for number in range(500)])

    def test_browse_empty_folder_returns_empty_list(self):
        result = inventory.browse_folder(self.root, "")
        self.assertEqual(result["entries"], [])
        self.assertIsNone(result["parentRelativePath"])
        self.assertFalse(result["truncated"])

    def test_browse_and_inventory_http_honor_the_claim_version(self):
        client = test_preparation_api.PreparationApiTests()
        client.setUp()
        self.addCleanup(client.doCleanups)
        status, state = client.attach()
        self.assertEqual(status, 200)
        folder = self.root / "data"
        folder.mkdir()
        (folder / "values.csv").write_bytes(b"Code,Qty\n001,2\n")
        active = {"preparationId": state["preparationId"], "root": str(self.root),
                  "expectedClaimVersion": state["claimVersion"]}
        inventory_fields = {"items": [{"relativePath": "data", "fileName": "values.csv"}]}
        status, result = client.post("browse", **active, relativePath="data")
        self.assertEqual(status, 200, result)
        self.assertEqual([entry["name"] for entry in result["entries"]], ["values.csv"])
        status, result = client.post("inventory", **active, **inventory_fields)
        self.assertEqual(status, 200, result)
        self.assertEqual(result["inventory"]["folderName"], self.root.name)
        self.assertEqual(result["inventory"]["files"][0]["fileSummary"]["columnCount"], 2)
        stale = {**active, "expectedClaimVersion": state["claimVersion"] + 1}
        for action, fields in (("browse", {"relativePath": "data"}), ("inventory", inventory_fields)):
            with self.subTest(action=action):
                status, result = client.post(action, **stale, **fields)
                self.assertEqual(status, 409)
                self.assertEqual(result["error"]["code"], "DP_REVIEW_STALE")
