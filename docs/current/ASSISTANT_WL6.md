# Assistant WL6 — Duyệt + Ghi

WL6 ghi vào bản sao xlsx bằng stdlib, không phải Office.js/Excel runtime verification.
Slice nhận bytes workbook cùng kết quả, Spec, Preview và approval trong bộ nhớ.
Apply trả bytes mới; caller quyết định lưu, engine không có đường dẫn ghi hoặc tự Save.
Không mở workbook người dùng thật, không Excel COM, PowerShell COM, AI hoặc network.

## Approval và cổng trước Apply

Caller phải chạy assert_approvable của WL5 trước issue/apply.
Approval API không nhận reconciliation nên không tự chứng minh đã qua cổng đó.
issue_approval cần approved_by=user và approved_at ISO datetime có timezone tường minh.
Không cấp actor hoặc thời điểm từ clock; metadata caller chưa phải chứng thực UI/human.
approvalId tất định từ specFingerprint và previewHash, boundTo giữ đúng hai hash.
Artifact là dict capability đã issue trong process, có sealed weakref registry trong bộ nhớ.
Copy, JSON reconstruction, reset consumed hoặc sửa field không cấp lại quyền.
consume_approval atomic, đổi token gốc consumed=true và trả consumed record riêng.
Record đã consumed chỉ là audit; không phải capability dùng lại.
Hai fresh approval từ hai hành động caller có thể có ID/shape bằng nhau.
Determinism dùng hai fresh token; không replay một approval đã dùng.

## Ghi sheet mới và bảo toàn nguồn

FIN ghi PnL_Result 23×9; SALES ghi Sales_Result 4×4 ở baseline.
Header ở hàng 1, cột số là numeric XML và đọc lại bằng Decimal.
Marker chứa spec=, preview=artifact previewHash và labels=.
WL5 preview marker dùng payload digest; marker kết quả WL6 dùng artifact previewHash.
Apply kiểm payload digest, kích thước, labels, Spec/Preview và recipe được hỗ trợ.
Context được capture trước consume; thay caller input trong writer không đổi bản đã duyệt.
Cần applied_at ISO timezone tường minh; thiếu metadata bị chặn trước package work.
Approval được consume trước khi đọc/dựng package; lỗi sau đó không cấp lại token.
Sheet trùng tên trả AF_WRITE_PARTIAL, không đổi tên hoặc ghi đè.

## Package và read-back

ZIP/XML được xử lý bằng stdlib, có giới hạn entry/part/byte và chặn XML DTD.
Chỉ thêm worksheet mới và append ba metadata: Content_Types, workbook và relationships.
Mọi part nguồn khác giữ byte-identical; sheet entries cũ và thứ tự vẫn giữ.
Toàn workbook.xml không thể byte-identical vì cần đăng ký sheet mới.
Formula sẵn có trên sheet nguồn được giữ nguyên theo luật nguồn bất biến.
Sheet kết quả có marker không có formula; package không query/connection/pivot/externalLinks.
Read-back kiểm header, tọa độ ô, từng giá trị numeric/text và marker đầy đủ.
Sai giá trị/marker/tọa độ hoặc fail_after_sheet trả AF_WRITE_PARTIAL, không retry.
Không trả bytes thành công khi chưa xác minh read-back.
ZIP timestamps cố định; cùng bytes/input/metadata và fresh token cho cùng output bytes/hash.
Hash artifact bind đủ approval/target/written/source/labels/timestamps và các ref.

## Giới hạn kiểm chứng

Source fingerprint lấy từ Preview đã bind; engine không tự kiểm freshness ngoài caller.
Approval chưa bind workbook bytes cụ thể hoặc chứng thực danh tính ngoài process.
Chỉ hỗ trợ recipe/full grain/policy A của Preview và XML metadata append an toàn.
Test dùng fixture synthetic, ghi/read-back file kết quả trong temp rồi dọn sạch.
Chưa có Office.js/Excel live, workbook người dùng, UI hoặc WL7 delta/Decision Record.

