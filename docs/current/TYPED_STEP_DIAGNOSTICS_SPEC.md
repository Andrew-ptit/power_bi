# Typed Step Diagnostics — đặc tả kỹ thuật và lát triển khai

| Thuộc tính | Giá trị |
|---|---|
| Phiên bản | 0.2 — Implemented, manual validation pending |
| Ngày | 2026-10-18 |
| Phạm vi | Typed Steps trong Excel task pane, Problem Chain hiện hành |
| Tài liệu liên quan | `PROBLEM_CHAIN_SPEC.md`, `PQ_CODE_M_SPEC.md`, `IMPLEMENTATION_PLAN.md` |
| Trạng thái sản phẩm | Đã triển khai code và focused checks cho Excel Table; usedRange đang dùng fallback deterministic an toàn, chưa có hard-case profiler; chưa chạy full regression, Excel runtime hoặc manual sideload |

## 1. Quyết định và ranh giới

Người dùng đã chốt: tại một step trung gian, **Chạy toàn bộ** thực thi nguồn và toàn bộ dependency closure đến đúng step được chọn, để chẩn đoán. Kết quả vào staging; **Xác nhận** chỉ lưu step cache trong phiên, **không ghi** sheet. Chỉ output cuối của toàn pipeline mới đi qua Preview → approval → ghi values vào `PQ_Typed_Result` có marker. Không thêm đường Apply một phần pipeline, không đổi Advanced M, không tự Save và không lưu full result hoặc sample rows trong Custom XML.

Giới hạn của luồng chẩn đoán step mới: **100.000 dòng, 75 cột, 1.000.000 ô**, lấy ngưỡng nào chạm trước. Với `rowCount` là số dòng dữ liệu, số ô tính cả hàng header: `(rowCount + 1) × columnCount`. Các ngưỡng này chặt hơn mã Typed/Advanced hiện có (100.000/200/2.000.000); tài liệu này **chưa thay đổi** giới hạn của các endpoint hiện hành. Workbook export vẫn tối đa 32 MiB; giới hạn 20 nguồn, 50 steps, prompt và schema Typed vẫn giữ nguyên.

### 1.1 Khái niệm

| Tên | Ý nghĩa |
|---|---|
| Mẫu kiểm tra | Tối đa 20 dòng được chọn có chủ đích; không được mô tả là đại diện thống kê. |
| Source profile | Metadata cục bộ để chọn dòng: ordinal, null/blank, độ dài, ký tự bất thường, giá trị cực trị. Không phải dữ liệu lưu trong workbook history. |
| Step diagnostic run | Excel runtime chạy compiled M của dependency closure đến step được chọn trên workbook tạm. |
| Staging | Kết quả chưa xác nhận; không thay cache, không có quyền ghi sheet. |
| Confirmed step cache | Kết quả chẩn đoán được xác nhận, chỉ phục vụ xem lại/chạy tiếp; không phải approval hoặc payload Apply. |
| `dataVersion` | Tín hiệu người dùng báo nguồn đổi; không chứng minh dữ liệu thực tế không đổi. |

## 2. Lấy mẫu và profile

**TSD-FR-001.** Thay logic lấy 20 dòng đầu trong `taskpane.js` bằng bộ chọn mẫu kiểm tra cho Table và usedRange. Chỉ tối đa 20 dòng × 200 cột cho mỗi nguồn được đưa vào planner; source profile/full workbook không được gửi tới Codex.

**TSD-BR-001.** Bộ chọn trả ordinal gốc, seed và lý do chọn cho từng dòng. Seed = SHA-256 của `sourceDataFingerprint + sourceId + samplerPolicyVersion`; cùng nguồn và cùng policy cho cùng kết quả. Không phụ thuộc thời gian hay `Math.random()` không seed.

**TSD-BR-002.** Chọn theo thứ tự ưu tiên có dedup: đầu/giữa/cuối; ít nhất một null/blank nếu có; chuỗi dài; Unicode/ký tự điều khiển hoặc ký tự đặc biệt; numeric/date extreme nếu có; sau đó reservoir/random seeded để lấp đủ 20. Khi không có loại nào thì chỉ ghi `notFound`, không bịa ví dụ. Nếu >20 ứng viên, ưu tiên cột được step chọn sử dụng rồi phân bổ công bằng giữa các cột; UI không hứa đã bao phủ mọi trường hợp khó.

**TSD-BR-003.** Profile được tính từ workbook export ở coordinator khi nạp/refresh nguồn, không tải cả cột qua Office.js thành nhiều request cell-by-cell. Cache profile trong phiên theo workbook identity, source ID, source fingerprint, `dataVersion` và sampler policy version. Cùng fingerprint/version tái dùng; source fingerprint khác thì tính lại dù người dùng quên tích ô nguồn đổi. Không lưu raw profile hoặc sample trong Custom XML; không log raw cells.

**TSD-BR-004.** Nếu profile không thể quét nguồn trong giới hạn workbook/time, trả lỗi hoặc nhãn `profileIncomplete` và mẫu fallback có seed; không gọi fallback là đã tìm đủ dòng khó. Trước khi Preview/runtime, fingerprint vẫn phải được đối chiếu độc lập.

## 3. Chạy đến step được chọn

**TSD-FR-002.** Nút `Chạy toàn bộ đến bước này` xuất hiện trên step card của revision là committed HEAD, `reviewReady`, output kind `table`, không có blocker. Nút không dùng double-click. UI hiển thị số dòng nguồn dự kiến và `Thời gian ước tính` hoặc `Chưa đủ dữ liệu ước tính`; ước tính dựa trên các lần Excel runtime thực đo cùng operation class và quy mô, không cam kết thời gian hoàn tất.

**TSD-BR-005.** Coordinator dựng transitive dependency closure của `selectedStepId` theo graph; giữ đúng thứ tự input của merge/append và thứ tự topo. Compiler sinh một bản M tạm với `in` trỏ tới selected step. Không sửa revision, `finalOutputStepId`, `reviewHash`, compiled M của final pipeline hoặc workbook history. Step sau selected step không được chạy; lỗi downstream không chặn chẩn đoán prefix nếu prefix tự hợp lệ.

**TSD-BR-006.** Run vẫn dùng Excel slot duy nhất và workbook tạm. Mọi giới hạn của mục 1 được kiểm trước và sau Excel. Chạy quá giới hạn hoặc lỗi refresh không tạo staging và không thay cache. Trong v1, job đồng bộ; progress chỉ có các trạng thái `preparing`, `excelRunning`, `measuring`, `ready`, không hiển thị % giả. Resume/batch per-row không thuộc tính năng này.

**TSD-BR-007.** Kết quả diagnostic gồm `inputRows`, `outputRows`, `outputColumns`, `blankCells`, `errorCells`, tối đa 5 dòng lỗi mẫu (ordinal và cột, nội dung lỗi đã rút gọn), tối đa 20 dòng output mẫu, `elapsedMs`, Excel version và `compiledMHash`. `blankCells` là null hoặc chuỗi rỗng ở output, tính cả hai nhưng loại trừ header. `errorCells` là lỗi M còn tồn tại ở output của selected step, không đồng nghĩa số ô lỗi gốc trong Excel. Nếu helper không đo được chính xác, trả `metricStatus: unavailable` và hiển thị “không đo được”, tuyệt đối không thay bằng 0; release gate yêu cầu xử lý rõ trường hợp này.

## 4. Staging, xác nhận và cache

**TSD-FR-003.** Một panel session có tối đa một step-diagnostic staging đang hoạt động. Trạng thái: `running → ready → confirmed` hoặc `running/ready → cancelled|failed|stale`. Staging không chứa approval token và không cấp write payload. Hủy hoặc lỗi giữ nguyên confirmed cache cũ.

**TSD-BR-008.** Xác nhận yêu cầu recheck session, workbook identity, committed HEAD/revision, `reviewHash`, selected step, graph, source schema và **source-data fingerprint hiện hành**. `dataVersion` phải bằng `runVersion`, nhưng khớp version không thay được fingerprint. Nếu bất cứ khóa nào lệch, trả stale và không thay cache. Confirm là atomic replace sau khi validation hoàn tất; cache cũ chỉ bị thay sau confirm thành công.

**TSD-BR-009.** Mỗi step có:

```text
paramsHash   = SHA-256(canonical(operationType, parameters, compilerPolicyVersion))
inputVersion = SHA-256(canonical(ordered input cache keys OR referenced source fingerprints))
stepCacheKey = SHA-256(canonical(stepId, inputVersion, paramsHash, schemaPolicyVersion))
```

Các input của merge/append phải hash đúng thứ tự. Tên hiển thị/note không làm đổi key. Đổi parameter hoặc producer làm key của step đó và descendants đổi; sibling không phụ thuộc giữ key. `dataVersion` là phụ trợ kiểm stale, không được dùng làm input duy nhất. Bản cache tái dùng qua revision chỉ khi stepId ổn định, key bằng nhau và HEAD/review/source checks của revision hiện tại pass; cached result không tự trở thành approval.

**TSD-BR-010.** Budget đã khóa cho v1: step cache chỉ session-memory, tối đa 5 confirmed step entries và 32 MiB tổng độ dài Base64 values-only packages, FIFO khi confirm entry mới. Final-result cache hiện hành (tối đa 5/64 MiB) là namespace/budget riêng, không bị step cache eviction. Tối đa một staging result, tối đa 48 MiB encoded; nếu vượt thì fail có mã lỗi, không evict confirmed cache để nhường chỗ. Temp workbook được cleanup theo coordinator temp manager. Đóng/expire session, đổi workbook hoặc chain xóa step cache/staging. Không lưu trong Custom XML.

**TSD-BR-011.** Cache nên dùng cho step có thời gian đo được và kết quả vừa giới hạn; UI không hứa mọi step sẽ nhanh hơn. Có thể chạy lại step rẻ thay vì materialize cache; trong v1, cache miss/eviction tự chạy lại diagnostic khi người dùng bấm nút, không ngầm ghi sheet. Group cache theo từng nhóm và incremental recompute nằm ngoài phạm vi v1 vì cần identity nhóm và change tracking chính xác.

## 5. API đề xuất (song song, không phá `/api/pq/v2/*` hiện có)

Tất cả endpoint yêu cầu session token; ID/fingerprint authoritative do coordinator tạo, không nhận nguyên trạng từ AI. Request có `revisionId`, `selectedStepId`, `baseHistoryHash` khi thích hợp. Không endpoint nào ở đây trả payload để task pane ghi sheet.

| Endpoint | Input chính | Output chính |
|---|---|---|
| `POST /api/pq/v2/step-diagnostics/samples` | `workbook`, `workbookBase64`, `sourceId`, `selectedStepId` | `profileId`, `sourceFingerprint`, `samplerPolicyVersion`, tối đa 20 sample rows và reason codes |
| `POST /api/pq/v2/step-diagnostics/runs` | `revisionId`, `selectedStepId`, `baseHistoryHash`, `workbook`, `workbookBase64` | `stagingId`, `runVersion`, `stepCacheKey`, metrics, mẫu, `status: ready` |
| `POST /api/pq/v2/step-diagnostics/confirms` | `stagingId`, `revisionId`, `selectedStepId`, `baseHistoryHash`, workbook identity + current `workbookBase64` | `cacheId`, `status: confirmed`, `cachedAt`; không có `resultWorkbookBase64` |
| `POST /api/pq/v2/step-diagnostics/cancels` | `stagingId` | `status: cancelled`; idempotent với staging đã cancelled |
| `POST /api/pq/v2/step-diagnostics/cache/inspect` | `revisionId`, `selectedStepId`, `baseHistoryHash`, current workbook/fingerprint | cache hit/stale/miss + metrics/mẫu nếu valid; không trả write payload |

`runs` chỉ gọi Excel sau V1–V9 Typed validation và source fingerprint preflight. Response chứa giới hạn kết quả và các chỉ số, không chứa toàn bộ bảng để tránh đẩy 48 MiB vào UI. `confirms` chỉ thay step cache; muốn ghi sheet vẫn phải dùng final-output Preview/approval/apply hiện hành. API cần status HTTP/code nhất quán với server: 409 stale/HEAD, 429 Excel busy, 413/422 limit, 502 runtime, 401 expired; map cụ thể được khóa trong lát API trước UI.

## 6. Luồng lỗi

| Code | Khi nào | Hành vi UI |
|---|---|---|
| `TSD_HEAD_MISMATCH` | Selected revision không còn là HEAD hoặc history hash đổi | Không chạy/confirm; đọc lại history |
| `TSD_STEP_NOT_FOUND` | Step ID không thuộc revision | Không chạy |
| `TSD_SOURCE_STALE` | Schema/data fingerprint, workbook identity hoặc `dataVersion` đổi | Không confirm/cache; Preview lại |
| `TSD_GRAPH_INVALID` | Dependency closure thiếu/cycle/không topo | Không gọi Excel; chỉ bước hỏng |
| `TSD_RESULT_LIMIT` | >100.000 dòng, >75 cột hoặc >1.000.000 ô | Bỏ staging; giữ cache cũ |
| `TSD_STAGING_LIMIT` | Encoded staging >48 MiB | Bỏ staging; giữ cache cũ |
| `TSD_METRICS_UNAVAILABLE` | Helper không thể xác định lỗi/blank chính xác | Hiển thị `không đo được`, không báo 0; release gate xử lý |
| `TSD_EXCEL_FAILED` | Refresh/read-back thất bại | Không tạo confirmed cache |
| `TSD_STAGING_STALE` | Staging cancelled/expired, revision hoặc source đổi | Không confirm; giữ cache cũ |
| `COORDINATOR_BUSY` | Excel slot đang chạy | 429, không xếp hàng hay tự retry |

Nếu Excel đã chạy nhưng task pane/HTTP bị ngắt, coordinator dọn staging khi session hết hạn; không có worksheet write để rollback. Không log prompt raw, cells, Base64 hoặc temp path.

## 7. Acceptance criteria và test oracle

| ID | Kịch bản | Kết quả bắt buộc |
|---|---|---|
| TSD-AC-01 | Nguồn có 20 dòng đầu sạch, giữa/cuối có blank/long/unusual/extreme | Mẫu ≤20, seed lặp lại cho cùng fingerprint, hiển thị ordinal/reason; không gọi là đại diện |
| TSD-AC-02 | Người dùng quên tăng `dataVersion` nhưng sửa một ô nguồn | Profile/cache/confirm cũ stale do fingerprint; không tái dùng kết quả cũ |
| TSD-AC-03 | Chọn step giữa A→B→C→D rồi chạy | Chỉ A/B/C được compile/chạy; revision/final output/history không đổi; zero worksheet write |
| TSD-AC-04 | Merge/append hai nhánh | Dependency closure có đủ hai nhánh, thứ tự inputs giữ nguyên |
| TSD-AC-05 | Run xong rồi Hủy | Cache cũ deep-equal, staging bị bỏ, zero worksheet write |
| TSD-AC-06 | Run xong, edit upstream hoặc đổi HEAD trước Confirm | Confirm trả stale, cache cũ giữ nguyên |
| TSD-AC-07 | Đổi tham số B trong A→B→C và nhánh A→D | Key B/C đổi; A/D không đổi |
| TSD-AC-08 | Cùng `dataVersion`, fingerprint nguồn khác | Cache inspect/confirm từ chối |
| TSD-AC-09 | Kết quả đúng 100.000 dòng, 75 cột nhưng >1 triệu ô | Bị chặn theo giới hạn ô; không có cache mới |
| TSD-AC-10 | Kết quả đúng từng ngưỡng độc lập, và vượt mỗi ngưỡng một đơn vị | Boundary pass/fail theo ba giới hạn; tính cả header |
| TSD-AC-11 | Kết quả có null, rỗng và M error | `blankCells`/`errorCells` đúng định nghĩa; ≤5 dòng lỗi mẫu; không biến unknown thành 0 |
| TSD-AC-12 | Confirm step trung gian | Chỉ step cache thay; `PQ_Typed_Result`, source, approval và final-result cache không đổi |
| TSD-AC-13 | 6 confirm hoặc vượt 32 MiB step cache | FIFO/size cap đúng; final-result cache 5/64 MiB không bị evict |
| TSD-AC-14 | Excel slot bận, runner lỗi, session hết hạn | Fail fast, không nhận cache/approval giả; temp cleanup |
| TSD-AC-15 | Final pipeline Preview/Apply cũ sau feature | Contract, result marker và workbook write rules không regression |

Test phải có oracle độc lập: so selected-step result với Excel Power Query chạy cùng compiled prefix trên fixture, kiểm source workbook hash trước/sau diagnostic, so cache hashes và số runner calls. Fake runner chỉ là unit evidence; runtime Excel và manual sideload là release gate riêng. Không ghi `Complete` nếu runtime/Excel bị skip, timeout hoặc còn `TSD_METRICS_UNAVAILABLE` chưa giải quyết.

## 8. Chia lát triển khai

| Lát | Nội dung và file chính | Test/exit gate |
|---|---|---|
| S0 — baseline/contract | Khóa API JSON, giới hạn 100k/75/1m, định nghĩa error/blank, benchmark fixture và chốt budget step cache/staging đề xuất; ghi lại Advanced/Typed baseline | Schema/API contract và boundary tests; không sửa UI trước khi contract ổn |
| S1 — sampler/profile | Bộ chọn deterministic và profile cache trong `taskpane.js` + coordinator source adapter; chỉ metadata/mẫu bounded ra planner | 20-row/seed/edge cases, data fingerprint stale, nhiều Table/usedRange, không lộ raw cells trong logs |
| S2 — prefix runner | Graph closure, compiler `in` selected step, Excel helper metrics, staging run API; không có Confirm | Golden test đơn/đa nguồn, zero worksheet write, giới hạn, lỗi Excel, runtime Excel smoke |
| S3 — staging/step cache | Confirm/cancel, step key, FIFO/size, dataVersion + fingerprint + HEAD checks | Cancel/failed confirm preserve old, graph invalidation, race/TTL, 6-entry FIFO và 32/48 MiB caps |
| S4 — task-pane UX | Nút rõ ràng, estimate từ đo đạc, staging report và cache label; final Apply giữ nguyên | JS fake-host, accessibility/manual click path, stale/busy messaging, Excel sideload |
| S5 — release regression | Cross-review độc lập, focused + full tests, Advanced/Typed regression, runtime Excel, performance measurements | Báo cáo pass/fail/skip, source hash, wall time/peak memory, max cache bytes và manual evidence; chỉ chốt khi tất cả gate đạt |

Thứ tự S0→S5 là bắt buộc vì UI không được suy đoán metrics, trạng thái hoặc cache authority trước khi server contract và Excel helper có bằng chứng. S0–S4 đã được triển khai ngày 2026-10-18 và qua focused checks; S5 chưa chạy theo yêu cầu người dùng. Vì chưa có Excel runtime/manual sideload và full regression, trạng thái phát hành vẫn là **manual validation pending**, không phải `Complete`.
