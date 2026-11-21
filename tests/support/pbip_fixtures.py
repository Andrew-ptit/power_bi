"""Deterministic, synthetic PBIP fixtures for W-03 structural tests.

These files imitate documented PBIP/TMDL/PBIR layout. They are not a Power BI
Desktop export and have not passed Desktop load/refresh or full schema validation.

Format references (Microsoft):
https://learn.microsoft.com/power-bi/developer/projects/projects-overview
https://learn.microsoft.com/power-bi/developer/projects/projects-report
https://learn.microsoft.com/power-bi/developer/projects/projects-dataset
https://learn.microsoft.com/analysis-services/tmdl/tmdl-overview
"""

from __future__ import annotations

import json
import hashlib
from pathlib import Path


SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/"
PAGE_ID = "a01b02c03d04e05f06a0"
VISUAL_ID = "b11c12d13e14f15a16b1"
VARIANTS = frozenset({
    "modern", "legacy", "unsupported_schema", "duplicate_measure",
    "broken_relative_link", "missing_binding", "protected_files", "hash_change",
})


def _json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value.strip() + "\n", encoding="utf-8")


def _table(name: str, columns: list[tuple[str, str]], rows: str, *, measures: str = "") -> str:
    column_defs = "\n\n".join(
        f"\tcolumn {column}\n\t\tdataType: {dtype}\n\t\tsourceColumn: {column}\n\t\tsummarizeBy: none"
        for column, dtype in columns
    )
    fields = ", ".join(f"{column} = {('number' if dtype in ('int64', 'double') else 'text' if dtype == 'string' else 'datetime')}" for column, dtype in columns)
    return (
        f"table {name}\n\n{column_defs}\n\n{measures}"
        f"\tpartition {name} = m\n\t\tmode: import\n\t\tsource =\n"
        f"\t\t\t#table(type table [{fields}], {{{rows}}})\n"
    )


def _measure_ref(table: str, measure: str) -> dict:
    return {"Measure": {"Expression": {"SourceRef": {"Entity": table}}, "Property": measure}}


def make_retail_pbip(root: Path, *, variant: str = "modern") -> Path:
    """Create one synthetic project in a new empty directory; never overwrite inputs."""
    if variant not in VARIANTS:
        raise ValueError(f"Unknown PBIP fixture variant: {variant}")
    root = Path(root)
    if root.exists() and any(root.iterdir()):
        raise FileExistsError(f"Fixture destination is not empty: {root}")
    root.mkdir(parents=True, exist_ok=True)
    report = root / "Retail.Report"
    semantic = root / "Retail.SemanticModel"
    definition = report / "definition"
    tmdl = semantic / "definition"

    _json(root / "Retail.pbip", {
        "$schema": SCHEMA + "pbip/pbipProperties/1.0.0/schema.json",
        "version": "1.0", "artifacts": [{"report": {"path": "Retail.Report"}}],
        "settings": {"enableAutoRecovery": True},
    })
    reference = {
        "$schema": SCHEMA + "item/report/definitionProperties/2.0.0/schema.json",
        "version": "4.0" if variant != "legacy" else "1.0",
        "datasetReference": {"byPath": {"path": "../Retail.SemanticModel"}},
    }
    if variant == "broken_relative_link":
        reference["datasetReference"]["byPath"]["path"] = "../Missing.SemanticModel"
    if variant == "missing_binding":
        del reference["datasetReference"]
    _json(report / "definition.pbir", reference)

    _report_definition(report, definition, variant)
    _semantic_model(semantic, tmdl, variant)
    _variant_extras(report, semantic, tmdl, variant)
    return root


def _report_definition(report: Path, definition: Path, variant: str) -> None:
    """Write the report side: legacy report.json, or the modern definition tree."""
    if variant == "legacy":
        _json(report / "report.json", {"sections": [], "config": "{}"})
    else:
        _json(definition / "version.json", {
            "$schema": SCHEMA + "item/report/definition/versionMetadata/1.0.0/schema.json",
            "version": "2.0.0",
        })
        _json(definition / "report.json", {
            "$schema": SCHEMA + "item/report/definition/report/3.2.0/schema.json",
            "themeCollection": {},
        })
        _json(definition / "pages" / "pages.json", {
            "$schema": SCHEMA + "item/report/definition/pagesMetadata/1.0.0/schema.json",
            "pageOrder": [PAGE_ID], "activePageName": PAGE_ID,
        })
        _json(definition / "pages" / PAGE_ID / "page.json", {
            "$schema": SCHEMA + "item/report/definition/page/2.1.0/schema.json",
            "name": PAGE_ID, "displayName": "Overview", "displayOption": "FitToPage",
            "height": 720, "width": 1280,
        })
        _json(definition / "pages" / PAGE_ID / "visuals" / VISUAL_ID / "visual.json", {
            "$schema": SCHEMA + "item/report/definition/visualContainer/"
                       + ("99.0.0" if variant == "unsupported_schema" else "2.4.0") + "/schema.json",
            "name": VISUAL_ID,
            "position": {"x": 24, "y": 32, "z": 1000, "height": 200, "width": 340, "tabOrder": 1000},
            "visual": {"visualType": "cardVisual", "query": {"queryState": {"Data": {"projections": [{
                "field": _measure_ref("FactOrders", "Gross Sales"),
                "queryRef": "FactOrders.Gross Sales", "nativeQueryRef": "Gross Sales",
            }]}}}},
        })

def _semantic_model(semantic: Path, tmdl: Path, variant: str) -> None:
    """Write the semantic model: definition properties, database, tables, relationships."""
    _json(semantic / "definition.pbism", {
        "$schema": SCHEMA + "item/semanticModel/definitionProperties/1.0.0/schema.json",
        "version": "4.0", "settings": {"qnaEnabled": False},
    })
    _text(tmdl / "database.tmdl", "database Retail\n\tcompatibilityLevel: 1600")
    _text(tmdl / "model.tmdl", """
model Model
\tculture: en-US
\tdefaultPowerBIDataSourceVersion: powerBI_V3
\tdiscourageImplicitMeasures

ref table FactOrders
ref table DimProduct
ref table DimCustomer
ref table DimDate
""")
    duplicate = "\tmeasure 'Gross Sales' = SUMX(FactOrders, FactOrders[Quantity] * FactOrders[UnitPrice])\n\n" if variant == "duplicate_measure" else ""
    measures = (
        "\t/// Synthetic gross sales; not net sales.\n"
        "\tmeasure 'Gross Sales' = SUMX(FactOrders, FactOrders[Quantity] * FactOrders[UnitPrice])\n"
        "\t\tformatString: \"#,0.00\"\n\n"
        "\tmeasure 'Order Count' = DISTINCTCOUNT(FactOrders[OrderID])\n"
        "\t\tformatString: \"#,0\"\n\n" + duplicate
    )
    _text(tmdl / "tables" / "FactOrders.tmdl", _table("FactOrders", [
        ("OrderID", "string"), ("CustomerID", "string"), ("ProductID", "string"),
        ("OrderDate", "dateTime"), ("Quantity", "int64"), ("UnitPrice", "double"),
        ("Discount", "double"), ("Status", "string"),
    ], '{"TEST-001", "C-001", "P-01", #datetime(2026, 9, 1, 0, 0, 0), 2, 100.0, 10.0, "Completed"}', measures=measures))
    _text(tmdl / "tables" / "DimProduct.tmdl", _table("DimProduct", [
        ("ProductID", "string"), ("ProductName", "string"), ("Category", "string"),
    ], '{"P-01", "Sample A", "A"}'))
    _text(tmdl / "tables" / "DimCustomer.tmdl", _table("DimCustomer", [
        ("CustomerID", "string"), ("City", "string"), ("CustomerSegment", "string"),
    ], '{"C-001", "South City", "Retail"}'))
    _text(tmdl / "tables" / "DimDate.tmdl", _table("DimDate", [
        ("Date", "dateTime"), ("Year", "int64"), ("MonthNumber", "int64"),
    ], '{#datetime(2026, 9, 1, 0, 0, 0), 2026, 9}'))
    _text(tmdl / "relationships.tmdl", """
relationship 5d9a5ca1-d0ee-4b61-bc9b-27ec81a09ff1
\tfromColumn: FactOrders.ProductID
\ttoColumn: DimProduct.ProductID

relationship d75c1b27-ab11-4f8e-af0a-3181a50d6d8c
\tfromColumn: FactOrders.CustomerID
\ttoColumn: DimCustomer.CustomerID

relationship e8d6ab32-ae76-4273-a777-27fc50ac5bbf
\tfromColumn: FactOrders.OrderDate
\ttoColumn: DimDate.Date
""")

def _variant_extras(report: Path, semantic: Path, tmdl: Path, variant: str) -> None:
    """Apply the per-variant additions that must land after the shared tree."""
    if variant == "protected_files":
        _json(report / "semanticModelDiagramLayout.json", {"version": "1.0", "diagrams": []})
        _json(report / "mobileState.json", {"synthetic": True})
        _json(semantic / "diagramLayout.json", {"version": "1.1.0", "diagrams": []})
    if variant == "hash_change":
        path = tmdl / "tables" / "DimProduct.tmdl"
        path.write_text(path.read_text(encoding="utf-8") + "\n// synthetic changed hash\n", encoding="utf-8")


def fixture_manifest(root: Path) -> dict:
    """Record an exact byte inventory; candidates are not patch authorization."""
    root = Path(root)
    files = {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*")) if path.is_file()
    }
    candidates = sorted(path for path in files if (
        path.startswith("Retail.SemanticModel/definition/") and path.endswith(".tmdl")
        or path.startswith("Retail.Report/definition/") and path.endswith(".json")
    ))
    return {
        "fixture": "synthetic_structural_pbip",
        "schema_validation": "not_run",
        "desktop_validation": "desktop_not_run",
        "patch_eligible": False,
        "files_sha256": files,
        "candidate_patch_paths_only_after_future_validation": candidates,
        "protected_or_out_of_scope_paths": sorted(set(files) - set(candidates)),
    }


def make_fixture_bundle(root: Path) -> Path:
    """Create a checked-in-style baseline plus exact manifest in an empty folder."""
    root = Path(root)
    if root.exists() and any(root.iterdir()):
        raise FileExistsError(f"Fixture bundle destination is not empty: {root}")
    project = make_retail_pbip(root / "Retail")
    _json(root / "manifest.json", fixture_manifest(project))
    return project
