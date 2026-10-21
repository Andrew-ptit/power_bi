# Problem Chain Custom XML — Office.js Wave 0

This is an isolated spike. It does not import product task-pane code, does not edit the product manifest, does not call `Save`, and never writes worksheet cells. The active sheet's `A1` is read before and after every operation as a source sentinel.

## Automated checks

```powershell
cd spikes/problem_chain_custom_xml/officejs
npm test
```

The Node checks cover canonical JSON, UTF-8/Base64, SHA-256 read-back, Vietnamese/Unicode, corrupt envelopes, DTD rejection, the 2 MiB boundary, the ExcelApi 1.5 runtime gate, all four Custom XML operations, source-sentinel guard, and absence of an auto-Save call. A fake Office host exercises the task-pane operation flow, while a Python cross-oracle proves the JavaScript envelope/document is accepted by the independent security contract and vice versa. Neither substitute is counted as real Excel Office.js evidence.

The autorun cleanup tracks the IDs created by that run and deletes only those IDs. If the namespace is non-empty at startup, the run fails closed and preserves every pre-existing part. The local evidence receiver also checks exact per-step part counts, a canonical payload within 4,098 bytes of the 2 MiB limit, duplicate-block codes, and cleanup of exactly the two run-owned parts before accepting a `Pass` record.

## HTTPS server

Install/trust the Microsoft development certificate once, then serve the spike:

```powershell
npx --yes office-addin-dev-certs install
cd spikes/problem_chain_custom_xml/officejs
node server.js
```

The server binds only `127.0.0.1:3100`, uses the certificates at `%USERPROFILE%\.office-addin-dev-certs`, serves only files inside this folder, disables caching, and logs request path/status/timing without XML or workbook data. Override paths with `PQPC_SPIKE_CERT`, `PQPC_SPIKE_KEY`, or the port with `PQPC_SPIKE_PORT`.

For a bounded disposable autorun attempt, set `PQPC_SPIKE_AUTORUN=1`. Requests for `taskpane.html` are then redirected to `taskpane.html?autorun=1`; the checked-in manifest is not modified. A local `POST /evidence` is still client-reported evidence and must be corroborated with a newly launched Excel PID, Office runtime log, server request log, and workbook/package hashes.

Sideload `manifest.xml` as a separate development add-in. Do not copy it to `C:\AddinManifests\manifest.xml`; that path is the product catalog. One option on a development machine is:

```powershell
npx --yes office-addin-dev-settings sideload manifest.xml
```

If the command is unavailable for the installed Office build, use Excel's trusted shared-folder catalog and point it at a separate temporary folder containing only this spike manifest.

## Manual evidence checklist

Record Excel version/build, API capability, each UI log entry and file hashes/sizes in `MANUAL_EVIDENCE.md`.

1. Open a disposable `.xlsx`; record its SHA-256 and size.
2. Verify zero parts; add the small Unicode document; get/set/read it back.
3. Set the near-2-MiB document and retain measured duration/size.
4. Explicitly create a duplicate; verify count 2 and `PQPC_DUPLICATE_XML_PART`; clean all parts.
5. Add again, manually Save, close/reopen, then verify hash.
6. Save As `.xlsx`, reopen the copy and verify hash; confirm the original and copy later diverge independently.
7. Save As CSV only as a negative observation; no metadata persistence is promised.
8. Verify source cells, Tables and queries were unchanged with the package oracle.

Until those actions run in real Excel, PC-X-020 through PC-X-024 remain `Not run`; Node tests are not Office.js runtime evidence.

The 2026-10-14 automated desktop sideload attempt launched Excel but did not load the task pane, so the runtime gates remain **Blocked / Not run**. See `MANUAL_EVIDENCE.md` for the bounded attempt, measurements, unchanged disposable-workbook hash, and cleanup record.
