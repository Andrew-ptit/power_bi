from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import unittest


class TaskpaneJavaScriptTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node.js is not available")
    def test_preparation_read_guards_and_wizard_revisions(self) -> None:
        for name in ("taskpane_preparation_runtime.js", "taskpane_preparation_wizard.js", "taskpane_assistant_entry.js", "taskpane_preparation_bridge.js", "preparation_native_mutations.js", "taskpane_preparation_session.js", "taskpane_preparation_startup.js", "taskpane_preparation_direct.js"):
            with self.subTest(script=name):
                result = subprocess.run(["node", str(Path(__file__).with_name(name))],
                                        capture_output=True, text=True, timeout=15, check=False)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("passed", result.stdout)

    @unittest.skipUnless(shutil.which("node"), "Node.js is not available")
    def test_assistant_record_metadata_xml_hash_cas_and_privacy(self) -> None:
        script = Path(__file__).with_name("taskpane_assistant_custom_xml.js")
        result = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=15, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("passed", result.stdout)

    @unittest.skipUnless(shutil.which("node"), "Node.js is not available")
    def test_advanced_m_policy_independent_crosscheck(self) -> None:
        script = Path(__file__).with_name("taskpane_advanced_policy_crosscheck.js")
        result = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=10, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("passed", result.stdout)

    @unittest.skipUnless(shutil.which("node"), "Node.js is not available")
    def test_diagnostic_capability_workbook_switch_and_error_recovery(self) -> None:
        script = Path(__file__).with_name("taskpane_diagnostic_ui_guard.js")
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
    def test_used_range_fallback_without_excel_table(self) -> None:
        script = Path(__file__).with_name("taskpane_usedrange.js")
        result = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=10, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("passed", result.stdout)

    @unittest.skipUnless(shutil.which("node"), "Node.js is not available")
    def test_table_totals_row_is_excluded_from_workbook_data(self) -> None:
        script = Path(__file__).with_name("taskpane_totals_row.js")
        result = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=15, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("passed", result.stdout)

    @unittest.skipUnless(shutil.which("node"), "Node.js is not available")
    def test_source_browser_selection_and_import_report(self) -> None:
        script = Path(__file__).with_name("taskpane_assistant_browser.js")
        result = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=15, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("passed", result.stdout)

    @unittest.skipUnless(shutil.which("node"), "Node.js is not available")
    def test_two_step_journey_scan_and_add_source(self) -> None:
        script = Path(__file__).with_name("taskpane_assistant_journey.js")
        result = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=15, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("passed", result.stdout)

    @unittest.skipUnless(shutil.which("node"), "Node.js is not available")
    def test_model_diagram_layout_and_render(self) -> None:
        script = Path(__file__).with_name("taskpane_model_diagram.js")
        result = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=15, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("passed", result.stdout)

    @unittest.skipUnless(shutil.which("node"), "Node.js is not available")
    def test_assistant_flow_sources_sampling_and_feature_gate(self) -> None:
        script = Path(__file__).with_name("taskpane_assistant_flow.js")
        result = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=15, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("passed", result.stdout)


if __name__ == "__main__":
    unittest.main()
