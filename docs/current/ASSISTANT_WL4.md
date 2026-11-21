# Assistant WL4 — Chốt + Compile

WL4 là compile tất định, không ghi workbook, không phải runtime verification.
Slice nhận Brief, DomainPack và lựa chọn tường minh để tạo ExecutionSpec.
Không gọi AI, LLM, network hoặc Excel; không sinh provenance `llm`.
Nguồn, golden và output WL1–WL3 được giữ nguyên.

## Quyết định và metadata

`build_decisions` nhận map `choices`, `acknowledgements`, `decision_metadata` tùy chọn.
Mỗi SP phải có đúng một choice hoặc acknowledgement khi validate bản hoàn chỉnh.
Metadata gồm `decidedAt`, `decidedBy`, `rationale`, `acknowledgementNotes`.
Chỉ choices có `decidedBy="user"` và ISO datetime có timezone mới đủ điều kiện freeze.
Thiếu metadata vẫn tạo được draft với giá trị null, nhưng `freezeBlocked=true`.
Không lấy đề xuất trong Brief để chọn hộ, không bịa thời điểm, lý do hoặc consent.
SP thiếu nguồn chỉ được đưa ngoài phạm vi bằng acknowledgement `out_of_scope`.
Acknowledgement `risk` không thay lựa chọn của policy ảnh hưởng dữ liệu.
Hash mới dùng sáu business field của contract; bộ đọc cũng nhận legacy basis tám field.
`validate_decisions` kiểm coverage/hash; consumer còn phải kiểm `freeze_blocked`.

## Quyết định ánh xạ tới step

FIN có 14 step; SALES có 10 step, theo catalog operation đóng.
FIN: SP-4 → dedupe/normalize sign; SP-5 → map account; SP-6 → join cost center.
SP-2/SP-8 → lookup FX; SP-9 → key collision; SP-3 → intercompany; SP-1 → variance bridge.
SALES: SP-3 → customer join; SP-4 → territory; SP-1 → cancelled; SP-2 → net returns.
`params.chosenOptions` giữ map riêng theo SP; `policyModes` mô tả hướng xử lý tương ứng.
`chosenOptionId` là scalar nếu chỉ một lựa chọn hoặc mọi lựa chọn giống nhau; mixed là null.
Các mode là chỉ dẫn compile, chưa thực thi phép biến đổi trên dữ liệu.

## Graph, fingerprint và assumption

Mỗi step sau step đầu đọc ít nhất một output đã có và khai báo dependency tương ứng.
Budget join phải đọc trực tiếp group đã gộp về grain; grain hai phía phải khớp.
Đảo group/budget trả `AF_FANOUT_RISK`; verifier không tự sắp xếp lại hoặc sửa graph.
`order_steps` là API sắp dependency riêng, trả bản sao và kiểm lại graph.
Brief chưa mang physical table IDs: compiler dùng semantic `sourceAlias`, `tableId=null`.
Alias cần binding sang nguồn thật trước thực thi ở WL5, không phải bằng chứng binding hiện có.
`build_spec(..., created_at="2026-10-28T10:00:00+07:00")` đòi thời điểm caller tường minh.
Bỏ `created_at` hoặc thiếu timezone trả `AF_SPEC_INVALID`; không có clock ẩn.
Spec bind snapshotHash, briefHash, decisionsHash; id được dẫn xuất từ nội dung.
Fingerprint gồm đúng `hashBasis` công bố, kể cả createdAt; cùng input/metadata cho cùng hash.
`spec_fingerprint` chỉ tính hash, không cấp quyền freeze hoặc xác nhận freshness.
Mọi assumption trong ledger vẫn được liệt kê và giữ nhãn `unverified`.
Chốt policy không tự biến nội dung authored hoặc assumption thành `verified`.

## Invalidate và giới hạn kiểm chứng

Đổi decisionsHash làm Spec cũ mất hiệu lực qua diagnostic `AF_SPEC_STALE`, `stale=true`.
`invalidate_message` không sửa bản Spec cũ; caller phải chặn dùng lại và dựng Spec mới.
Spec final từ chối draft, binding sai revision, graph pending/blocked hoặc thiếu choice mapping.
Contract so cấu trúc/refs/status/hash binding; không so prose hay hash literal với golden.
Chưa làm WL5 preview/reconcile, UI, physical source binding hoặc runtime Excel/Power BI.
Chưa có workflow thực thi Spec, ghi sheet, approval Apply hoặc đối soát sau ghi.
