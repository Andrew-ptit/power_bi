"""The pane's script order is contract: HTML, Node harnesses and Python cross-checks.

A split pane only behaves like one script while every consumer loads the same
files in the same order. This pins the three lists together so a future split or
rename cannot leave one consumer reading a different program.
"""
from __future__ import annotations

import re
import unittest

from tests.support.taskpane_source import ADDIN_ROOT, ORDER, taskpane_source


class TaskPaneAssetOrderTests(unittest.TestCase):
    def test_html_loads_exactly_the_ordered_pane_scripts(self) -> None:
        html = (ADDIN_ROOT / "taskpane.html").read_text(encoding="utf-8")
        loaded = re.findall(r'<script src="/assets/(taskpane[^"]*\.js)" defer></script>', html)
        self.assertEqual(tuple(loaded), ORDER)

    def test_node_loader_order_matches_python_order(self) -> None:
        loader = (ADDIN_ROOT.parents[1] / "tests" / "support" / "taskpane_source.js").read_text(encoding="utf-8")
        listed = re.findall(r'"((?:taskpane[^"]*)\.js)"', loader)
        self.assertEqual(tuple(listed), ORDER)

    def test_every_ordered_file_exists_and_is_classic_script(self) -> None:
        for name in ORDER:
            path = ADDIN_ROOT / name
            self.assertTrue(path.is_file(), name)
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("\nexport ", text, name)
            self.assertNotIn("\nimport ", text, name)

    def test_concatenation_still_defines_the_entry_points(self) -> None:
        source = taskpane_source()
        for name in ("function bindEvents(", "async function start(", "async function apiImpl("):
            self.assertIn(name, source)
