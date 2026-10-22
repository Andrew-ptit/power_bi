# PQ_Code-M — Excel task-pane feature spec

| Trường | Giá trị |
|---|---|
| Phiên bản | 0.6 — 12/10/2026 |
| Status | Current contract; see [CURRENT_STATUS.md](CURRENT_STATUS.md) |
| Owner | Product owner của Excel add-in |
| Reviewer/approver | Người dùng workbook; manual sideload sign-off còn mở |
| Nguồn | Yêu cầu ngày 06–12/10/2026; `EXCEL_MCP_SPEC.md`, `EXCEL_CONNECTOR_CONTRACT.md` |

Current verification and Advanced M deferral: [CURRENT_STATUS.md](CURRENT_STATUS.md).

## Runtime policy and lifecycle

### Advanced M Trusted Mode

Advanced M dùng policy do coordinator sở hữu với ID `advanced-m-trusted-v1`. Đây là **informed consent**, không phải sandbox hoặc DLP: arbitrary M được phép dùng connector ngoài workbook, file/web/database và credential Excel. UI chỉ bật Advanced M khi bootstrap trả đúng toàn bộ policy và `sessionId`; `/api/pq/run-sheet` chỉ chạy khi `riskAccepted=true` và `riskPolicyId` khớp. Acknowledgement được nhớ theo `sessionId + policyId + workbookIdentity`; Cancel không đọc/export workbook và không gọi runner. Mỗi lần Apply vào source vẫn phải xác nhận riêng. Không backup bắt buộc, không auto-Save và không hứa rollback/Ctrl+Z.

### Typed Planner strict schema

Schema Structured Output có đúng 15 operation variants và 10 expression variants đệ quy. Mọi object khai báo `properties`, yêu cầu toàn bộ property và đóng `additionalProperties:false`; field tùy chọn dùng nullable. Preflight chạy trước executable lookup/Codex call và đối chiếu operation discriminator, input arity, local `$defs` reference, expression kind và Python catalog. Schema drift trả `CODEX_SCHEMA_INVALID` với zero Codex call. Error mapping chuẩn: schema `500`, auth/unavailable `503`, rate limit `429`, timeout `504`, generic failure `502`; không trả/log raw stderr, prompt hoặc workbook sample.

### Session, concurrency và temp lifecycle

Coordinator cấp token ngẫu nhiên 256-bit, idle TTL 1.800 giây và absolute TTL 28.800 giây. Request hợp lệ gia hạn idle nhưng không kéo absolute deadline; token cũ/hết hạn trả `401 TOKEN_EXPIRED`. `POST /api/session/close` đóng ngay hoặc chờ job đang chạy kết thúc; bootstrap trong lúc session đang closing còn job trả `429 COORDINATOR_BUSY` và `Retry-After: 2` để không trộn state giữa hai session. Task pane có thể bootstrap lại một lần nhưng không replay POST cũ.

Codex và Excel có hai slot độc lập, mỗi slot tối đa một job; job cùng loại thứ hai bị từ chối ngay bằng `429`, không xếp hàng. Approval/prepare/complete dùng state lock riêng. Temp artifact của coordinator nằm dưới marked root `local-data-copilot/run_<nonce>`; operation cleanup dùng `finally`, janitor chạy lúc startup và mỗi 60 giây, chỉ xóa marker hợp lệ quá một giờ hoặc legacy directory hợp lệ quá 24 giờ. Không cấp phát được temp trả `507 TEMP_STORAGE_UNAVAILABLE` trước subprocess.

## Typed Steps v2 — luồng mặc định

Typed Steps là chế độ mặc định của tab Power Query. Codex chỉ trả draft có cấu trúc; coordinator cấp toàn bộ ID có thẩm quyền, chuẩn hóa draft thành revision bất biến, chạy validator/lineage engine và chỉ sau đó compiler tất định mới sinh M. Typed mode không nhận raw M từ AI hoặc client và chỉ đọc Excel Table/usedRange trong workbook đang mở. `Advanced M` vẫn chạy song song; từ v0.5, Chạy thử tạo/reuse sheet preview values-only, còn Apply là hành động riêng để thay values của đúng nguồn đã preview.

Luồng tin cậy:

1. Task pane gửi prompt và bounded workbook snapshot, tối đa 20 dòng × 200 cột mỗi nguồn.
2. Codex trả typed draft theo `codex_pq_typed_response.schema.json`; AI không tạo validation, runtime evidence, approval hoặc authoritative ID.
3. Coordinator cấp `planId`, `snapshotId`, `revisionId`, `stepId`, `columnId`; validator kiểm schema, graph, source, lineage, type, catalog, security và compile.
4. Compiler template sinh một M binding cho mỗi step; `in` trỏ đúng `finalOutputStepId`; output cuối luôn là table.
5. Excel helper refresh compiled M trên workbook tạm và tạo package một sheet values-only. Preview không ghi workbook đang mở.
6. Người dùng duyệt đúng revision/preview/snapshot/review hash. Approval dùng một lần và bị vô hiệu khi plan, workbook hoặc destination thay đổi.
7. `/applies/prepare` revalidate và chỉ trả payload values-only sau approval; Office.js ghi vào sheet có marker `localDataCopilot.pqTypedResult.v2`; `/applies/complete` kiểm marker và kích thước read-back. Add-in không tự Save và không tuyên bố rollback nếu write đã bắt đầu.

Operation catalog v1 gồm source Table/usedRange; filter, select, remove, rename, change type, calculated column, sort, distinct, group, aggregate; append 2–20 table; merge rồi expand ở step riêng. Expression DSL chỉ cho literal/column reference, compare, arithmetic, boolean/not, conditional, coalesce, allowlisted function và `safeDivide`. File/web/database connector, URL/path/credential, raw/custom M và function ngoài allowlist là hard blocker.

Mọi add/edit/delete/reorder/set-final và patch được chọn tạo revision mới. Xóa producer không cascade-delete downstream; revision trở thành `blocked`. Auto-fix chỉ trả một patch khuyến nghị và tối đa hai phương án có rationale, semantic impact, risks và change list. Patch không tự áp dụng; khi chọn sẽ tạo revision mới rồi phải validation, Excel runtime preview và approval lại.

API v2 chạy song song với Advanced M:

| Endpoint | Contract |
|---|---|
| `POST /api/pq/v2/plans` | AI draft → normalize → authoritative IDs → static validation |
| `POST /api/pq/v2/revisions` | Tạo revision từ typed changes hoặc repair patch |
| `POST /api/pq/v2/repairs` | Chẩn đoán và proposal patch; không auto-apply |
| `POST /api/pq/v2/previews` | Compile và chạy Excel runtime trên workbook tạm |
| `POST /api/pq/v2/approvals` | Bind user approval với revision/snapshot/preview/hash/marker |
| `POST /api/pq/v2/applies/prepare` | Revalidate, consume approval, trả values-only payload |
| `POST /api/pq/v2/applies/complete` | Nhận read-back metadata và đóng apply attempt |

Các gate V1–V12 được hiện thực qua schema/manual contract validation, authoritative identity, graph/topology, source snapshot, column lineage, types, catalog/policy, compiler, Excel runtime, pre-apply binding và values-only read-back. Mọi blocker có `code`, `path`, `target`, `reason`, `remedy`; không có đường AI tự đánh dấu `passed` hoặc `Verified`.

Automated acceptance hiện có: normalization/lineage/compiler golden tests; stale/replay/forged approval tests; repair revision tests; full API state machine; task-pane preview/approval/write/invalidation smoke; Excel 16.0 cross-check thật cho filter → add → sort, aggregate một dòng, append strict và merge → expand. Expected result trong runtime tests được khai báo độc lập với compiler template để phát hiện sai khác chéo. Manual sideload vẫn là exit gate riêng cho Office.js bind/write/reuse trên workbook đang mở.

### Typed requirements traceability

| Requirement | Implementation evidence | Verification evidence |
| --- | --- | --- |
| PQ2-FR-001…003 | `build_source_catalog`, AI response schema, coordinator ID allocator | `test_draft_is_normalized_to_authoritative_ids_and_compiled`, API auth tests |
| PQ2-FR-004…008 | Immutable revision store, graph/lineage/type/catalog validator, template compiler | catalog golden, type mismatch, raw-M/unknown-field negative tests |
| PQ2-FR-009…013 | Compiled preview store, one-use approval, prepare/complete protocol, typed Office.js marker | full API lifecycle, JS 0-write-before-approval, static package audit, real Excel smoke |
| PQ2-FR-014…016 | Repair diagnosis + server-held proposal patches; no cascade delete | producer-delete/repair revision test; stale revision tests |
| PQ2-FR-017…018 | Workbook-only typed catalog; Advanced endpoints/UI giữ song song | policy negative test; `/api/pq/propose` coexistence và Advanced JS regression |
| PQ2-FR-019…020 | Session-memory stores/close cleanup; request-body-free coordinator logging | server lifecycle và mutation-log regression tests |

Exception/negative paths đã kiểm gồm malformed/unknown operation, dependency/cycle/column/type/policy blocker, stale snapshot/revision/preview, forged/replayed approval, failed refresh, package không thuần values và read-back mismatch. Điều kiện chưa đóng là manual sideload: bind đúng workbook, ghi/reuse/clear-tail đúng sheet marker trong Excel task pane thật và xác nhận add-in không gọi Save.

## Advanced M — mục tiêu và phạm vi tương thích

Người dùng ở nguyên trong Excel task pane, chọn nguồn trên sheet hiện hành, nhận M do Codex đề xuất hoặc tự sửa M, rồi bấm **Chạy thử và mở sheet kết quả**. Add-in chạy Power Query trong workbook **tạm**, nhập/reuse sheet có marker `PQ_Result` dưới dạng values-only và kích hoạt sheet này để người dùng review; source Table/usedRange chưa bị thay. Nếu kết quả phù hợp, người dùng bấm riêng **Áp dụng vào sheet nguồn** và xác nhận việc ghi đè. Nguồn Excel Table thì resize/thay riêng Table; nguồn usedRange thì thay toàn bộ usedRange và xóa phần đuôi cũ. Không lưu M query/connection và không tạo backup. Add-in **không tự Save**.

Tab PQ là ngoại lệ có giới hạn của quy tắc source read-only trước đây. Tab `Trợ lý` vẫn chỉ đề xuất, không áp công thức tùy ý; luồng PBIP nguồn và Excel connector W-21 còn theo copy-only. CSV cần mở/import vào workbook `.xlsx` trước khi dùng tab PQ này.

M vẫn là code tùy ý, có thể dùng `File.Contents`, `Web.Contents` và nguồn ngoài. **Một hộp xác nhận ngay trong task pane trước lần chạy M đầu tiên cho mỗi workbook trong phiên panel** nêu rõ M có thể dùng credential, gửi dữ liệu ra ngoài hoặc gây side effect không hoàn tác được; không dùng `window.confirm` vì Excel task pane không hỗ trợ. Bản tạm không phải sandbox. Các lần preview sau trên cùng workbook không hỏi lại; bấm Hủy thì chưa chạy M và lần sau vẫn hỏi. Mỗi lần Apply có một xác nhận ghi đè nguồn riêng. Nếu đổi workbook, hỏi lại. Không tự cấp credential, tắt privacy level hay bypass lỗi refresh. Không bảo đảm Ctrl+Z hoặc rollback cho thao tác ghi nguồn.

Ngoài phạm vi: tự duyệt thay người dùng, bảo đảm M do AI sinh đúng nghiệp vụ, chạy VBA/Python/PowerShell, hỗ trợ `.xlsm`/workbook mã hóa/Protected View, hay bảo đảm connector ngoài không có side effect.

## Luồng và business rules

| ID | Luật kiểm được |
|---|---|
| PQ-BR-001 | Xác nhận rủi ro một lần trước lần chạy M đầu tiên trên mỗi workbook trong phiên panel; bấm Hủy thì không chạy M và không ghi. |
| PQ-BR-002 | M chỉ chạy trong workbook `.xlsx` tạm; Chạy thử chỉ tạo/reuse một sheet `PQ_Result` có marker và copy values kết quả, không tạo query/connection và không thay source. |
| PQ-BR-003 | Apply là hành động và xác nhận riêng. Trước khi ghi phải kiểm lại workbook identity, source fingerprint và M code đúng với preview hiện hành; fingerprint chỉ bỏ qua đúng sheet preview có tên được quản lý, vẫn phát hiện thay đổi source/sheet khác. |
| PQ-BR-004 | Nguồn Excel Table: chỉ resize và thay values của đúng Table. Khi mở rộng, nếu vùng mới chiếm đã có value hoặc formula ngoài Table thì chặn trước khi ghi. |
| PQ-BR-005 | Nguồn usedRange: thay toàn bộ usedRange từ ô góc trên-trái; kết quả nhỏ hơn phải xóa hàng/cột đuôi của usedRange cũ. |
| PQ-BR-006 | Không tạo backup, không tự Save và không hứa rollback/Ctrl+Z. Nếu write đã có thể bắt đầu nhưng read-back lỗi, báo `applyFailed`/có thể ghi một phần, không tự retry. |
| PQ-BR-007 | AI đề xuất M không phải phê duyệt hoặc chứng cứ runtime; Excel refresh/read-back chỉ là runtime preview, không gắn nhãn nghiệp vụ `Verified`. |

## Yêu cầu chức năng và điều kiện đạt

| ID | Hành vi | AC/Test |
|---|---|---|
| PQ-FR-001 | Dùng cùng workbook đã đọc ở tab 1; nguồn là Table duy nhất trên sheet hiện tại, Table chứa ô đang chọn, hoặc usedRange nếu không có Table. | Không có source picker riêng. Nếu không xác định duy nhất Table, yêu cầu chọn ô trong Table; descriptor nguồn được giữ cố định từ preview tới Apply. |
| PQ-FR-002 | Gửi prompt và mẫu giới hạn tới Codex để đề xuất M có thể sửa. | Thiếu prompt/source thì không gọi Codex; output M không tự chạy. |
| PQ-FR-003 | Editor M tách khỏi text tư vấn; M giữ dấu `,` theo cú pháp Power Query bất kể locale công thức Excel dùng `;`. | Sửa M hủy preview cũ; lần chạy mới dùng chính editor hiện tại. |
| PQ-FR-004 | `Chạy thử và mở sheet kết quả` xuất snapshot, refresh M trong helper, kiểm package rồi dùng Office.js tạo/reuse sheet `PQ_Result` có marker. | Chỉ copy values và kích hoạt sheet preview; source không đổi. M/credential/timeout lỗi thì không cập nhật preview sheet. |
| PQ-FR-005 | Trước khi giữ preview, kiểm package kết quả không có formula/query/connection/macro/external link, đúng một sheet và kích thước read-back. | Payload sai bị chặn. Giới hạn ban đầu: 100.000 dòng, 200 cột, 2 triệu ô, 32 MiB compressed. |
| PQ-FR-006 | `Áp dụng vào sheet nguồn` yêu cầu xác nhận riêng, đọc lại workbook, so content fingerprint bỏ qua đúng managed preview sheet và kiểm M code, rồi dùng Office.js ExcelApi 1.13 copy values vào nguồn. | Preview stale, source/sheet khác đổi, workbook đổi hoặc thiếu API 1.13 đều chặn trước source write. |
| PQ-FR-007 | Với Table, resize đúng Table rồi copy values; với usedRange, thay toàn bộ vùng. Sau write, xóa phần đuôi cũ, kích hoạt sheet nguồn và read-back tối đa 20 dòng. | Ô ngoài Table được giữ nguyên; mở rộng đè dữ liệu ngoài Table bị chặn; read-back xác nhận kích thước và values hiển thị. |
| PQ-FR-008 | Nhắc người dùng tự quyết định Save sau khi ghi nguồn. | Không tự Save, không backup, không hứa Ctrl+Z/rollback và không tự retry khi trạng thái ghi không chắc chắn. |

## UI và hợp đồng

Tab hiển thị nguồn hiện hành dạng chỉ đọc, prompt, nút `Codex đề xuất M`, editor, nút `Chạy thử và mở sheet kết quả`, nút `Áp dụng vào sheet nguồn` và bảng trước/sau. Chạy thử tạo/reuse `PQ_Result`; nếu trùng tên với sheet người dùng không có marker thì dùng tên khả dụng, không ghi đè. Nút Apply chỉ bật khi có preview hiện hành chưa áp dụng. Backend dùng `/api/pq/propose` và `/api/pq/run-sheet`; `run-sheet` nhận export tối đa 32 MiB, M tối đa 16.000 ký tự và trả `.xlsx` một sheet values-only mã hóa base64.

Với sheet thường không có Table, helper tạo `PQ_Input` **chỉ trong workbook tạm**. Với Table có sẵn, M nguồn mặc định là `Excel.CurrentWorkbook(){[Name="<table>"]}[Content]`. M tùy ý vẫn có thể đọc nguồn khác, nhưng Apply luôn nhắm descriptor nguồn mà UI đã preview, không suy luận lại từ code M. Nhánh ghi dùng bản export của **workbook đang mở**, không cần đường dẫn file local và không tạo file backup riêng. Sau khi thay values nguồn, add-in không gọi Save.

## Lỗi, bảo mật và nghiệm thu

| Mã/điều kiện | Hành vi |
|---|---|
| `PQ_RISK_ACK_REQUIRED` | Backend không chạy M khi request thiếu cờ xác nhận của hộp đầu tiên. |
| `PQ_SOURCE_MISSING` | Sheet/Table không còn hoặc không xác định; không chạy preview. |
| `PQ_REFRESH_FAILED`, `PQ_RESULT_NOT_TABLE` | Excel không refresh được hoặc M không trả table; không ghi workbook đang mở. |
| `PQ_RESULT_INVALID` | Workbook giá trị có formula/nguồn ngoài/query hoặc không khớp kích thước; không áp dụng. |
| Preview/workbook/code/source đổi | Invalidate preview, không ghi; yêu cầu chạy preview lại. |
| Mở rộng Table gặp value/formula ngoài Table | Chặn trước resize/write và giữ nguyên Table hiện tại. |
| ExcelApi 1.13 thiếu | Hiện lỗi hỗ trợ host; không ghi nguồn. |
| Lỗi sau khi write có thể đã bắt đầu | Báo `applyFailed` và khả năng partial write; không tuyên bố rollback, không tự retry. |
| `CALC_TIMEOUT` | Dừng riêng instance do helper tạo, không đụng Excel của người dùng. |

Unit/API/JS test phải phủ xác nhận chạy M lần đầu, tạo/reuse marked preview sheet, không đổi source trước Apply, xác nhận Apply riêng, fingerprint bỏ qua preview nhưng không bỏ qua source change, stale code/source, Table shrink/collision, usedRange clear-tail và package audit. Automated Advanced Apply smoke ngày 11/10/2026 đạt; full runtime cross-check cùng ngày còn `CALC_TIMEOUT` ở nhánh Typed merge/append khi Excel/Mashup bận. **Manual sideload trong Excel thật vẫn là gate riêng**, đặc biệt import/reuse `PQ_Result`, Table resize và usedRange clear-tail.

Rủi ro còn lại: M tùy ý có thể truyền dữ liệu ra ngoài hoặc gây side effect ngay trong preview, dù workbook tạm không phải nguồn gốc; Power Query nguồn ngoài có thể cần privacy/credential prompt mà instance ẩn không xử lý được. Apply trực tiếp vào nguồn không có backup, rollback giao dịch hoặc Ctrl+Z được bảo đảm; nên UAT lần đầu trên workbook không quan trọng và chỉ Save sau khi đã tự đối chiếu kết quả.

Raw workbook có ô lỗi Excel là ca riêng: `Excel.CurrentWorkbook()` có thể đưa giá trị lỗi sang M thành `null`, và `Table.Distinct` trực tiếp trên các dòng M còn lỗi có thể làm refresh thất bại. Mẫu `examples/pq_clean_orders_with_errors.m` giữ các dòng M có lỗi, chỉ khử trùng lặp dòng không lỗi; không hứa bảo toàn mã lỗi Excel hoặc xóa hết duplicate trong nhóm dòng lỗi.
