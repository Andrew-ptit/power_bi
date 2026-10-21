# Trợ lý Excel + PBIP — khung triển khai từng lát cắt

Dự án đang xây theo [`SPEC.md`](./SPEC.md) v0.6, [`BPMN_MODEL.md`](./BPMN_MODEL.md) v0.5, [đặc tả Excel MCP](./EXCEL_MCP_SPEC.md) v0.1 và [kế hoạch triển khai chi tiết](./IMPLEMENTATION_PLAN.md) v0.4. CLI đã nhận `.xlsx` và `.csv` theo chế độ chỉ đọc. Phần nhập `N-002 → N-003` kiểm kê PBIP, profile dữ liệu và lưu fingerprint SHA-256 để phát hiện nguồn thay đổi. Insight của người dùng được ghi là **giả thuyết**, không phải kết luận. Phần kế hoạch `N-006/N-007` mới có hợp đồng thuần và unit test cho KPI, biểu đồ, dependency; chưa nối với bộ trích xuất ý định từ ngôn ngữ tự nhiên hay model parser thật. Quy tắc về xác nhận rủi ro khi AI khuyên không nên và lỗi chặn đã được mô hình hóa trong Figma/BPMN nhưng **chưa code**.

Chưa có UI hoàn chỉnh cho toàn bộ R1, local AI, đề xuất KPI/chart tự động từ lời nói, sinh M/DAX/TMDL/PBIR, diff, backup/apply/restore hay kiểm tra runtime trong Power BI Desktop. Các trạng thái chưa chạy được ghi `not_run`. Không mở hay ghi vào PBIP gốc.

Đã có functional prototype cho riêng giai đoạn dữ liệu thô: local web side-panel hỗ trợ kéo/thả `.xlsx`/`.csv`, cấu hình cách đọc CSV, preview giới hạn, profile cột, lỗi dòng và so schema. Đây là **W-17A source-only**, không phải UI hoàn chỉnh của toàn bộ R1 và không bật AI/PBIP/apply. Wireframe/hợp đồng kiểm thử nằm tại [`UI_RAW_DATA.md`](./UI_RAW_DATA.md).

## Chạy thử

Yêu cầu: Python 3.13. Luồng CSV/XLSX/PBIR chỉ dùng thư viện chuẩn; catalog TMDL cần .NET 8+ và bridge cục bộ đã pin `Microsoft.AnalysisServices` 19.117.0. Restore NuGet chỉ diễn ra ở bước setup, không ở runtime.

```powershell
py -m pbip_assistant --pbip .\demo_inputs\Retail --excel .\demo_inputs\Sales.xlsx --insight "Doanh thu miền Nam giảm?"
py -m pbip_assistant --pbip .\tests\fixtures_pbip\Retail --excel .\tests\fixtures_source\orders_synthetic.xlsx --csv .\tests\fixtures_source\orders_synthetic.csv
py -m unittest discover -s tests -v
```

### Chạy UI dữ liệu thô — không cần Power BI

```powershell
py -m pbip_assistant.webapp --port 8765 --open
```

Sau đó dùng side-panel tại `http://127.0.0.1:8765/` để kéo/thả nhiều file. Server chỉ bind loopback, tạo bản sao tạm và xóa khi dừng. Preview tối đa 20 dòng trên UI; không gọi dịch vụ cloud.

Để bật catalog TMDL chính thức lần đầu:

```powershell
dotnet restore .\tools\tmdl_bridge\TmdlBridge.csproj --locked-mode
dotnet build .\tools\tmdl_bridge\TmdlBridge.csproj -c Release --no-restore
```

`demo_inputs` đã được tạo tại workspace khi smoke test; `Orders_synthetic.xlsx` trong đó mô phỏng schema CSV 17 cột. Muốn tạo thêm bộ mới, chạy `py -m examples.make_sample --out .\ten_thu_muc_moi`. Bộ này chỉ là fixture tổng hợp để xem luồng nhập, không phải PBIP thật đã được Power BI Desktop xác nhận. Có thể lặp `--excel` để nhập nhiều workbook. Không cần mở Power BI Desktop cho bước này.

Bộ fixture W-02 mới nằm trong [`tests/fixtures_source`](./tests/fixtures_source) và tái tạo bằng `py -m examples.source_fixtures .\thu_muc_fixture_moi`. PBIP giả W-03 nằm trong [`tests/fixtures_pbip/Retail`](./tests/fixtures_pbip/Retail), kèm manifest và generator [`examples/pbip_fixtures.py`](./examples/pbip_fixtures.py). Hai bộ này chỉ dùng dữ liệu giả; manifest ghi hash và kết quả kỳ vọng. Không chạy generator lên thư mục nguồn người dùng.

### Fixture cho spike Excel MCP

Workbook tổng hợp [`excel_mcp_sales_input.xlsx`](./tests/fixtures_excel_mcp/excel_mcp_sales_input.xlsx) có `SalesTable` và `CommissionTable`; [`manifest.json`](./tests/fixtures_excel_mcp/manifest.json) chứa prompt chuẩn, bốn operation/công thức và kết quả kiểm soát. Tạo lại vào một thư mục test riêng bằng:

```powershell
py -m examples.excel_mcp_fixtures .\excel_mcp_fixture_moi
py -m unittest tests.test_excel_mcp_fixtures -v
```

Parser hiện tại đã đọc được fixture và xác nhận workbook nguồn không có formula. W-21 đã dùng chính fixture này trong isolated Excel 16.0 smoke để tạo copy, ghi/calculate bốn công thức và đọc lại kết quả khớp manifest. Đây là bằng chứng connector runtime trên copy, chưa phải bằng chứng task pane đã sideload trên máy người dùng hoặc MCP server W-22 đã chạy.

### Chạy thử Excel task pane W-21

Chi tiết setup/UAT/cleanup nằm tại [`tools/excel_addin/README.md`](./tools/excel_addin/README.md). Luồng ngắn:

```powershell
.\tools\excel_addin\setup-dev.ps1 -Trust
py -m pbip_assistant.excel_addin_server
```

Sau đó sideload [`manifest.xml`](./tools/excel_addin/manifest.xml) trong Excel và mở một fixture copy. Task pane đọc workbook trực tiếp bằng Office.js; chỉ sau xác nhận mới xuất workbook, tạo file `*_AI_copy_*.xlsx`, rồi helper mở riêng copy để ghi và calculate. Không dùng workbook thật ở lần UAT đầu.

Máy này liên kết add-in qua `C:\AddinManifests\manifest.xml`. Lệnh `py -m pbip_assistant.excel_addin_server` chọn cổng trống đầu tiên từ `3079` xuống `3072`, sinh channel ngẫu nhiên để phá cache, cập nhật cả manifest repository/catalog và chỉ chạy khi hai SHA-256 khớp. Sau mỗi lần khởi động coordinator phải đóng/mở lại task pane để Excel đọc URL runtime mới; không ghi đè `.certs` hoặc file catalog khác.

Máy người dùng dùng dấu `;` giữa các đối số công thức Excel. Panel mặc định chọn `;` và cho đổi sang `,` trước khi phân tích; lựa chọn này được gửi cho Codex để hiển thị công thức đề xuất đúng locale. Đây mới là đề xuất đọc-chỉ, chưa phải công thức đã được Excel kiểm chứng hay payload apply. Connector fixture hiện dùng COM `Formula2` cho công thức API, không thay dấu phân tách hàng loạt trong chuỗi công thức.

**Codex analysis slice (04/10/2026):** ô Yêu cầu hiện gọi Codex CLI đã đăng nhập khi bấm `Phân tích workbook`. Panel đọc tối đa 20 dòng và 200 cột trên mỗi sheet/table, gồm cả sheet không có Excel Table, rồi gửi prompt và mẫu này tới OpenAI; không gửi file workbook hoặc đường dẫn local. Kết quả là đề xuất đọc-chỉ, không phải preview sau đã được Excel tính. Nút duyệt/ghi vẫn bị khóa cho đề xuất Codex. Endpoint W-21 fixture `/api/excel/plan` và copy/apply bốn công thức mẫu còn dành riêng cho smoke kỹ thuật, không xử lý prompt tùy ý. Workbook OneDrive có thể được phân tích, nhưng chưa thể xuất/apply bản copy từ nhánh Codex. Cần Codex CLI có trong `PATH` và đã đăng nhập (`codex login status`).

Tab `Trợ lý` chỉ hiển thị mẫu dữ liệu nguồn đã đọc, công thức và nhận xét đề xuất. Với `PQ_Code-M`, Excel thật refresh M trên bản tạm rồi add-in tạo/reuse sheet `PQ_Result` values-only và mở sheet này để review; source chưa bị thay. Sau Apply, panel đọc lại tối đa 20 dòng đầu từ chính Table/usedRange nguồn. Nếu refresh hoặc ghi lỗi, không hiển thị kết quả cũ như kết quả của lần chạy mới.

Phần trả lời Codex trong tab `Trợ lý` nay tách **nhận xét/giả định/cảnh báo** khỏi **công thức Excel, M, DAX và code khác**. Mỗi khối code có nút `Sao chép` riêng; copy không kèm lời giải thích. Khối code ở tab này vẫn chỉ là đề xuất, không tự ghi vào workbook. Tab `PQ_Code-M` có editor M riêng: xác nhận rủi ro lần đầu mới chạy preview, còn ghi nguồn luôn cần nút và xác nhận Apply riêng.

Nút `Phân tích workbook` và phím tắt `Ctrl+Enter` trong ô yêu cầu đều đọc lại workbook trực tiếp qua Office.js trước mỗi lần phân tích; nếu đọc lỗi, không gửi snapshot cũ cho Codex. Nút `Đọc lại` vẫn dùng để cập nhật riêng phần thông tin kết nối.

Đây là prototype: Codex chạy trong thư mục tạm và sandbox read-only, nhưng chưa có bằng chứng cô lập quyền đọc file ở mức hệ điều hành. Không dùng với workbook bí mật/được quản lý chặt cho tới khi kiểm tra bảo mật hoàn tất. Mở add-in chỉ kiểm tra Codex; dữ liệu chỉ được gửi khi người dùng bấm `Phân tích workbook`.

Nếu panel báo không tìm thấy Codex dù lệnh `codex` chạy trong terminal, hãy dừng coordinator, mở terminal mới trong thư mục dự án và chạy `codex login status`, `py -c "from pbip_assistant.codex_excel import codex_available; print(codex_available())"`, rồi chạy lại `py -m pbip_assistant.excel_addin_server` và mở lại panel. Coordinator nay tìm thêm Codex trong extension VS Code và `%APPDATA%\npm\codex.cmd` khi `PATH` của Excel khác terminal. Không cần cài lại nếu kiểm tra trả `True`.

Nếu panel báo **“Coordinator đang chạy bản cũ”**, dừng terminal coordinator bằng `Ctrl+C`, chạy lại `py -m pbip_assistant.excel_addin_server`, rồi đóng/mở panel. Launcher sẽ chọn lại cổng trong pool và đồng bộ manifest tự động.

Nếu coordinator được khởi động lại khi task pane vẫn đang mở, request đầu tiên có thể nhận `TOKEN_REQUIRED` hoặc `TOKEN_EXPIRED`. Task pane sẽ bootstrap một phiên mới, xóa trạng thái runtime gắn với phiên cũ và yêu cầu người dùng bấm lại; POST cũ không được tự replay.

### Tab PQ_Code-M (Typed Steps v2 và Advanced Apply, cập nhật 12/10/2026)

Problem Chain của Typed Steps dùng lịch sử revision bất biến lưu trong Custom XML của workbook. Wave 0 đã xác minh add/get/set/delete, payload gần 2 MiB, Save/reopen và Save As trong Excel thật. Phase 1 đã có luồng tạo vấn đề đầu, nối tiếp, sửa step thủ công, xem và quay lại revision, cùng kiểm tra `head` trước preview/approval. Kiểm tra chéo tự động và live Codex continuation đã đạt; full regression sạch và manual sideload của UI tích hợp vẫn là gate mở. Xem [`PROBLEM_CHAIN_SPEC.md`](./PROBLEM_CHAIN_SPEC.md) và [`PHASE1_CROSSCHECK.md`](./PHASE1_CROSSCHECK.md). Tính năng yêu cầu ExcelApi 1.5 khi chạy, không tự Save và không áp dụng cho Advanced M.

Phase 1.1 giữ tối đa 5 bản xem kết quả **đã xác nhận** trong panel và tối đa 5 kết quả values-only đầy đủ (tổng dữ liệu mã hóa không quá 64 MiB) trong coordinator theo FIFO; không nhúng kết quả vào workbook history. Preview mới chỉ là staging: Xác nhận ghi sheet và read-back thành công mới thay cache, Hủy giữ cache cũ. `Xem` chỉ mở step cards/mẫu. `Quay lại bản này` chuyển HEAD rồi chỉ ghi cache cùng `dataVersion` vào sheet `PQ_Typed_Result` có marker sau khi kiểm HEAD/history/review hash/workbook identity và fingerprint nguồn hiện tại; không chạy lại M nếu hợp lệ. Ô `Dữ liệu nguồn đã thay đổi` ở đầu chuỗi tăng `dataVersion` một lần, giữ cache cũ để so sánh và chạy lại từng revision khi được chọn. Kể cả quên tích ô, fingerprint nguồn đổi vẫn chặn ghi cache cũ. Cache thiếu/quá lớn/stale chuyển sang staging Preview mới; không ghi mẫu 20 dòng thay cho kết quả đầy đủ. Add-in không tự Save. Thay đổi version/staging chưa được chạy lại test theo yêu cầu người dùng. Xem [`PROBLEM_CHAIN_SPEC.md`](./PROBLEM_CHAIN_SPEC.md).

Phase 2 bổ sung cây revision với hai hành động có chủ đích: `Làm tiếp từ đây` tạo child của revision được chọn; `Làm lại vấn đề` tạo sibling từ parent của vấn đề cũ. Nhánh cũ và descendants được giữ nguyên, không tự chạy lại/sửa; UI chỉ hiển thị impact report. Người dùng có thể xóa lịch sử rõ ràng: leaf xóa ngay, node có con phải xác nhận rồi xóa cả subtree, root không được xóa. Tips được suy ra từ cây, không persist `branchTip`. Domain/API/UI cross-check đã đạt; live Codex branch smoke và manual Excel sideload vẫn là gate mở.

Typed Step Diagnostics đã được triển khai theo [`TYPED_STEP_DIAGNOSTICS_SPEC.md`](./TYPED_STEP_DIAGNOSTICS_SPEC.md): mẫu kiểm tra đa dạng và tất định, nút chạy toàn bảng đến step đang chọn, staging chỉ lưu step cache sau xác nhận và không ghi sheet. Step cache là session-memory, FIFO tối đa 5 entry/32 MiB; staging tối đa 48 MiB. Ngưỡng riêng của diagnostic là 100.000 dòng, 75 cột hoặc 1 triệu ô tính cả header. Focused checks đã đạt; full regression, Excel runtime và manual sideload chưa chạy theo yêu cầu người dùng, nên chưa coi đây là release evidence hoàn chỉnh.

`Typed Steps` nay là chế độ mặc định. Nhập yêu cầu → Codex tạo cards có kiểu → review/add/edit/delete/reorder → `Chạy preview` → review kết quả Excel runtime → `Duyệt revision và ghi values`. Codex không gửi raw M vào typed compiler; coordinator cấp ID, kiểm graph/column lineage/type/catalog, compiler template mới sinh M. Preview chạy trên workbook tạm và không ghi workbook đang mở. Approval gắn đúng revision/snapshot/preview, chỉ dùng một lần; mọi edit đều khóa preview/approval cũ. Auto-fix chỉ đưa proposal patch, không tự xóa hoặc sửa logic. Kết quả approved được ghi values-only vào sheet có marker riêng `PQ_Typed_Result`; add-in không tự Save. API v2 chạy song song với Advanced M. Xem contract và các gate tại [`PQ_CODE_M_SPEC.md`](./PQ_CODE_M_SPEC.md).

Typed `selectColumns` giữ nguyên thứ tự cột upstream; cột mới chỉ được nối ở cuối bởi operation tạo cột. Workbook kết quả values-only giữ kiểu số/ngày/text của Excel thay vì ép toàn bộ sang Text; chuỗi có tiền tố giống công thức vẫn được lưu dưới dạng text literal.

Automated smoke đã đối chiếu riêng validator/compiler, API lifecycle và Excel 16.0 runtime. Các case filter → add → sort, aggregate, append strict và merge → expand khớp expected độc lập. Manual sideload vẫn là gate riêng để xác nhận Office.js bind/write/reuse trong workbook người dùng.

Coordinator hiện cấp session token 256-bit với idle TTL 30 phút và absolute TTL 8 giờ. Codex job và Excel job có hai slot độc lập; job thứ hai cùng loại nhận `429 COORDINATOR_BUSY` và không được xếp hàng hoặc tự replay. Khi token hết hạn, panel bootstrap phiên mới một lần, xóa plan/preview/approval cũ và yêu cầu người dùng chạy lại thao tác. Temp workspace dùng marked run directory, cleanup sau operation và janitor an toàn cho artifact bị bỏ lại.

#### Advanced M — tương thích

Trong task pane, mở sheet dữ liệu → chọn `PQ_Code-M` → nhập/review M → `Chạy thử và mở sheet kết quả`. Panel chạy M trên workbook tạm, tạo/reuse `PQ_Result` values-only và mở sheet này; source vẫn giữ nguyên. Khi kết quả đúng, bấm `Áp dụng vào sheet nguồn`: nguồn Excel Table chỉ resize/thay Table đó; nguồn usedRange thay toàn bộ usedRange và xóa phần đuôi cũ. Không backup và không tự Save. Chi tiết ở [`PQ_CODE_M_SPEC.md`](./PQ_CODE_M_SPEC.md).

Đây là đường chạy M **tùy ý** trong `M nâng cao · Tin cậy`, kể cả `File.Contents`/nguồn ngoài workbook. Policy hiện hành là `advanced-m-trusted-v1`. Xác nhận theo session + policy + workbook không phải sandbox: M có thể gửi dữ liệu ra mạng, dùng credential hoặc gây tác động ngoài workbook không thể hoàn tác. Không tự tắt privacy levels/cấp credential. Chỉ sau Excel thật refresh/read-back thành công và static result không chứa formula/query/connection thì preview mới sẵn sàng. Khi Apply, panel kiểm lại workbook/source/code rồi ghi values vào nguồn bằng Office.js và luôn hỏi xác nhận riêng cho từng lần ghi. Đây là ngoại lệ có giới hạn của quy tắc Excel nguồn chỉ đọc: **Table hoặc usedRange nguồn sẽ bị thay trực tiếp**. Không bảo đảm Ctrl+Z/rollback; nên thử trước trên workbook không quan trọng. Không tạo file backup hay tự lưu workbook. Giới hạn export 32 MiB, M 16.000 ký tự và kết quả 100.000 dòng/200 cột/2 triệu ô. Với nguồn ngoài cần credential, Excel instance ẩn có thể không xử lý được prompt đăng nhập; khi đó báo lỗi và không ghi nguồn.

Kiểm tra workbook chưa đổi trước Apply dùng dấu vân tay dữ liệu và cấu trúc workbook, không so sánh nguyên bytes của hai lần xuất `.xlsx` (ZIP có thể khác bytes khi dữ liệu không đổi). Nếu ô/công thức/cấu trúc thật sự đổi sau preview, panel hủy preview và dừng trước khi ghi. Sau khi cập nhật Python/JS, **khởi động lại coordinator và đóng/mở task pane** để dùng đường kiểm tra mới; manifest trong `C:\AddinManifests` không cần đổi.

Release regression ngày 12/10/2026 đạt 214 test, 0 fail và 1 skip môi trường symlink; riêng isolated Excel runtime đạt 8/8, gồm external CSV qua `File.Contents` và các nhánh Typed filter/add/sort, aggregate, append, merge. Live Codex strict schema cũng đạt. **Chưa có bằng chứng manual sideload/ghi nguồn bằng tab này trong Excel người dùng**; hãy mở lại coordinator/panel rồi thử trước trên workbook mẫu hoặc một bản copy. Nhánh phân tích công thức Excel ở tab `Trợ lý` vẫn chỉ đề xuất, không tự áp dụng. Các endpoint PQ copy/save cũ đã bị khóa (`410`); panel cũ cần tải lại.

UAT ngắn: dùng workbook không quan trọng → chọn Table → nhập M → `Chạy thử và mở sheet kết quả` → xác nhận `PQ_Result` được tạo/reuse và source chưa đổi → `Áp dụng vào sheet nguồn` → kiểm tra đúng Table được resize/thay, ô ngoài Table còn nguyên. Lặp lại với usedRange để kiểm tra phần đuôi cũ được xóa. Sửa source sau preview phải làm Apply bị khóa; thay riêng nội dung `PQ_Result` không được che giấu thay đổi source. Không Save cho tới khi đối chiếu xong. Đóng/mở lại coordinator và panel để tải bản mới; manifest không đổi.

Với raw data có ô lỗi Excel, `Table.Distinct` trực tiếp trên toàn bộ rows có thể làm Power Query refresh thất bại (`PQ_REFRESH_FAILED`, HRESULT `0x800A03EC`). M mẫu ở [`examples/pq_clean_orders_with_errors.m`](./examples/pq_clean_orders_with_errors.m) lọc dòng rỗng và `Ma_Don_Hang` trống/`null`, khử trùng lặp trên **toàn bộ cột của các dòng không lỗi**, giữ các dòng Power Query nhận là lỗi để tránh xóa nhầm. M này đã chạy trên bản tạm của `raw_sales_dataset_100k_ex.xlsx` (100.000 → 95.630 dòng, 10 cột), xuất workbook kết quả chỉ giá trị và kiểm package thành công; file gốc byte-identical. Đây không phải bằng chứng task pane đã nhập sheet vào Excel đang mở. `Excel.CurrentWorkbook()` có thể chuyển ô lỗi Excel thành `null` khi đọc; vì vậy mã lỗi gốc và việc khử trùng lặp các dòng lỗi **không được bảo đảm**.

Server dùng exclusive bind trên Windows. Một lần chạy mới thử `3079 → 3072`, bỏ qua cổng đang bận và không reuse socket. Nếu cả tám cổng đều bận, coordinator fail-closed thay vì chạy thêm instance không kết nối được với manifest.

Kiểm tra tự động và isolated Excel smoke:

```powershell
py -m unittest tests.test_excel_plan tests.test_excel_connector tests.test_excel_addin_server -v
py -m examples.w21_excel_smoke
```

## Giới hạn rõ ràng của parser đầu tiên

- `.xlsx` được profile giá trị ô, table metadata, date style, hệ ngày 1900/1904 và trạng thái formula cache. Parser không tính công thức; ngày text theo locale và thang phần trăm mơ hồ được giữ nguyên kèm cảnh báo. Workbook mã hóa/mật khẩu không được hỗ trợ. File quá 64 MiB sau giải nén hoặc sheet quá 100.000 dòng bị chặn; đây là giới hạn tạm, chưa phải chứng cứ đạt NFR R1.
- `.csv` hiển thị encoding, delimiter, header, số cột, profile giới hạn và lỗi từng record. Delimiter mơ hồ, header trùng, encoding sai hoặc dòng lệch cột chặn mapping phụ thuộc; chuỗi giống công thức chỉ là text và không được thực thi.
- TMDL được parse read-only bằng `TmdlSerializer` chính thức qua bridge cục bộ; catalog gồm table, column, measure, relationship và M partition. PBIR có catalog page/visual/binding/bookmark/filter cùng allowlist/version gate. PBIR hiện mới qua hợp đồng tĩnh đã pin, chưa chạy toàn bộ JSON Schema offline, vì vậy chỉ có `static_patch_candidate`; `patch_eligible` luôn `false`.
- Snapshot băm toàn bộ file trong thư mục dự án và từng nguồn Excel/CSV. Bước sau sẽ dùng hash này làm cổng `Needs rebase` trước khi tạo bản copy/backup. Hiện chưa có apply.
- Fixture cũ từ [`tests/fixtures.py`](./tests/fixtures.py) vẫn phục vụ test parser ban đầu. Fixture W-02/W-03 mới kiểm tra biến thể dữ liệu và cấu trúc PBIP. Riêng 8 file JSON trong PBIP baseline đã qua một lượt kiểm tra thủ công bằng schema Microsoft công khai; kiểm tra này không nằm trong suite offline, không xác thực TMDL và **không** chứng minh Power BI Desktop mở được. Manifest vẫn ghi `schema_validation: not_run` cho pipeline tự động.
- Fixture đơn hàng dùng đúng 17 tên cột của `clean_final_data.csv` người dùng cung cấp, nhưng mọi dòng đều tổng hợp. Test giữ lại `Quantity` âm/0 và `Discount` dạng 0–30 như dữ liệu tham chiếu; không tự chuẩn hóa thành phần trăm hay coi đơn trả hàng là lỗi.

## Tiến độ theo BPMN

| Lát cắt | Trạng thái | Bằng chứng |
|---|---|---|
| W-01: BPMN v0.5 | Hoàn thành mô hình Figma: 1 frame tổng quan + W-01A…D; warnings/render findings/layout issues đều 0 | `BPMN_MODEL.md`, Figma `Demo_Figma / Page 1` |
| W-02: fixture `.csv`/`.xlsx` | Xong bộ dữ liệu giả, manifest và test; đã được W-04/W-05 sử dụng | `examples/source_fixtures.py`, `tests/test_source_fixtures.py` |
| W-03: fixture PBIP TMDL/PBIR | Fixture TMDL đã qua parser chính thức; 8/8 JSON baseline từng qua schema Microsoft thủ công. Desktop cấp B chưa chạy | `examples/pbip_fixtures.py`, `tests/test_pbip_fixtures.py` |
| W-04: CSV importer/profile | Nghiệm thu chức năng; ambiguity/encoding/header/row error chặn mapping, schema CSV↔XLSX và source hash được kiểm | `pbip_assistant/csv_source.py`, `tests/test_csv_source.py`, `tests/test_source_schema.py` |
| W-05: Excel profile nâng cao | Nghiệm thu chức năng; sheet/table selection, date/style, formula cache và schema drift | `pbip_assistant/xlsx.py`, `tests/test_xlsx_advanced.py` |
| W-06: TMDL adapter/catalog | Nghiệm thu read-only; official parser, catalog, negative test và round-trip spike đạt | `pbip_assistant/tmdl.py`, `tests/test_tmdl.py`, `spikes/w06_tmdl` |
| W-07: PBIR catalog/gate | Nghiệm thu catalog tĩnh; legacy/schema lạ/out-of-allowlist là view-only hoặc blocked. Full JSON Schema và Desktop vẫn chưa chạy | `pbip_assistant/pbir.py`, `tests/test_pbir.py` |
| W-17A: UI source-only | Functional prototype cho S1/S2: upload local, CSV options, preview/profile/issues/schema; chưa phải toàn bộ W-17 | `pbip_assistant/webapp.py`, `pbip_assistant/web/`, `tests/test_webapp.py` |
| W-20: Excel MCP spec + fixture | GX0 đã nghiệm thu: spec v0.1, workbook/manifest tổng hợp và 4 test fixture; riêng package W-20 không bao gồm connector/runtime | `EXCEL_MCP_SPEC.md`, `examples/excel_mcp_fixtures.py`, `tests/fixtures_excel_mcp`, `tests/test_excel_mcp_fixtures.py` |
| W-21: Excel task pane + connector spike | W21-A…D đạt bằng 16 test và isolated Excel 16.0 smoke; task pane sideload/manual bind W21-E còn chờ nên GX1 chưa đóng | `W21_EXCEL_TASKPANE_SPEC.md`, `pbip_assistant/excel_addin_server.py`, `pbip_assistant/excel_addin/`, `tools/excel_connector`, `tools/excel_addin` |
| `N-002/N-003`: nhập, profile, PBIP inventory, snapshot | Có CLI và test; parser còn giới hạn như trên | `tests/test_xlsx.py`, `test_pbip.py`, `test_workflow.py`, `test_reference_schema.py` |
| `N-006/N-007`: xác nhận KPI, đề xuất chart, duyệt dependency | Hợp đồng thuần và unit test; chưa nối AI/model thực | `tests/test_planning.py` |
| `N-008/N-009`: generator, static validation, diff | Chưa làm | Cần fixture TMDL/PBIR thực |
| `N-015/N-018/N-019`: copy, backup, apply, restore | Chưa làm | Cần fault-injection test trước khi bật apply |
| `N-021/N-022/N-023`: Desktop runtime | Chưa làm | Cần Power BI Desktop và PBIP đại diện |

W-01, W-02…W-07, W-20/GX0 và prototype W-17A đã xanh trong phạm vi tương ứng. Automated suite gồm isolated Excel 16.0 smoke cho Advanced M và Typed Steps v2, cùng JS smoke cho preview/approval/write/invalidation; số liệu mới nhất được ghi sau mỗi full regression trong `IMPLEMENTATION_PLAN.md`. Coordinator đã phục vụ tab mới trên HTTPS loopback; manual sideload/ghi trực tiếp Table và usedRange trong Excel người dùng vẫn cần nghiệm thu nên GX1 mở. MCP server W-22 và pilot W-25/26 chưa làm. Full W-17, PBIR JSON Schema và Power BI Desktop validation vẫn chưa chạy; không được áp patch PBIP từ fixture hiện tại.
