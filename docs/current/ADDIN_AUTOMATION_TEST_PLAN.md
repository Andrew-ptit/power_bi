# Kế hoạch kiểm thử tự động add-in

Ngày: 2026-11-01 (Asia/Saigon). Phạm vi: Assistant v2, Typed/PQ, Problem Chain/history, step diagnostics, cache, Custom XML, phiên và phục hồi; Advanced M được đưa lại vào phạm vi kiểm thử theo yêu cầu mới kiểm thử toàn hệ thống. Chỉ dùng M tổng hợp và dữ liệu cục bộ do test tạo.

## Mục tiêu và nguyên tắc đánh giá

Tìm lỗi sai dữ liệu, ghi sai workbook/nguồn, quyền duyệt cũ, ghi lặp, mất lịch sử và báo thành công sai. Mỗi case có tiền điều kiện, bước thử, oracle độc lập, actual, lớp bằng chứng, hash/state trước và sau, thời gian và cleanup. Không đổi expected để hợp thức hóa lỗi. Kỳ vọng phải viết tay hoặc tính bằng oracle độc lập, không dùng engine đang được kiểm tra làm oracle.

Phủ toàn bộ capability và chuyển trạng thái, biên bằng/ngoài giới hạn, ca âm, recovery và tổ hợp rủi ro cao. Số tổ hợp thao tác và lỗi bất kỳ không hữu hạn; báo công khai tổ hợp đã thử/chưa thử thay vì tuyên bố mọi khả năng đều được chứng minh.

P0: mất/ghi nhầm dữ liệu, vượt approval/CAS/privacy hoặc false success sau lỗi ghi. P1: sai kết quả, mất thông tin trọng yếu, luồng chính không dùng được. P2: recovery/khả năng rà soát/UX sai nhưng chưa thấy mất dữ liệu. Gặp P0/P1: giữ evidence, tạo regression tái hiện trước sửa, chạy lại cả success và recovery của affected journey sau sửa.

Workbook người dùng chỉ đọc. Không Save, refresh connection, chạy macro hay dùng workbook đang mở làm fixture. Mọi write/fault/save-reopen dùng fixture tổng hợp có marker trong workspace tạm. Không dump raw cells, công thức, workbook binary, credential hoặc đường dẫn riêng. Không tắt security/approval/TTL để chạy test. Các gate HTTP, fake Office.js, runtime COM, live Office.js và live Codex được báo riêng.

## Khảo sát đã thực hiện trước chạy testcase

Nguồn: `Addin_StressTest_Data_PC_Test.xlsx` do người dùng gửi. Trạng thái đang mở: một workbook, Excel 16.0, chưa lưu; read-only inspection giữ nguyên Saved=false. Bản đĩa hash không đổi trong khảo sát.

| Sheet | Nguồn | Dòng dữ liệu | Trường hợp cần thiết kế |
|---|---|---:|---|
| README | Vùng thường | 4 | Nội dung tài liệu không cấp quyền thực thi |
| Sales | tblSales, 13 cột | 423 | OrderDate: 416 date/7 text; Qty: 404 number/19 text; CustomerCode trống 13; OverridePrice trống 371; duplicate/key/join/filter/override |
| Products | tblProducts, 5 cột | 25 | Lookup và khóa không duy nhất/không khớp trên fixture |
| Employees | tblEmployees, 5 cột | 12 | EffectiveDate, lookup và khóa |
| Recon | tblRecon, 2 cột | 350 | Anti join/unmatched/đối soát |
| Branch_HN | tblBranchHN, 4 cột | 30 | Append schema chung |
| Branch_DN | tblBranchDN, 4 cột | 20 | Append schema chung |
| Branch_HCM | tblBranchHCM, 5 cột | 25 | Thêm Channel: schema drift/union |
| CustMaster | tblCustomerMaster, 2 cột | 5 | Exact key/normalization; không tự suy diễn fuzzy match |
| CustRaw | tblCustomerRaw, 2 cột | 7 | Dữ liệu text không đồng nhất; unsupported operation phải chặn |
| Employees_Legacy | tblEmployeesLegacy, 5 cột | 12 | Append/distinct và provenance |
| Plan_Wide | usedRange, 7 cột | 4 | Cấu trúc wide; không tự mở rộng catalog để unpivot |
| Region_FillDown | usedRange, 3 cột | 6 | Region trống 3; unsupported fill-down phải báo rõ |

Tổng: 13 sheet, 10 Table, 909 dòng trong Table. Bản đĩa không có formula/error cell, macro, external link, query table, web extension, merged/hidden row/column. Trạng thái COM không có query/connection/named item hoặc XML của sản phẩm. Do đó cần fixture bổ sung cho công thức lỗi, Total Row, bảo vệ, giới hạn lớn, lịch sử và dữ liệu ghi partial; workbook này một mình không phủ được các rủi ro đó.

Kênh tài liệu kết nối: chưa có session. Hai kênh Computer Use hiện đều trả `native pipe unavailable` sau retry/reset; COM đọc dữ liệu thành công. Live Office.js chỉ được ghi PASS khi thật sự chạy được UI/Office.js, không suy ra từ COM. Lỗi này là prerequisite môi trường, không phải defect add-in. Đã hỏi người dùng kết nối lại trong khi tiếp tục các lớp độc lập.

## Ma trận testcase và thứ tự thực hiện

L = Excel/Office.js thật; R = Excel COM/M thật; I = coordinator tích hợp; U = unit/contract; J = fake Office.js. Một PASS ở U/I/J không thay thế ô L/R.

| ID | Ưu tiên | Bài kiểm thử và oracle | Lớp |
|---|---|---|---|
| QA-01 | P0 | Hai workbook/trùng tên khác URL/chuyển workbook từng pha; không ghi workbook thứ hai | L,I,J |
| QA-02 | P0 | Read-only/protected/thiếu API; chặn trước consume và write | L,U,J |
| QA-03 | P1 | Table duy nhất/nhiều Table/chọn trong ngoài/usedRange ngoài A1; không tự đổi nguồn sau preview | L,J |
| QA-04 | P1 | Total Row/filter/hidden row; tổng mọi data row đúng, không lấy total làm dữ liệu | L,J |
| QA-05 | P1 | Blank/header-only/header lỗi/merged/error cell/vùng chỉ format; schema và missing data trung thực | L,U,I |
| QA-06 | P0 | Refresh/Understand đọc lỗi hay chuyển workbook; stale authority bị hủy, consumed warning giữ đúng workbook | L,I,J |
| QA-07 | P1 | Discover mẫu 20 dòng/ngoài mẫu/đầu giữa cuối; compute đọc đầy đủ; không giả full freshness | L,I,J |
| QA-08 | P1 | CSV BOM/quote/newline/delimiter/width; XLSX/folder schema drift/rename/delete; mapping block khi mơ hồ | I,U |
| QA-09 | P0 | Disclosure/prompt/source thiếu hoặc cancel; zero Codex call/export trước hành động hợp lệ | L,I,J |
| QA-10 | P0 | Sentinel riêng tư trong path/rows; kiểm payload Codex/log/XML/download, không có binary/raw ngoài bound | I,U,J |
| QA-11 | P1 | Sửa prompt/answer/source khi request chạy; CtrlEnter repeat/IME; stale response không cấp quyền | L,I,J |
| QA-12 | P1 | Codex unavailable/auth/rate/timeout/malformed; không fallback plan giả | L,I,U |
| QA-13 | P0 | Raw M/unknown op/expr/cycle/field/type/hash spoof; fail closed trước execute | I,U |
| QA-14 | P1 | 15 operation/10 expression, null/rỗng/trùng/mixed; expected viết tay và row IDs | U,R |
| QA-15 | P1 | 6 join, duplicate/unmatched/null, merge lồng rồi expand; đúng row/value/order | U,R |
| QA-16 | P0 | Fan-out từng join/chuỗi join/left rỗng/cap và cap+1; ack không override hard blocker | I,U |
| QA-17 | P1 | Decimal lớn/0.1+0.2/âm/zero/null/chia zero; native Excel serial/1904/ISO/locale/bad date; không nhóm mất ngày âm thầm | L,R,I,U,J |
| QA-18 | P0 | Control total đúng/sai/không có: sai block; thiếu phải ack và unverified | L,I,U |
| QA-19 | P1 | A/B cùng snapshot; khác ancestor measure thì delta unavailable, không so đơn vị giả | L,I,U |
| QA-20 | P0 | Freeze discover hoặc stale planning/preview/result/reconcile; không tự duyệt revision mới nhất | L,I,U |
| QA-21 | P0 | Sửa ô ngoài mẫu sau preview/sau approve/giữa ghi-readback; chặn hoặc partial đúng pha | L,I,J |
| QA-22 | P0 | Direct handler/checkbox chưa tick/restored approval/đổi branch; không ghi bằng approval cũ | L,J,I |
| QA-23 | P0 | Doubleclick/request đồng thời/replay consumed; tối đa một handoff và một sheet mới | L,I,U |
| QA-24 | P0 | Trùng result sheet/tên-marker giả/rename/delete; không overwrite sheet hiện có | L,I,J |
| QA-25 | P0 | Cell/header bắt đầu =,+,-,@, Unicode; Text trước values, zero formula, full readback | L,J,I |
| QA-26 | P1 | Decimal text/native bool/int/null/empty và >15 digits; giữ giá trị đúng, disclosure thật | L,J,U |
| QA-27 | P0 | Mất response trước/sau consume/write/receipt; pre-consume stale không giả partial; consumed unknown không retry/Record | L,I,J |
| QA-28 | P0 | Record applied-only; hash đầy đủ safe steps/parameters, node hash riêng, không raw/path | L,I,U |
| QA-29 | P0 | XML CAS hai pane/tamper/duplicate/malformed/32KiB exact+1; không lost update | L,J,U |
| QA-30 | P1 | Reopen pane offline, metadata freshness unknown; full reload mới đối chiếu; Record bất biến | L,J,I |
| QA-31 | P0 | Harness Save/reopen/Save As fixture; history/XML giữ, approval không hồi sinh; product không Save | L,R |
| QA-32 | P1 | Root/child/manual add/edit/remove/reorder/final; prior revision nguyên vẹn; downstream blocked không runner | L,I,J |
| QA-33 | P0 | View khác checkout/HEAD; checkout invalidate; non-leaf continuation chặn; explicit branch hợp lệ | L,I,J |
| QA-34 | P1 | Sibling/leaf/subtree delete; đúng HEAD/CAS, root và sibling bảo toàn | L,I,J |
| QA-35 | P0 | Preview staging Cancel/Confirm/error/readback mismatch; chỉ Confirm mới promote, giữ prior cache/result | L,I,J |
| QA-36 | P1 | Cache hit zero M call/miss/eviction/stale; full cache, FIFO5; display-only không cấp quyền ghi | L,I,U |
| QA-37 | P0 | Result rewrite không false-stale source; source value/style/identity đổi vẫn invalidate | L,I,U |
| QA-38 | P1 | Diagnostics dependency closure/prefix/merge/append/downstream lỗi; không đổi plan/history/cells | L,I,J |
| QA-39 | P0 | Diagnostic staging đổi HEAD/source/version rồi Confirm; stale block, Cancel giữ cache; không write payload | L,I,J |
| QA-40 | P1 | Step/final/staging cache độc lập và cap exact/+1; row/column/cell/byte limits; unavailable không zero | I,U |
| QA-41 | P0 | Idle/absolute TTL/reset/restart/token hết hạn; no replay; history hydrate không hồi authority | L,I,U,J |
| QA-42 | P1 | Codex/Excel slot độc lập, cùng loại fail-fast; close job/temp cleanup; user Excel còn nguyên | I,U,R |
| QA-43 | P0 | Assistant/Typed/PC/Record/tab-switch; namespace/fingerprint/cache/authority không lẫn | L,I,J |
| QA-44 | P1 | Advanced Cancel zero export/run; ack đúng session/policy/workbook; chỉ M local tổng hợp | L,I,J |
| QA-45 | P0 | Advanced marked result reuse/source unchanged/code/source/workbook stale; Apply chính xác preview | L,I,J |
| QA-46 | P0 | Advanced Table/usedRange shrink/expand/tail/occupied value hoặc formula collision; ngoài region nguyên | L,I,J,R |
| QA-47 | P0 | Advanced bad/non-table/timeout/package nguy hiểm; zero import; post-write failure partial, no retry | L,I,J,R |
| QA-48 | P2 | Pane hẹp/keyboard/progress/errors/Unicode; 8 cards/2 tabs/disabled state; xem đầy đủ thuật toán trước duyệt | L,J,I |

## Oracle và thứ tự gate

1. A/B tiền: `10,-3,5` → A=12, B=15, delta=-3, mỗi bảng 1×1. Khẳng định cả số dòng/khóa/kiểu, không chỉ tổng.
2. Join: left A10,A20,B30; right A/x,A/y,C/z → inner4, left5, right5, full6, leftAnti1, rightAnti1 sau expand. Null keys có suite riêng.
3. Ngày: native serial 45292/45293 trong hệ 1900 phải giữ hai ngày 2024-01-01/02; số tiền 10/20 không được gộp thành ngày null/tổng30 mà chỉ báo control-total đạt. Hệ1904 phải dùng epoch riêng; serial60 fictitious phải được xử lý rõ.
4. Chạy tuần tự: prerequisites và source baseline → targeted adversarial reproductions → regression sau fix → runtime COM safe case/parity → live Typed/Assistant/diagnostics nếu UI truy cập được → toàn bộ fast → live Codex riêng. Không chạy các test ghi trên workbook nguồn.
5. Plan được ghi trước execution campaign. Các phát hiện từ đọc code là hypothesis cho đến khi có regression tái hiện. Kết quả cập nhật vào `CURRENT_STATUS.md`; log chi tiết/metadata nằm dưới `.artifacts/addin-quality-20261101/` (ignored), không nhân bản lịch sử release trong docs.

## Tiêu chí kết thúc

Không còn P0/P1 đã xác nhận chưa được xử lý hoặc được nêu rõ là blocker. Mỗi fix có test đỏ-trước/xanh-sau và affected journey/recovery. Từng nhóm QA có lớp bằng chứng thực tế hoặc lý do Blocked/Not run. Thống kê case chỉ tính những case thực sự chạy; không lấy số test có trong registry làm số pass. Live UI bị chặn phải báo riêng, không nâng simulation thành pass và không tuyên bố release-qualified.
