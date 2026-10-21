# Office.js runtime evidence — passed

## Actual Excel autorun

| Field | Observed value |
|---|---|
| Status | **Pass** |
| Attempt | 2026-10-14 21:14–21:22 +07:00 |
| Excel | Microsoft Excel 16.0.20430.20146 x64 |
| Host/API | Excel on PC; ExcelApi 1.5 supported |
| Workbook | Disposable copy of `excel_mcp_sales_input.xlsx` |
| Safety | A1 unchanged for every completed operation; no Save call by the add-in |
| Final autorun state | 0 matching parts after deleting exactly two run-owned parts |

The task pane was opened manually after CLI sideload. Excel requested the isolated page and posted a strict, redacted evidence record accepted by the local validator.

| Operation | Result | Duration |
|---|---:|---:|
| Inspect zero parts | Pass | 77.8 ms |
| Add + hash read-back | Pass | 143.9 ms |
| Get + parse | Pass | 98.1 ms |
| Set Unicode + read-back | Pass | 165.6 ms |
| Set/read near-2-MiB payload | Pass | 1,554.8 ms |
| Add duplicate | Pass | 476.0 ms |
| Detect duplicate/fail closed | Pass | 69.9 ms |
| Cleanup run-owned parts | Pass | 126.4 ms |

The near-limit payload contained 2,093,056 canonical JSON bytes. Its write sync took 228.1 ms and XML read-back sync took 188.3 ms. Duplicate handling returned `PQPC_DUPLICATE_XML_PART`; cleanup removed two run-owned parts and left zero.

## Save, reopen and Save As

After autorun cleanup, one small Unicode document was added through Office.js and saved manually.

| Gate | Result | Evidence |
|---|---|---|
| Save → close → reopen | Pass | Existing part caused expected `AUTORUN_INITIAL_STATE_NOT_EMPTY`; owned cleanup deleted 0; final count remained 1; `get-parse` passed in 87.3 ms |
| Save As `.xlsx` → close → reopen | Pass | Final count remained 1; `get-parse` passed in 123.1 ms |
| Original persisted file | Pass | 15,308 bytes; SHA-256 `AD9E850967CC80EEC16FADEE3BAFB523C1EF0387BE1BC50AB32937219AD1DFB5` |
| Save As copy | Pass | 15,315 bytes; SHA-256 `629E922C807708C25DB2AF8F1200AE1AB19A4406E1C186CCC3207E8FDE30D1B2` |
| Custom XML package | Pass | Exactly one linked Problem Chain part in each package |
| Payload equality | Pass | Both copies: 1,230 canonical bytes; history hash `sha256:7b70c3a09d9e7659f7d5a6be0344344867562bf6367d637925d93d2bc59021ff` |
| Default sample persistence | Pass | `sampleStore` empty in both packages |
| Source workbook semantics | Pass | Fixture and both saved copies share semantic SHA-256 `36ce27e3c199f7ea0f4ac08a92538f1dfcfa66a2cdf2576311a6b5a643bc488c` |

The fail message on reopen is expected safety behavior: autorun requires a clean namespace and refuses to overwrite or delete pre-existing history.

## Remaining scope boundaries

- CSV persistence negative test: not run. The product must warn that unsupported formats do not preserve history.
- Co-authoring: unsupported by v1 design; no merge or race-free claim is made.
- An earlier unattended CLI attempt opened Excel but did not load the task pane. It remains recorded as a blocked attempt and was not counted as runtime evidence.

The local server was stopped after capture. The user's existing workbook was not closed, saved or modified by the spike workflow.
