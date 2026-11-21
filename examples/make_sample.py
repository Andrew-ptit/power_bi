"""Create tiny synthetic inputs for trying the read-only import command."""

import argparse
import sys
from pathlib import Path

from tests.support.fixtures import make_csv_shaped_xlsx, make_pbip, make_xlsx


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True, help="New directory for synthetic sample files")
    args = parser.parse_args()
    output = Path(args.out).resolve()
    if output.exists():
        parser.error("Output directory already exists; choose a new one")
    output.mkdir(parents=True)
    make_pbip(output / "Retail")
    make_xlsx(output / "Sales.xlsx")
    make_csv_shaped_xlsx(output / "Orders_synthetic.xlsx")
    print(f"Sample created in {output}")
    print(f"py -m pbip_assistant --pbip \"{output / 'Retail'}\" --excel \"{output / 'Sales.xlsx'}\" --insight \"Doanh thu miền Nam giảm?\"")


if __name__ == "__main__":
    main()
