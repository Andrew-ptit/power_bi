"""The served task pane must expose every script/style it references."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[2]
HTML = ROOT / "pbip_assistant" / "excel_addin" / "taskpane.html"
SERVER = ROOT / "pbip_assistant" / "coordinator" / "server.py"


class TaskpaneAssetRouteTests(unittest.TestCase):
    def test_every_referenced_asset_has_a_served_route(self) -> None:
        html = HTML.read_text(encoding="utf-8")
        server = SERVER.read_text(encoding="utf-8")
        referenced = set(re.findall(r'(?:src|href)="(/assets/[^"?]+\.(?:js|css))"', html))
        self.assertTrue(referenced, "the task pane references no assets")
        missing = sorted(path for path in referenced if f'"{path}"' not in server)
        self.assertEqual(missing, [], f"task-pane assets without a served route: {missing}")
