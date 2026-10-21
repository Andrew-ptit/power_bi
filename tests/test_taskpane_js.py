from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import unittest


class TaskpaneJavaScriptTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node.js is not available")
    def test_text_and_copyable_code_are_rendered_separately(self) -> None:
        script = Path(__file__).with_name("taskpane_code_blocks.js")
        result = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=10, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("passed", result.stdout)

    @unittest.skipUnless(shutil.which("node"), "Node.js is not available")
    def test_pq_preview_copies_result_and_source_apply_is_separately_confirmed(self) -> None:
        script = Path(__file__).with_name("taskpane_pq.js")
        result = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=10, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("passed", result.stdout)

    @unittest.skipUnless(shutil.which("node"), "Node.js is not available")
    def test_typed_pq_preview_approval_and_revision_invalidation(self) -> None:
        script = Path(__file__).with_name("taskpane_pq_typed.js")
        result = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=10, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("passed", result.stdout)

    @unittest.skipUnless(shutil.which("node"), "Node.js is not available")
    def test_problem_chain_custom_xml_cas_head_view_and_feature_gate(self) -> None:
        script = Path(__file__).with_name("taskpane_problem_chain.js")
        result = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=15, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("passed", result.stdout)

    @unittest.skipUnless(shutil.which("node"), "Node.js is not available")
    def test_pq_writer_imports_values_and_reuses_marked_sheet(self) -> None:
        script = Path(__file__).with_name("taskpane_pq_write.js")
        result = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=10, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("passed", result.stdout)

    @unittest.skipUnless(shutil.which("node"), "Node.js is not available")
    def test_advanced_pq_apply_replaces_only_selected_source_scope(self) -> None:
        script = Path(__file__).with_name("taskpane_pq_source_apply.js")
        result = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=10, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("passed", result.stdout)

    @unittest.skipUnless(shutil.which("node"), "Node.js is not available")
    def test_advanced_m_trusted_policy_acknowledgement_and_session_lifecycle(self) -> None:
        script = Path(__file__).with_name("taskpane_advanced_policy.js")
        result = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=10, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("passed", result.stdout)

    @unittest.skipUnless(shutil.which("node"), "Node.js is not available")
    def test_analyze_reads_live_workbook_and_blocks_stale_snapshot_on_failure(self) -> None:
        script = Path(__file__).with_name("taskpane_live_analyze.js")
        result = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=10, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("passed", result.stdout)

    @unittest.skipUnless(shutil.which("node"), "Node.js is not available")
    def test_ctrl_enter_analyzes_only_when_button_is_enabled(self) -> None:
        script = Path(__file__).with_name("taskpane_shortcut.js")
        result = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=10, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("passed", result.stdout)

    @unittest.skipUnless(shutil.which("node"), "Node.js is not available")
    def test_used_range_fallback_without_excel_table(self) -> None:
        script = Path(__file__).with_name("taskpane_usedrange.js")
        result = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=10, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("passed", result.stdout)


if __name__ == "__main__":
    unittest.main()
