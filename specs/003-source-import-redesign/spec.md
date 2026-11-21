# Feature specification: một tab Nguồn — nhập file thành sheet đúng kiểu dữ liệu

**Feature**: `003-source-import-redesign`. **Created**: 2026-11-18 (Asia/Saigon).
**Status**: Draft — chờ người dùng duyệt trước khi giao agent code.
**Input**: 3 ảnh task pane (bước `1. Nguồn`, bước `2. Làm sạch`, thẻ câu hỏi định dạng) và trao đổi 2026-11-18.
**Git**: giữ `main`, không reset/stash công việc đang có. Không đổi baseline 001, không đổi release metadata.
**ID**: `SI*`, `S*`, `SC*` là alias feature-local, không cấp lại FR/DP/AC của docs/current hay feature 002.

## 1. Vấn đề hiện tại (bằng chứng trong code)

| # | Hiện trạng | Hệ quả với người dùng |
|---|---|---|
| P1 | `pbip_assistant/sources/preparation/packages.py` dựng frame CSV bằng `numberFormats: [["@"] * len(rows[0])]`, giá trị giữ nguyên chuỗi `csv.reader` | Mọi cột thành text; số/ngày không tính toán, không lọc, không sort được |
| P2 | `pbip_assistant/sources/preparation/cleaning.py:86-92` sinh câu hỏi `keep_text / decimal_dot / decimal_comma` và `DMY / MDY / YMD` cho từng cột | Người dùng phải trả lời từng cột như ảnh 3, dù dữ liệu đã rõ |
| P3 | `pbip_assistant/excel_addin/taskpane.html:60-66` journey 3 bước; `#preparation-wizard` chứa quét, chọn hệ ngày, câu hỏi, `Xem trước`, áp dụng | Hai tab chồng nhau cho cùng một việc "đưa dữ liệu vào workbook" |
| P4 | `pbip_assistant/excel_addin/assistant_entry.js:126` nhập xong gọi `scan()` rồi chuyển bước `Làm sạch` | Nhập xong vẫn chưa dùng được; phải đi qua màn hình thứ hai |
| P5 | `inventory._members()` chỉ lấy file trực tiếp trong thư mục đã chọn | Không duyệt được thư mục con; phải chọn lại từng thư mục bằng dialog Windows |

## 2. Quyết định người dùng đã duyệt (2026-11-18)

| # | Quyết định |
|---|---|
| D1 | Gộp hai bước `1. Nguồn` + `2. Làm sạch` thành một tab `Nguồn`. Journey còn `1. Nguồn → 2. Đề bài`. |
| D2 | Chọn nguồn = panel tự duyệt cây thư mục: mở dialog **một lần** để lấy thư mục gốc, sau đó đi vào/ra các thư mục con và tick file ngay trong panel. |
| D3 | Giữ nút `Dùng dữ liệu trong workbook`. |
| D4 | CSV chuyển hoá thành sheet với đúng kiểu ô: số → number + numberFormat `General`; ngày → date + numberFormat; mã/chữ → text `@`. |
| D5 | Định dạng (dấu thập phân, phân cách nghìn, thứ tự ngày, hệ ngày 1900/1904) do hệ thống tự quyết ở khâu nhập. Không hỏi từng cột, không hỏi hệ ngày. |
| D6 | Mọi quyết định tự động được liệt kê trong khối `Ngoại lệ đã tự xử lý` (option b): không chặn, không hỏi, nhưng phải xem lại được. |
| D7 | Bỏ hoàn toàn `Xem trước` (preview dữ liệu và preview làm sạch) và bỏ bước duyệt/áp dụng làm sạch khỏi hành trình. |
| D8 | Không còn câu hỏi `Giữ dạng chữ / Dấu chấm thập phân (1,234.56) / Dấu phẩy thập phân (1.234,56) / DMY / MDY / YMD`; không còn select `Hệ ngày của workbook`. |

## 3. Phạm vi

**Trong phạm vi**

- Tab `Nguồn` duy nhất: browser cây thư mục, tick file, nhập, báo cáo kết quả + ngoại lệ.
- Suy luận kiểu cho CSV (number/date/text/identifier) và ghi ô đúng kiểu, đúng numberFormat.
- Báo cáo ngoại lệ có thể xem lại; file lỗi bị bỏ qua có lý do, không chặn file khác.
- Nhánh `Dùng dữ liệu trong workbook` vẫn hoạt động, không sửa dữ liệu trong sheet.
- Cập nhật owner docs (`docs/current/*`) và acceptance matrix.

**Ngoài phạm vi**

- Đề bài, KPI, Codex, PBIP patch, Advanced M.
- Undo/Redo, backup/restore, sửa dữ liệu sheet có sẵn (giữ nguyên hành vi hiện tại).
- Import XLSX: giữ nguyên đường native group-insert đang có; chỉ đảm bảo UI/báo cáo mới không làm hỏng nó.
- CSV có dòng lệch số cột (ragged), file > 64 MiB, > 100.000 dòng, > 200 cột: vẫn chặn (xem SI10).
- `%`, tiền tệ có ký hiệu, datetime có giờ, năm 2 chữ số: giữ text, ghi ngoại lệ `DATE_UNSUPPORTED_TEXT` / `MIXED_TYPE_TEXT`.

## 4. User Scenarios & Testing

### US1 — Duyệt thư mục và chọn file trong panel (P1)

Mở dialog một lần để lấy thư mục gốc; sau đó panel hiển thị các thư mục con và file `.csv`/`.xlsx`; người dùng đi vào/ra, tick từng file hoặc chọn tất cả trong thư mục hiện tại.

**Independent test**: cây `root/{A/{x.csv,y.xlsx}, z.csv, note.txt}` — đi vào `A`, tick `x.csv`, quay lên, tick `z.csv`; `note.txt` và thư mục không lẫn vào danh sách chọn; selection giữ nguyên khi đi lại giữa các thư mục.

- **S01** Chỉ hiện thư mục và file `.csv`/`.xlsx`; sắp xếp thư mục trước, sau đó theo tên (casefold).
- **S02** Breadcrumb + `↑ Lên cấp trên` phản ánh đúng vị trí; không thoát khỏi thư mục gốc, không theo reparse point/symlink.
- **S03** Tick/bỏ tick giữ trạng thái theo `(thư mục tương đối, tên file)`; `Chọn tất cả` chỉ tác động thư mục hiện tại; footer đếm đúng `N file · M sheet dự kiến`.
- **S04** Hủy dialog, thư mục rỗng, thư mục chỉ có file không hỗ trợ: thông báo rõ, không lỗi, không mất selection cũ.

### US2 — CSV thành sheet đúng kiểu dữ liệu (P1)

Nhập file đã chọn; mỗi CSV tạo một sheet, mỗi XLSX nhập cả nhóm sheet như hiện tại. Cột số/ngày được ghi đúng kiểu để Excel tính toán được ngay.

**Independent test**: CSV `dim_products.csv` có `unit_price` (`1234.56`, `0.99`), `qty` (`1,234`, `12`), `code` (`00123`), `created` (`03/04/2026`), `note` (`" KH01 "`). Oracle độc lập khẳng định: `unit_price` là number `1234.56` + `General`; `qty` là number `1234` + `General`; `code` là text `00123` + `@`; `created` là serial ngày đúng hệ ngày + numberFormat `yyyy-mm-dd`; `note` = `KH01`.

- **S05** Số nguyên/thập phân thành number thật (`typeof === "number"`), numberFormat `General`; không giữ chuỗi "1234".
- **S06** Mã có số 0 đầu, số > 15 chữ số có nghĩa, text lẫn trong cột số: giữ text `@`, ghi ngoại lệ tương ứng.
- **S07** Ngày hợp lệ thành serial theo hệ ngày của workbook (probe 1900/1904, không hỏi), numberFormat `yyyy-mm-dd`; ngày không hợp lệ → cả cột text + ngoại lệ.
- **S08** Header luôn là text `@`; ô rỗng giữ rỗng; formula-like (`=1+1`, `+A1`, `@x`) luôn là text `@`, không bao giờ được Excel thực thi.

### US3 — Ngoại lệ tự xử lý và báo cáo sau nhập (P1)

Sau khi nhập, panel hiện số file/sheet đã tạo, danh sách mapping `file → sheet`, và khối `Ngoại lệ đã tự xử lý` liệt kê từng quyết định (cột nào, kết luận gì, vì sao, bao nhiêu ô).

**Independent test**: cùng fixture US2 — khối ngoại lệ có đúng 3 dòng: `code` (LEADING_ZERO_TEXT), `created` (DATE_DMY_DEFAULT), `qty` (GROUP_SEPARATOR); không có dòng nào cho `unit_price`; file lệch cột bị `Bỏ qua` kèm lý do và không có sheet nào được tạo từ nó.

- **S09** Report chỉ chứa metadata (tên cột, kind, reasonCode, số ô, tối đa 2 ví dụ ngắn ≤ 40 ký tự); không log, không gửi ra ngoài.
- **S10** File lỗi (lệch số cột, vượt hạn mức, encoding không đọc được, ZIP lỗi) bị bỏ qua riêng lẻ; các file còn lại vẫn nhập; không có partial write âm thầm.
- **S11** Nhập xong, `Tiếp tục: Đề bài` bật ngay khi có ≥ 1 sheet đã verify hoặc workbook có dữ liệu hợp lệ; không còn bước `Làm sạch`.

### US4 — Dùng dữ liệu trong workbook (P2)

Không chuyển hoá, không sửa sheet: chỉ kiểm tra sheet hiện tại có header + dòng dữ liệu, đọc lại nguồn như hiện tại, rồi cho đi tiếp.

**Independent test**: workbook có sheet `Data` hợp lệ và sheet `Empty` trống — chọn workbook thì `Empty` chỉ hiện cảnh báo, `Data` cho đi tiếp; nội dung sheet không đổi byte nào.

- **S12** Không ghi/sửa/xoá bất kỳ ô nào trên nhánh này; số sheet và giá trị không đổi sau thao tác.
- **S13** Workbook không có dữ liệu hợp lệ: thông báo rõ, `Đề bài` vẫn tắt, không tạo phiên rỗng.

### Edge Cases

Tên sheet trùng/Unicode/31 ký tự; CSV BOM; delimiter `, ; \t |`; encoding Windows-1252/UTF-16; cột toàn rỗng; file 0 byte; file chỉ có header; thư mục đổi trong lúc đang mở panel; file bị sửa giữa lúc tick và lúc nhập; hai tab task pane mở cùng lúc; panel hẹp 360px; mất kết nối coordinator giữa lúc nhập; workbook protected.

## 5. Yêu cầu chức năng

- **SI01** Tab `Nguồn` là nơi duy nhất để đưa dữ liệu vào; journey đúng hai bước `1. Nguồn` → `2. Đề bài`; không còn bước/tab `Làm sạch`.
- **SI02** Browser panel: chọn thư mục gốc bằng dialog native một lần, sau đó duyệt cây trong panel (breadcrumb, lên cấp trên, danh sách thư mục con + file `.csv`/`.xlsx`).
- **SI03** Selection theo `(relativePath, fileName)`, giữ khi điều hướng; `Chọn tất cả` theo thư mục hiện tại; giới hạn 200 file, 64 MiB/file và tổng phiên như hiện có.
- **SI04** Chỉ đọc nội dung file khi người dùng bấm nhập; duyệt thư mục chỉ `stat`, không đọc/hash nội dung, không ghi.
- **SI05** Nhập CSV → một sheet; XLSX → toàn bộ nhóm sheet như hiện tại; không đè sheet có sẵn; tên sheet qua `safe_sheet_name`.
- **SI06** Suy luận kiểu theo cột, tất định, theo đúng bảng luật ở §6; ghi giá trị đúng kiểu + numberFormat.
- **SI07** Không hỏi định dạng, không hỏi hệ ngày, không hiện preview dữ liệu; mọi quyết định nằm trong report.
- **SI08** Report ngoại lệ: theo file, theo cột, gồm `reasonCode`, mô tả tiếng Việt, số ô ảnh hưởng, tối đa 2 ví dụ ≤ 40 ký tự; tổng hợp `files/sheets/decisions/skipped`.
- **SI09** File lỗi bị bỏ qua độc lập, có lý do; không rollback ngầm, không nhập lại tự động; trạng thái partial/unknown phải nói rõ.
- **SI10** Giữ nguyên các cổng chặn: ragged rows, vượt byte/row/column, ZIP bomb, đường dẫn thoát root, source đổi giữa review và write, protected workbook.
- **SI11** Nhánh `Dùng dữ liệu trong workbook`: không chuyển hoá, không sửa dữ liệu; chỉ validate + đọc lại nguồn; cảnh báo sheet trống/không tabular.
- **SI12** `Đề bài` chỉ bật sau khi có nguồn verified; chuyển bước không tự ghi workbook, không tự Save.
- **SI13** Không gửi dữ liệu/đường dẫn sang AI; không log raw cell, binary hay private path; mọi text render bằng `textContent`.
- **SI14** Accessibility: keyboard đi hết browser/selection/report, `aria-live` cho tiến độ, không tràn ngang ở 360px, hit target ≥ 32px.
- **SI15** Mọi hành vi mới có test tự động (Python unittest + Node taskpane script) và không làm hỏng bất kỳ script taskpane nào đang có trong gate.

## 6. Bảng luật suy luận kiểu (bắt buộc, tất định)

Áp dụng cho từng cột CSV sau khi trim hai đầu; chỉ xét ô không rỗng.

1. **Formula-like**: `=`, `+`, `@`, hoặc `-` không phải số → text `@`, reason `FORMULA_LIKE_TEXT`.
2. **Identifier**: có giá trị khớp `^0\d+$` (khác `"0"`) → text `@`, reason `LEADING_ZERO_TEXT`. Luật này thắng luật số.
3. **Number** (chỉ khi 100% giá trị không rỗng parse được theo **một** cách hiểu):
   - `decimal_dot`: `^[+-]?(\d{1,3}(,\d{3})+|\d+)(\.\d+)?$`
   - `decimal_comma`: `^[+-]?(\d{1,3}(\.\d{3})+|\d+)(,\d+)?$`
   - Nếu cả hai cách đều parse hết: nếu **mọi** giá trị có đúng 3 chữ số sau dấu phân cách và có ít nhất một dấu nhóm → hiểu là phân cách nghìn (số nguyên), reason `GROUP_SEPARATOR`; ngược lại hiểu là dấu thập phân, reason `DECIMAL_DOT`/`DECIMAL_COMMA` (low-confidence).
   - > 15 chữ số có nghĩa, hoặc |x| < 2.2250738585072014e-308 → text `@`, reason `PRECISION_TEXT`.
4. **Date** (100% giá trị khớp `^(\d{1,4})[/.-](\d{1,2})[/.-](\d{1,4})$` và là ngày hợp lệ):
   - token đầu 4 chữ số → `YMD`, reason `DATE_ORDER_DETECTED`.
   - có token đầu > 12 (và token thứ hai ≤ 12 ở mọi dòng) → `DMY`, reason `DATE_ORDER_DETECTED`.
   - có token thứ hai > 12 (và token đầu ≤ 12 ở mọi dòng) → `MDY`, reason `DATE_ORDER_DETECTED`.
   - còn lại mơ hồ → `DMY` (locale vi-VN), reason `DATE_DMY_DEFAULT` (low-confidence).
   - Trộn cả hai (>12 ở cả hai vị trí) hoặc năm 2 chữ số → text, reason `INVALID_DATE_TEXT` / `DATE_UNSUPPORTED_TEXT`.
   - Xuất serial theo hệ ngày của workbook (probe hàm `DATE(1904,1,1)`: `0` → 1904, `1462` → 1900), numberFormat `yyyy-mm-dd`.
5. **Text**: mặc định; trim hai đầu; numberFormat `@`. Nếu cột trộn số/ngày/chữ → text + reason `MIXED_TYPE_TEXT`.
6. **Empty**: ô rỗng giữ `null`, numberFormat `General` (ô để trống, không ghi chữ); cột toàn rỗng → `null` + `General`, reason `EMPTY_COLUMN`.
7. Header: luôn text `@`, không suy luận kiểu.
8. Mỗi quyết định khác `TEXT`/`NUMBER` mặc định được ghi vào report; `DECIMAL_DOT`, `DECIMAL_COMMA` có low-confidence cũng ghi.
9. **Delimiter thắng dấu thập phân.** Tách ô xảy ra trước, suy luận kiểu sau. Ví dụ đã chốt 2026-11-19:

   | Header | Dòng | Kết quả |
   |---|---|---|
   | `Code;Price` | `A01;00123,2` | `Code` = text `A01`; `Price` = number `123.2` (một ô, dấu phẩy là thập phân) |
   | `Code,Qty` | `00123,2` | `,` là delimiter → hai ô: `Code` = text `00123` (giữ số 0 đầu), `Qty` = number `2` |

   Amendment 2026-11-20 (đã duyệt): ô CSV rỗng giữ `null` + `General`; physical verifier so `numberFormats` của package thay vì bắt mọi ô `@`.

## 7. Key entities

`BrowseEntry` (name, kind, size, modified), `SelectionItem` (relativePath, fileName), `ColumnDecision` (column, kind, numberFormat, reasonCode, affectedRows, samples[≤2]), `FileImportReport` (fileName, status, sheets, reading{encoding,delimiter,headerRow,columns}, decisions, issues), `ImportReport` (files, totals), `TypedSheetFrame` (values, numberFormats, formulaCells). Chi tiết: [data-model.md](data-model.md), chữ ký API: [contracts/source-import.md](contracts/source-import.md).

## 8. Success Criteria

- **SC01** Fixture US2 cho ra đúng oracle kiểu ô + numberFormat + serial ngày; chạy 2 lần cho kết quả byte-identical.
- **SC02** 0 cột số/ngày nào bị ghi thành text khi dữ liệu sạch 100%; 0 cột nhiễu nào bị ép số.
- **SC03** 100% quyết định tự động xuất hiện trong report với reasonCode đúng; không quyết định nào âm thầm.
- **SC04** Không còn DOM/nhánh code nào của preview, câu hỏi định dạng hay select hệ ngày trong tab Trợ lý; journey đúng `1. Nguồn → 2. Đề bài`.
- **SC05** Browser dùng được bằng keyboard ở 360px; điều hướng 3 cấp và giữ selection đúng.
- **SC06** Ragged/oversize/hỏng file không tạo sheet, không chặn file khác, không ghi một phần.
- **SC07** Nhánh workbook không đổi một byte dữ liệu nào (fingerprint trước/sau bằng nhau).
- **SC08** Gate: `py tools/run_checks.py fast`, `runtime`, `py -m unittest discover -s tests` xanh; toàn bộ script taskpane đang có trong gate + 2 script mới đều chạy.

## 9. Supersession (feature 002)

Được duyệt bỏ khỏi hành trình: S05–S11, DP05–DP09 (preview/answer/apply/undo của làm sạch), phần `scan/question/preview` trong UI của T008/T009/T010. Backend `cleaning.py`, `mutation.py`, `store.preview/answer/begin_mutation` **giữ nguyên như compatibility code đã test**, không bị xoá, nhưng không còn được mount trong tab Trợ lý và không còn là đường đi của người dùng. Import vẫn dùng cổng approval/permit/read-back hiện có; không nới lỏng cổng ghi.

## 10. Assumptions & open points

- Windows Excel Desktop, ExcelApi ≥ 1.9 như hiện tại; không nâng manifest floor.
- Số thực ghi bằng JS number là an toàn trong giới hạn 15 chữ số có nghĩa đã nêu; số chính xác hơn phải ở lại text.
- Report hiển thị tối đa 200 dòng ngoại lệ, phần còn lại chỉ hiện tổng số.
- Chưa có yêu cầu đổi màu/typography; dùng token CSS hiện có của task pane.
- Nếu người dùng muốn giữ khả năng sửa tay sau nhập (ví dụ đổi 1 cột về text), đó là feature sau, không thuộc 003.
