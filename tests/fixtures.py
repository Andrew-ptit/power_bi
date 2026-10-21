"""Synthetic OOXML and PBIP fixtures. No real business data is included."""

from pathlib import Path
import json
from xml.sax.saxutils import escape
from zipfile import ZipFile


ORDER_HEADERS = [
    "OrderID", "CustomerID", "OrderDate", "ProductID", "Quantity", "Discount",
    "PaymentMethod", "Status", "Age", "City", "SignupDate", "CustomerSegment",
    "ProductName", "Category", "UnitPrice", "Sales", "OrderValue",
]


def make_xlsx(path: Path, *, rows: list[list[object]] | None = None, formula: bool = False) -> Path:
    rows = rows or [
        ["OrderId", "Region", "Amount"],
        ["SO-001", "South", 100],
        ["SO-002", "South", 150],
        ["SO-002", "North", None],
    ]
    xml_rows = []
    for row_number, row in enumerate(rows, 1):
        cells = []
        for index, value in enumerate(row):
            if value is None:
                continue
            reference = f"{chr(65 + index)}{row_number}"
            if isinstance(value, str):
                cells.append(f'<c r="{reference}" t="inlineStr"><is><t>{escape(value)}</t></is></c>')
            else:
                f = "<f>10*10</f>" if formula and row_number == 2 and index == 2 else ""
                cells.append(f'<c r="{reference}">{f}<v>{value}</v></c>')
        xml_rows.append(f'<row r="{row_number}">{"".join(cells)}</row>')
    path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(path, "w") as archive:
        archive.writestr(
            "xl/workbook.xml",
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="Sales" sheetId="1" r:id="rId1"/></sheets></workbook>',
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>',
        )
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f'<sheetData>{"".join(xml_rows)}</sheetData></worksheet>',
        )
    return path


def make_csv_shaped_xlsx(path: Path) -> Path:
    """Synthetic rows inspired by the supplied CSV schema; no source rows copied."""
    return make_xlsx(path, rows=[
        ORDER_HEADERS,
        ["TEST-001", "C-001", "2026-09-01", "P-01", 2, 10, "Card", "Completed", 29, "South City", "2024-01-10", "Retail", "Sample A", "A", 100, 180, 180],
        ["TEST-002", "C-001", "2026-09-02", "P-01", -1, 10, "Card", "Returned", 29, "South City", "2024-01-10", "Retail", "Sample A", "A", 100, -90, -90],
        ["TEST-003", "C-002", "2026-09-03", "P-02", 0, 0, "Cash", "Cancelled", 41, "North City", "2023-05-03", "Business", "Sample B", "B", 60, 0, 0],
    ])


def make_pbip(root: Path, *, legacy: bool = False) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "Retail.pbip").write_text("{}", encoding="utf-8")
    report = root / "Retail.Report"
    report.mkdir()
    (report / "definition.pbir").write_text(json.dumps({"version": "4.0"}), encoding="utf-8")
    if legacy:
        (report / "report.json").write_text("{}", encoding="utf-8")
    else:
        definition = report / "definition"
        definition.mkdir()
        (definition / "report.json").write_text(json.dumps({"$schema": "example"}), encoding="utf-8")
    model = root / "Retail.SemanticModel" / "definition"
    model.mkdir(parents=True)
    (model / "model.tmdl").write_text("model Model\n", encoding="utf-8")
    return root
