# Assistant WL7 — Verify + Record

engine slice tất định; không phải Office.js/Excel runtime verification.
WL7 đo delta và ghép Decision Record từ artifact đã có; không mở hoặc ghi file nguồn.
Không gọi AI, Excel COM hoặc network; UI, AI narrative và live Codex chưa được làm.

## Delta và lineage

compute_delta nhận raw tables trong bộ nhớ, result và Spec đã bind/hash hợp lệ.
rowsIn/rowsOut và duplicates được tính từ input hiện tại, không chép số golden.
FIN baseline: GL 31→23 hàng, PartnerEntity 29→0 ô rỗng, duplicates 1→0.
SALES baseline: OrderItems 24→4 hàng; null trước lấy CustomerID/TerritoryID trên Orders.
SALES có CustomerID 0→0, TerritoryID 3→0 và duplicates 0→0.
Null là None, chuỗi rỗng hoặc whitespace; số 0 vẫn là giá trị có mặt.
Cột nguồn đã map không còn ở output, nên nullsAfter là coverage projection có khai báo.
FIN PartnerEntity dùng pnlLine; SALES TerritoryID dùng region, CustomerID dùng customerCount.
Đây không phải lời khẳng định các cột raw vẫn còn trong bảng kết quả.
duplicatesAfter đếm khóa grain trùng, không chỉ so toàn hàng đã group.
changedColumns sinh từ catalog lineage của params.operation trong Spec.
Bỏ operation làm lineage tương ứng mất; không chọn lineage theo tên scenario/file.
changed_columns có thể đọc draft để chẩn đoán; helper không cấp quyền freeze.

## Decision Record

Record có snapshot/source fingerprint, brief hash/prompt, decisions, assumptions, steps,
reconciliation projection, delta, labels và hash; không chứa raw rows/cells/binary.
Chỉ giữ metadata dẫn xuất và tham chiếu cần thiết, không dùng workbook bytes hoặc file texts.
Privacy guard từ chối filesystem path tuyệt đối cả khi nằm giữa prose, giữ ratio/math thông thường.
decisions đúng mảng quyết định WL4, không gộp acknowledgements.
steps đúng Spec; reconciliation bỏ hashBasis/variantOf/variantReason theo projection contract.
Hash reconciliation gốc vẫn được kiểm bằng cách khôi phục basis/schema đã biết.
Assumptions lấy nguyên từ Brief runtime và các ID phải thuộc ledger đó.
Người dùng đã chốt riêng FIN có 5 assumptions theo runtime, không pad lên 8 như golden cũ.
FIN lengths là 8/5/14/1; SALES là 4/3/10/1 cho decisions/assumptions/steps/reconciliations.
Golden và WL1–WL6 được giữ nguyên; các anchor delta/refs khác vẫn so tuyệt đối.

created_at cần ISO datetime có timezone do caller cấp; không có clock ẩn.
ID rec_<24 hex> dẫn xuất từ snapshotHash, briefHash, decisionsHash; hash bind đầy đủ metadata.
JSON UTF-8, ensure_ascii=False, indent=2, sort_keys=True và newline tái mở giữ hash.
Optional source_evidence tái dùng kiểm chứng WL5 cho original CSV text trong bộ nhớ.
SALES cần evidence để tái tạo source fingerprint full-text; FIN dùng source hash-list.
Evidence có coverage/hash/cap trước khi dùng, không được lưu trong Record.

## Stale và nhãn

Chỉ cho phép unverified, assumed, out_of_scope, stale; không có nhãn verified.
Ledger chưa được xác minh giữ unverified; chốt policy không biến suy luận thành bằng chứng.
detect_stale so snapshot/source reference hoặc decisions hiện tại, không tự mở nguồn live.
Decision binding được kiểm qua ID 96-bit đã dẫn xuất; đây không phải authentication.
Record đã stale vẫn stale; mark_stale trả copy, thêm stale/reason và tính lại hash.
Nguồn đổi trả AF_SPEC_STALE/sourceChanged; quyết định đổi trả decisionChanged.

## Bốn hành trình engine và giới hạn

FIN/SALES đi WL1→WL7 với Apply bytes và read-back trong temp trước khi ghép Record.
UNKNOWN giữ ba lựa chọn chưa chốt, có A/B và delta nhưng bị chặn freeze.
Người dùng chốt NOPACK trên FIN là negative fail-closed, AF_BRIEF_INVALID trước phép đo.
Fallback generic trên FIN chưa được hỗ trợ; không dựng genericMode/notice giả để test xanh.
Record API không nhận Apply proof nên không xác thực việc ghi ngoài hành trình caller kiểm thử.
Chưa có UI, Office.js/Excel/Power BI live, AI narrative hoặc live Codex E2E.
