import argparse
import json
import sys

from .workflow import import_sources


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    parser = argparse.ArgumentParser(description="Local Excel + PBIP assistant (read-only import slice)")
    parser.add_argument("--pbip", required=True, help="PBIP project root directory")
    parser.add_argument("--excel", action="append", default=[], help=".xlsx path; repeat for multiple files")
    parser.add_argument("--excel-sheet", action="append", help="Worksheet name(s) selected from each Excel file")
    parser.add_argument("--excel-table", help="Named Excel table selected from each Excel file")
    parser.add_argument("--csv", action="append", default=[], help=".csv path; repeat for multiple files")
    parser.add_argument("--csv-encoding", help="Explicit encoding applied to selected CSV files")
    parser.add_argument("--csv-delimiter", choices=[",", ";", "tab", "|"], help="Explicit CSV delimiter")
    parser.add_argument("--csv-header-row", type=int, default=1, help="One-based logical CSV header record")
    parser.add_argument("--insight", default="", help="Analysis question, treated as a hypothesis")
    args = parser.parse_args()
    sources = [*args.excel, *args.csv]
    delimiter = "\t" if args.csv_delimiter == "tab" else args.csv_delimiter
    csv_options = {
        path: {
            **({"encoding": args.csv_encoding} if args.csv_encoding else {}),
            **({"delimiter": delimiter} if delimiter else {}),
            "header_row": args.csv_header_row,
        }
        for path in args.csv
    }
    xlsx_options = {
        path: {
            **({"sheet_names": args.excel_sheet} if args.excel_sheet else {}),
            **({"table_name": args.excel_table} if args.excel_table else {}),
        }
        for path in args.excel
    }
    result = import_sources(args.pbip, sources, args.insight, csv_options=csv_options, xlsx_options=xlsx_options)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["state"] == "imported_needs_proposal" else 2


if __name__ == "__main__":
    raise SystemExit(main())
