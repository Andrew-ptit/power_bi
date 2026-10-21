# Problem Chain Custom XML package/COM oracle

This Wave 0 spike is deliberately isolated from product code. It modifies only disposable copies.

Run the small round-trip oracle:

```powershell
py -m spikes.problem_chain_custom_xml.package_oracle.run_spike --fixture tests/fixtures_excel_mcp/excel_mcp_sales_input.xlsx
```

Run the duplicate-namespace and near-2-MiB cases too:

```powershell
py -m spikes.problem_chain_custom_xml.package_oracle.run_spike --fixture tests/fixtures_excel_mcp/excel_mcp_sales_input.xlsx --full
```

The oracle checks Excel COM add/save/reopen/Save As, namespace lookup, canonical JSON hashing, semantic preservation of cells/formulas/Tables, OOXML part changes, exact source-file hash preservation, and cleanup of the helper-created Excel PID. It does not count as Office.js sideload evidence.
