# W-21 — Excel task pane và connector spike

| Thuộc tính | Giá trị |
|---|---|
| Phiên bản | 0.1 |
| Ngày | 04/10/2026 |
| Trạng thái | Baseline triển khai W-21; chưa phải production |
| Tài liệu cha | `SPEC.md` v0.6, `EXCEL_MCP_SPEC.md` v0.1, `IMPLEMENTATION_PLAN.md` v0.4 |
| Phạm vi | Excel Desktop Windows, workbook `.xlsx` đã lưu, task pane Office.js, local coordinator, Excel COM helper |
| Gate đích | GX1 — connector khả thi |

## 1. Mục tiêu và kết quả phải chứng minh

W-21 phải tạo được một lát cắt chạy thật, có thể sideload vào Excel Desktop:

```text
Workbook đang mở
→ task pane đọc sheet/table/header/preview bằng Office.js
→ local coordinator tạo kế hoạch cố định cho fixture W-20
→ người dùng xem kế hoạch và mẫu dữ liệu nguồn (không hiển thị kết quả sau mô phỏng)
→ người dùng bấm duyệt
→ Office.js xuất snapshot nhị phân của workbook đang mở
→ coordinator tạo file copy không ghi đè
→ Excel COM helper mở riêng bản copy, ghi 4 cột công thức và calculate
→ coordinator trả formula/value đọc lại từ Excel
```

W-21 không tuyên bố đã có AI planner tổng quát hoặc MCP server. Hai phần đó lần lượt thuộc W-23 và W-22. Kế hoạch cố định trong W-21 chỉ nhận đúng schema fixture `SalesTable`/`CommissionTable` để kiểm chứng đường đi kỹ thuật.

## 2. Quyết định kiến trúc

### 2.1 Thành phần

| Thành phần | Trách nhiệm | Không được làm |
|---|---|---|
| Excel task pane | Đọc workbook đang mở qua Office.js; nhận prompt; hiển thị plan/preview; yêu cầu xác nhận; xuất workbook bytes khi apply | Không ghi ô/công thức vào workbook nguồn |
| Local coordinator Python | Serve HTTPS trên loopback; xác thực token/origin; kiểm schema; giữ plan revision; tạo đích copy an toàn; gọi helper | Không nhận arbitrary script; không gửi dữ liệu ra mạng |
| Excel COM helper PowerShell | Mở bản copy bằng Excel instance riêng; chỉ thực thi operation allowlist; calculate; đọc lại kết quả; save | Không attach hoặc ghi vào workbook nguồn; không tự chọn file nguồn/đích |
| Excel Desktop | Host task pane và tính công thức trên bản copy | Không được dùng preview mô phỏng làm bằng chứng runtime |

### 2.2 Lý do dùng workbook export thay vì attach active COM instance

Task pane lấy bản `.xlsx` của document hiện hành bằng Office document API. Coordinator ghi bytes đó vào một file đích mới, sau đó helper chỉ mở file đích. Cách này tránh rủi ro `GetActiveObject` trả nhầm một Excel instance khi người dùng đang mở nhiều tiến trình. Đường dẫn workbook nguồn chỉ được dùng để chọn thư mục đích và kiểm hash đĩa trước/sau; không được truyền cho helper như target ghi.

### 2.3 Ranh giới dữ liệu

- Chỉ bind `127.0.0.1` hoặc `::1`; manifest dùng `https://localhost:3000`.
- Office.js là script ngoài duy nhất được phép bởi CSP. Không có CDN UI, telemetry hoặc cloud AI.
- Prompt tối đa 4.000 ký tự; preview tối đa 20 dòng; workbook export W-21 tối đa 32 MiB.
- Request body, workbook bytes và raw cell values không được ghi log.
- Export tạm nằm trong temporary directory của process và bị xóa khi server dừng.

## 3. UI/task pane

Task pane có năm vùng:

1. **Kết nối workbook** — trạng thái Office host, workbook, sheet active, URL local/saved và capability `ExcelApi`.
2. **Yêu cầu** — textarea prompt và nút `Phân tích workbook`.
3. **Kế hoạch đề xuất** — danh sách 4 operation có target, công thức, lý do và cảnh báo giới hạn fixture.
4. **Mẫu dữ liệu nguồn** — chỉ hiển thị tối đa 20 dòng Excel đã đọc; không dựng bảng kết quả sau mô phỏng. Kết quả sau chỉ xuất hiện trong vùng runtime khi Excel thật đã tính và đọc lại.
5. **Duyệt và kết quả** — nút `Duyệt, tạo copy và chạy Excel`; đường dẫn copy; trạng thái calculate; bảng formula/value runtime.

Nút apply bị khóa khi chưa có plan `review_ready`, có hard blocker, workbook chưa lưu local, schema khác fixture hoặc plan/snapshot đã đổi.

## 4. Hợp đồng nội bộ W-21

### 4.1 `POST /api/excel/plan`

Input:

```json
{
  "prompt": "...",
  "workbook": {
    "name": "excel_mcp_sales_input.xlsx",
    "url": "file:///C:/.../excel_mcp_sales_input.xlsx",
    "activeSheet": "Sales",
    "tables": [{"sheet": "Sales", "name": "SalesTable", "headers": [], "rows": []}]
  }
}
```

Output tối thiểu: `snapshotId`, `planRevisionId`, `status`, `operations`, `preview`, `warnings`, `hardBlockers`. ID là hash canonical của metadata/prompt/operations, không chứa raw values.

### 4.2 `POST /api/excel/apply`

Input: metadata workbook lặp lại, `snapshotId`, `planRevisionId`, toàn bộ operation ID được chọn, `workbookBase64`. Việc gọi endpoint sau hộp thoại xác nhận là approval tường minh của W-21.

Coordinator phải:

1. Tái tạo và đối chiếu snapshot/plan ID.
2. Kiểm file là ZIP `.xlsx`, trong giới hạn và schema export khớp metadata đã duyệt.
3. Parse URL local; bảo đảm tên file và workbook name khớp; từ chối URL web/unsaved.
4. Hash file nguồn trên đĩa trước thao tác nếu tồn tại.
5. Chọn tên `<stem>_AI_copy_<UTC timestamp>_<suffix>.xlsx`; không overwrite.
6. Ghi export vào file đích bằng create-new semantics.
7. Gọi helper bằng typed JSON allowlist.
8. Hash file nguồn sau thao tác và hard-fail/audit nếu thay đổi.
9. Chỉ trả `excel_runtime_verified` khi helper đã calculate, save và đọc lại không có formula error.

### 4.3 Operation allowlist W-21

| ID | Target | Formula |
|---|---|---|
| `op-net-revenue` | `SalesTable[Net Revenue]` | `=[@[Gross Revenue]]-[@[Discount Value]]-[@[Return Value]]` |
| `op-return-rate` | `SalesTable[Return Rate]` | `=IFERROR([@[Total Return Qty]]/[@[Total Sold Qty]],0)` |
| `op-commission` | `SalesTable[Commission Value]` | `=[@[Net Revenue]]*XLOOKUP([@[Net Revenue]],CommissionTable[Min Net Revenue],CommissionTable[Commission Rate],0,-1)` |
| `op-sales-rank` | `SalesTable[Sales Rank]` | `=LET(p,PERCENTRANK.INC(SalesTable[Net Revenue],[@[Net Revenue]]),IFS(p>=0.9,"Top 10%",p>=0.8,"Top 20%",TRUE,"Bottom"))` |

Helper không thực thi formula do client gửi. Coordinator lấy công thức từ catalog nội bộ theo operation ID rồi tạo request cho helper.

## 5. Hard blockers và lỗi hành động được

| Code | Điều kiện | Hành động gợi ý |
|---|---|---|
| `OFFICE_NOT_READY` | Không chạy trong Excel/Office.js chưa sẵn sàng | Sideload manifest và mở lại task pane |
| `WORKBOOK_UNSAVED` | Không có URL local | Lưu workbook thành `.xlsx` rồi refresh |
| `REMOTE_WORKBOOK_UNSUPPORTED` | URL OneDrive/SharePoint/HTTP | Tải và mở bản local trong W-21 |
| `SCHEMA_MISMATCH` | Thiếu table/header fixture | Mở fixture W-20 hoặc sửa schema |
| `PLAN_STALE` | prompt/metadata/operation khác plan | Phân tích lại và duyệt revision mới |
| `WORKBOOK_LIMIT` | Export vượt 32 MiB | Dùng workbook nhỏ hơn cho spike |
| `COPY_EXISTS` | Đích đã tồn tại | Tạo tên copy mới; không overwrite |
| `EXCEL_UNAVAILABLE` | Không tạo được Excel COM instance | Kiểm Excel Desktop đã cài |
| `FORMULA_UNSUPPORTED` | Excel không hỗ trợ `XLOOKUP`, `LET` hoặc `Formula2` | Nâng Excel hoặc thay formula ở W-23 revision mới |
| `CALC_TIMEOUT` | Calculate không kết thúc trong timeout | Mở copy kiểm external links/formula |
| `SOURCE_CHANGED` | Hash nguồn trước/sau khác | Dừng và kiểm workbook nguồn; không gắn nhãn verified |

## 6. Acceptance criteria W-21

| ID | Điều kiện đạt | Bằng chứng |
|---|---|---|
| W21-AC-01 | Task pane load trong Excel và `Office.onReady` xác nhận host Excel | Manual sideload record + capability payload |
| W21-AC-02 | Đọc đúng 2 sheet, 2 table, headers và tối đa 20 dòng fixture mà không write | Unit/API test + task pane manual |
| W21-AC-03 | Schema sai/unsaved/remote URL tạo hard blocker và disable apply | Unit/API/JS state test |
| W21-AC-04 | UI không hiển thị giá trị sau mô phỏng; trước approval không tạo file copy | JS/API test + filesystem assertion |
| W21-AC-05 | Apply chỉ nhận revision hiện hành và đủ 4 operation allowlist | Negative unit/API tests |
| W21-AC-06 | File copy tạo bằng tên mới; nguồn byte-identical | Integration test + SHA-256 trước/sau |
| W21-AC-07 | Excel helper ghi 4 calculated columns vào copy, calculate và đọc lại 6 dòng | Real Excel isolated smoke test |
| W21-AC-08 | Runtime values khớp `manifest.json`; không có formula error | Reconciliation report |
| W21-AC-09 | Timeout/helper failure trả error; không tuyên bố verified | Negative test/fake runner |
| W21-AC-10 | Runbook setup HTTPS, sideload, test và cleanup đủ để người dùng tự chạy | `tools/excel_addin/README.md` |

GX1 chỉ đóng khi W21-AC-01, 02, 06, 07 và 08 có bằng chứng trên Excel Desktop. Nếu automation COM xanh nhưng task pane chưa được sideload thủ công, ghi `GX1 pending manual task-pane evidence`, không ghi hoàn thành.

## 7. Kế hoạch test theo lát cắt

| Lát cắt | Đầu ra | Test ngay | Điều kiện đạt |
|---|---|---|---|
| W21-A | Typed fixture planner + stale-plan validation | prompt/schema/headers/revision/preview | deterministic; 0 filesystem write |
| W21-B | Loopback task-pane server + Office.js UI + manifest | host/origin/token/assets/API, `node --check` | HTTPS-ready; mutation có token |
| W21-C | Safe copy coordinator + helper adapter | invalid path/base64/ZIP/copy collision/fake helper/source hash | không overwrite; không truyền source làm write target |
| W21-D | PowerShell Excel helper | isolated fixture apply/calculate/read-back + timeout contract | source hash bất biến; output khớp manifest |
| W21-E | Sideload runbook + manual UAT | người dùng mở fixture và chạy full task pane | UI/runtime evidence ghi rõ phiên bản |

## 8. Giới hạn sau W-21

- Planner chỉ hiểu đúng fixture; chưa hiểu prompt tự do ngoài bốn yêu cầu mẫu.
- Approval W-21 là request một lần gắn plan/snapshot; token ký/audit hoàn chỉnh thuộc W-24.
- Chưa công bố tool qua MCP Inspector; hợp đồng MCP/fake connector thuộc W-22.
- Chưa hỗ trợ `.csv` trong task pane vì Excel task pane host một workbook; `.csv` vẫn dùng raw-data UI hiện có.
- Chưa hỗ trợ OneDrive/SharePoint, `.xlsm`, workbook mã hóa/protected, nhiều Excel instance hoặc workbook lớn.

## 9. Bằng chứng triển khai ngày 04/10/2026

| Hạng mục | Trạng thái | Bằng chứng |
|---|---|---|
| W21-A planner/revision/preview | Đạt automated | 4 test `test_excel_plan.py`; preview 6 dòng khớp manifest; schema/URL/prompt/stale revision bị chặn |
| W21-B server/task pane/manifest | Đạt automated, chờ manual host | 5 test `test_excel_addin_server.py`; `node --check`; HTTPS health trả `w21_excel_taskpane`; certificate PEM xuất thành công nhưng chưa tự động trust |
| W21-C copy coordinator/safety | Đạt automated | 7 test `test_excel_connector.py`; source target/collision/base64/runtime mismatch/stale preview/trace; helper chỉ nhận catalog operation nội bộ |
| W21-D Excel helper runtime | Đạt isolated Excel | `py -m examples.w21_excel_smoke`: Excel `16.0`, 6 dòng, 0 formula error, manifest matched, source SHA-256 unchanged |
| Full regression | Đạt | `py -m unittest discover -s tests -v`: 118 pass, 1 skip symlink |
| W21-E sideload/UAT trong task pane | Chưa chạy | Môi trường automation không có browser session; cần người dùng trust certificate, sideload manifest và thực hiện runbook |

Kết luận hiện tại: connector/copy/calculate **khả thi và đã chạy thật trên fixture cô lập**. GX1 vẫn `pending manual task-pane evidence`; không suy diễn kết quả này thành MCP runtime, AI planner tổng quát hoặc production-ready.
