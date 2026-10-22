# Problem Chain Wave 0 summary — 2026-10-14

## Decision

Wave 0 required spike gates are **Pass**. Automated validation, actual Excel Office.js add/get/set/delete, Save/reopen, Save As, package linkage and source-semantic preservation have evidence. The user accepted closure on 2026-10-14. Product implementation has not started.

## Delivered isolated artifacts

- Standalone Office.js Custom XML spike under `spikes/problem_chain_custom_xml/officejs`.
- Canonical JSON/Base64/XML codec with SHA-256 read-back and a 2 MiB canonical JSON limit.
- Local-only evidence receiver with strict allowlisted fields and 32 KiB request cap.
- Package oracle and strict persisted-history/security validator.
- Independent adversarial, fake-host, cross-language and OOXML package tests.

No product code or production manifest was modified. The product manifest and active catalog manifest both remain SHA-256 `8316ED910CE98DE3464479BE3D8B673175C482A2DA536ABC1FB48E338BEEBAC3`.

## Defects caught before product integration

1. Autorun cleanup could delete pre-existing Problem Chain history after an initial-state failure. Cleanup now deletes only IDs created by the current run; a regression test proves existing history remains byte-for-byte unchanged.
2. Persisted source metadata could hide sample rows or unknown fields. Strict allowlists now reject them.
3. `sampleStore` accepted malformed keys/shapes and oversized samples. It now requires content-hash keys, exact shape, finite scalar values and 20 × 200 bounds.
4. The OOXML oracle accepted orphan Custom XML items. It now requires workbook relationship, item-properties relationship, content type and namespace linkage.
5. Excel serialization differences (`inlineStr`/shared strings and numeric formatting) caused false failures. Semantic normalization now compares workbook meaning rather than raw XML representation.
6. Evidence validation could accept an incomplete “Pass”. It now requires the exact eight-step transition, near-limit bounds, duplicate block codes, unchanged sentinel and cleanup of exactly two run-owned parts.
7. The evidence server oversized-body test could reset the socket and the privacy assertion falsely matched the word `XML` inside a legitimate error code. Both tests were corrected and now fail for structural leaks instead.

## Measured evidence

| Gate | Result | Measurement |
|---|---|---|
| Office.js isolated `npm test` | Pass | Root rerun: 2,257.4 ms; 8 fake autorun steps; 39 sync boundaries; 2,952-byte redacted evidence; 3/3 JS↔Python oracle tests |
| Security/adversarial contract | Pass | 22/22; 8.825 s test time, 9.074 s root wall time |
| Package oracle unit | Pass | 5/5; 34 ms test time, 325.5 ms root wall time |
| Near-limit codec microbenchmark | Pass | 2,093,056-byte JSON; 2,790,987-byte XML; build mean 27.0 ms; parse mean 73.9 ms |
| Full package/COM evidence from prior clean run | Pass | 22/22 package/security cross-check; source SHA unchanged; no helper Excel PID remained |
| High-entropy 2.03 MiB package round-trip | Pass | 19.831 s; `.xlsx` grew by 1,922,740 bytes |
| Independent COM rerun | Timed out/Failed | Hung about 33 minutes; only test-owned processes were stopped; not counted as Pass |
| Actual Excel Office.js autorun | Pass | Excel 16.0.20430.20146, ExcelApi 1.5; 8/8 operations; A1 unchanged; final count 0 |
| Save/reopen | Pass | Persisted count 1; hash read-back passed in 87.3 ms |
| Save As/reopen | Pass | Persisted count 1; hash read-back passed in 123.1 ms |
| Co-authoring | Unsupported | v1 remains single-user/single-panel |

The 2.79 MiB XML representation is about 33.3% larger than canonical JSON because of Base64. In actual Excel, the near-limit operation took 1,554.8 ms; its write sync took 228.1 ms and XML read-back sync took 188.3 ms.

## Desktop attempt and cleanup

An initial unattended attempt from 20:51 to 20:55 (+07:00) did not load the task pane and remains recorded as blocked. A later manual sideload loaded the pane and passed the runtime gates. The saved original and Save As copy each contained exactly one linked Problem Chain part with identical history hash and empty `sampleStore`. Their workbook semantic hash matched the source fixture, proving the test did not alter worksheet meaning.

## Next gate

Create `PROBLEM_CHAIN_SPEC.md` as the repository source of truth, link it from the existing specifications, then begin Phase 1 linear Problem Chain implementation. CSV format behavior remains a negative warning test, and co-authoring remains unsupported in v1.
