import unittest

from pbip_assistant.planning import (
    FieldCatalog, KpiDefinition, ProposedOperation, VisualRequest,
    kpi_readiness, propose_visual, validate_operation_selection,
)


class PlanningTests(unittest.TestCase):
    def setUp(self):
        self.catalog = FieldCatalog(
            temporal_dimensions=("OrderMonth",),
            category_dimensions=("City", "Status"),
            confirmed_measures=("Return Rate", "Net Sales"),
        )

    def test_unconfirmed_kpi_cannot_generate_dax(self):
        result = kpi_readiness(KpiDefinition("Return Rate", "Returned / Sales", "order", "", "%", ("Returned", "Sales")))
        self.assertEqual(result["status"], "needs_clarification")
        self.assertIn("date_role", result["missing"])
        self.assertFalse(result["may_generate_dax"])

    def test_confirmed_kpi_is_ready_for_later_generator(self):
        result = kpi_readiness(KpiDefinition("Return Rate", "Returned / Sales", "order", "OrderDate", "%", ("Returned", "Sales"), "analyst"))
        self.assertTrue(result["may_generate_dax"])

    def test_trend_chart_is_proposed_but_not_generated(self):
        result = propose_visual(VisualRequest("Return Rate by month", "trend", "Return Rate", "OrderMonth", target_page="Overview"), self.catalog)
        self.assertEqual(result["visual_type"], "line")
        self.assertEqual(result["status"], "needs_user_review")
        self.assertFalse(result["may_generate_pbir"])

    def test_requested_unsupported_scatter_is_not_silently_replaced(self):
        result = propose_visual(VisualRequest("Compare two KPIs", "comparison", "Net Sales", "City", "scatter", "Overview"), self.catalog)
        self.assertEqual(result["visual_type"], "scatter")
        self.assertIn("unsupported_visual_type:scatter", result["missing"])
        self.assertEqual(result["alternative_type"], "bar")

    def test_missing_measure_blocks_visual_proposal(self):
        result = propose_visual(VisualRequest("Return Rate by month", "trend", "Unconfirmed Rate", "OrderMonth", target_page="Overview"), self.catalog)
        self.assertIn("confirmed_measure:Unconfirmed Rate", result["missing"])

    def test_visual_dependency_cannot_be_deselected(self):
        operations = [
            ProposedOperation("m1", "measure.add", "Return Rate", approved=True),
            ProposedOperation("v1", "visual.add", "Overview/Trend", ("m1",), approved=True),
        ]
        result = validate_operation_selection(operations, {"v1"})
        self.assertEqual(result["status"], "blocked")
        self.assertIn("missing_dependency:v1:m1", result["errors"])
        self.assertEqual(validate_operation_selection(operations, {"m1", "v1"})["status"], "static_pass")

    def test_unapproved_or_cyclic_operation_is_blocked(self):
        operations = [
            ProposedOperation("a", "measure.add", "A", ("b",), approved=False),
            ProposedOperation("b", "visual.add", "B", ("a",), approved=True),
        ]
        result = validate_operation_selection(operations, {"a", "b"})
        self.assertEqual(result["status"], "blocked")
        self.assertTrue(any(error.startswith("dependency_cycle") for error in result["errors"]))
        self.assertIn("not_approved:a", result["errors"])


if __name__ == "__main__":
    unittest.main()
