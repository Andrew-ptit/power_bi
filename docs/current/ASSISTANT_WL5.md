# Assistant WL5 — Preview + Reconcile

WL5 dựng workbook tạm bằng stdlib, không phải Excel/Power BI runtime verification.
Slice nhận bảng đã ingest trong bộ nhớ cùng Spec và quyết định WL4.
Không gọi AI, network hoặc Excel COM; không mở lại file nguồn trong engine.

## Kết quả và workbook tạm

FIN nhóm bản GL đã dedupe theo line/account/cost center/entity, giữ bucket nội bộ.
Budget được nhóm trước theo cùng grain rồi union khóa với actual, tránh nhân dòng.
Kết quả FIN baseline có 23 hàng × 9 cột, gồm actual/budget/variance bằng Decimal.
SALES loại Cancelled, giữ quantity âm, dùng territory trên đơn rồi fallback Customer.
Kết quả SALES baseline có 4 hàng × 4 cột, sắp theo region, có nhóm UNKNOWN.
Slice chỉ thực thi tập policy A và recipe/full grain đóng đang hỗ trợ.
Policy khác hoặc plan/grain chưa có cách thực thi bị chặn, không tự thay bằng A.

`build_workbook` dựng XLSX zip/XML values-only; header ở hàng 1, marker ở ô riêng.
ZIP entries có thứ tự cố định và timestamp 2026-01-01 00:00:00.
Workbook không có formula, queryTables, connections hoặc externalLinks.
Giới hạn row/column/byte và numeric bounds được kiểm trước khi dựng XML lớn.
`temp_workspace` tạo workspace ngoài repo và dọn cả khi caller gặp lỗi.
Số rowsOut/colsOut là kích thước dữ liệu, không gồm header và marker.

## Hash, marker và evidence nguồn

Marker chứa spec=, preview= và labels=; preview= là digest payload columns+rows có kiểu.
Digest payload khác previewHash của artifact, nên không có vòng hash tự tham chiếu.
previewHash vẫn tính theo hashBasis golden, bind payload qua marker trong target.
Thay nội dung kết quả làm payload digest và previewHash thay đổi, dù kích thước giữ nguyên.
`source.before/after` mặc định lấy hash-list nguồn trong snapshot được truyền.
Optional `source_evidence` nhận map relative filename → original UTF-8 text đã nạp.
Engine kiểm coverage, tên an toàn, byte cap và hash CSV/folder với snapshot trước khi dùng.
Hỗ trợ đúng recipe nguồn runtime WL1 và legacy fixture; không nhận fingerprint unbound.
SALES golden băm toàn tập original CSV text, cần verified evidence để tái tạo literal đó.
Evidence được caller nạp ở ingest stage, không mở lại nguồn hoặc lưu raw text vào artifact.

## Ba check và cổng duyệt

row_count kiểm kích thước, khóa nhóm và digest payload với Preview.
control_total kiểm raw − droppedByDedupe = source và source = result trong tolerance.
Tolerance mặc định 0.01, không được nới vượt 0.01; số nhỏ hơn được giữ chính xác.
FIN baseline: 16906900000 − 2700000000 = 14206900000 = tổng actualVnd kết quả.
SALES baseline: source = result = 133942500 sau khi loại Cancelled.
bridge_identity dùng công thức assistant_findings, kiểm Op + FX = Total = variance.
Bridge còn bind variance NetRevenue kết quả và actual − budget của từng hàng FIN.
SALES có applicable=false và các field bridge còn lại null.
Thiếu average rate được dùng tạo blocker, kể cả hai dòng ngoại tệ bù trừ net=0.
Thiếu closing hoặc rate không dùng chỉ tạo warning nếu các check khác đạt.
Số nguồn/bridge chưa tính được trong blocked artifact để null, không thay bằng số 0.
Fail tạo AF_RECONCILE_FAILED; assert_approvable kiểm lại hash/checks/identity và raise.
Cổng này chưa tạo approval hoặc quyền Apply; metadata/hash không thay kiểm freshness ngoài API.

## Giới hạn kiểm chứng

Contract kiểm golden chọn lọc, mutation, SHA-256/mtime, temp cleanup và XML readback.
Đọc lại cell XML và control total của workbook tạm là bằng chứng package, chưa phải Excel runtime.
API không nhận đủ raw snapshot binding; không khẳng định dữ liệu in-memory đã được xác thực ngoài caller.
Chưa làm WL6 ghi workbook người dùng, approval/Apply UI, WL7 Decision Record hoặc E2E live.
