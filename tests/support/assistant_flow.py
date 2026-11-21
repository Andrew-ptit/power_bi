"""Deterministic plan-only test double for isolated Assistant HTTP smoke runs.

This fixture never supplies calculated results and is never imported by product
code. Both branches use the supplied source catalog and the real local engine.
"""

from copy import deepcopy


class AssistantBranchPlanner:
    def __init__(self):
        self.calls = []

    def propose(self, payload):
        self.calls.append(deepcopy(payload))
        sources = payload["sources"]
        chosen = None
        for preferred in ("Amount", "Quantity", "Qty", "UnitPrice", "ListPrice"):
            for source in sources:
                if any(column["name"] == preferred for column in source["columns"]):
                    chosen = source, preferred
                    break
            if chosen:
                break
        if chosen is None:
            raise AssertionError("Synthetic smoke needs a named numeric fixture column")
        source, column = chosen
        source_kind = source.get("kind", "excelTable")
        operation = "source.usedRange" if source_kind == "usedRange" else "source.workbookTable"

        def step(reference, variable, kind, inputs, parameters):
            return {"clientRef": reference, "variableName": variable,
                    "actionDescription": "Synthetic smoke: " + kind,
                    "operationType": kind, "inputs": inputs, "parameters": parameters}

        branches = []
        for branch_id in ("A", "B"):
            steps = [
                step("source", "Source", operation, [], {"sourceId": source["sourceId"]}),
                step("typed", "Typed", "table.changeTypes", ["source"],
                     {"conversions": [{"column": column, "targetType": "number"}]}),
            ]
            previous = "typed"
            if branch_id == "B":
                steps.append(step("positive", "Positive", "table.filterRows", [previous], {
                    "predicate": {"kind": "compare", "operator": "gt",
                                  "left": {"kind": "columnRef", "column": column},
                                  "right": {"kind": "literal", "valueType": "number", "value": 0}}}))
                previous = "positive"
            steps.append(step("total", "Total", "table.aggregateRows", [previous], {
                "aggregations": [{"function": "sum", "column": column, "outputName": "Total"}]}))
            branches.append({
                "id": branch_id,
                "label": "All source rows" if branch_id == "A" else "Positive source rows",
                "rationale": "Synthetic plan fixture; the local engine calculates all results.",
                "controlTotal": {"resultColumn": "Total", "sourceColumn": column,
                                 "aggregation": "sum", "afterFilters": True},
                "plan": {"summary": "Sum the selected fixture column", "questions": [],
                         "assumptions": [], "warnings": [], "steps": steps, "finalOutputRef": "total"},
            })
        return {"summary": "Two synthetic typed plans; no calculated values", "questions": [],
                "assumptions": [], "branches": branches}
