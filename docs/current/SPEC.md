# Đặc tả dự án: Trợ lý phân tích Excel/CSV và chỉnh sửa Power BI Project

> Quyết định bổ sung 04/10/2026 (Excel task pane): người dùng chấp thuận gửi prompt và mẫu dữ liệu workbook có giới hạn tới OpenAI qua Codex khi chủ động bấm Phân tích. Ngoại lệ này chỉ áp dụng cho nhánh Excel task pane; PBIP và web UI nguồn vẫn local-only. Workbook nguồn vẫn chỉ đọc; kết quả Codex không được tự duyệt/ghi. Những dòng local-only trước đây trong tài liệu phải được hiểu với ngoại lệ hẹp này. Chưa có preview-after hay apply tổng quát cho công thức do Codex đề xuất.

| Thuộc tính | Giá trị |
|---|---|
| Phiên bản | 0.6 — tích hợp Excel task pane/MCP trên bản copy workbook |
| Ngày | 02/10/2026 |
| Chủ sở hữu sản phẩm | Người khởi xướng dự án — cần xác nhận |
| Người duyệt | Product owner, BI lead, kỹ thuật, bảo mật — cần chỉ định |
| Trạng thái | Draft; đã chốt xử lý cục bộ, bản copy PBIP và tạo biểu đồ theo yêu cầu |

Sơ đồ quy trình để review trước implementation: [BPMN — Luồng Excel + PBIP](BPMN_MODEL.md), được vẽ trong file Figma `Demo_Figma` → `Page 1`. Bản vẽ hiện phản ánh v0.3; vòng phản biện và nhánh xác nhận rủi ro của v0.5 được ghi trong [kế hoạch triển khai](IMPLEMENTATION_PLAN.md) và cần cập nhật lên Figma trước khi coi sơ đồ là baseline.

| Phiên bản | Thay đổi |
|---|---|
| 0.1 | Đặc tả luồng Excel + PBIP và patch TMDL/PBIR. |
| 0.2 | Chốt AI cục bộ và apply trên bản copy PBIP. |
| 0.3 | Bổ sung đề xuất và tạo visual mới theo yêu cầu người dùng. |
| 0.4 | Chốt R1 nhận `.xlsx` và `.csv`; bổ sung vòng người dùng phản biện, AI đánh giá rủi ro, đề xuất tối ưu hoặc giải thích vì sao không nên; chấp nhận PBIP mẫu giả lập có cổng xác minh Desktop. |
| 0.5 | Chốt người dùng được tiếp tục đúng phương án mình chọn sau khi xác nhận rủi ro của lời khuyên `không nên làm`, nếu không có lỗi chặn; lỗi chặn phải hiện nguyên nhân và không thể vượt qua. |
| 0.6 | Bổ sung nhánh Excel Desktop trực tiếp: task pane nhập prompt, connector/MCP đọc workbook đang mở, preview mô phỏng, user duyệt, tạo bản copy, ghi công thức và đọc lại kết quả Excel runtime. Đặc tả chi tiết tại `EXCEL_MCP_SPEC.md`. |

## 1. Mục tiêu và vấn đề cần giải quyết

Người làm Power BI nhận một hoặc nhiều file Excel/CSV mới, đồng thời có một Power BI Project (PBIP) đang sử dụng. Họ phải tự tìm bảng/cột phù hợp, đối chiếu với model hiện tại, viết Power Query M và DAX, sửa metadata, kiểm tra các visual bị ảnh hưởng, rồi lưu bản sao trước khi thay đổi. Công việc dễ sai ở chỗ định nghĩa KPI, grain, khóa, quan hệ và schema giữa các kỳ thay đổi.

Sản phẩm cho phép người dùng đưa `.xlsx`/`.csv` và PBIP vào một phiên làm việc, mô tả insight hoặc mục tiêu phân tích, nhận đề xuất có dẫn chứng, xem thay đổi ở mức dữ liệu/model/report, duyệt từng thay đổi, tạo bản sao khôi phục và áp dụng patch vào PBIP. Mỗi kết luận và mỗi patch phải truy vết được về dữ liệu đầu vào, quy tắc người dùng đã xác nhận và bước kiểm tra đã chạy.

**Chỉ số thành công đề xuất để kiểm chứng với người dùng thử:** thời gian từ khi nhập file đến khi có patch được duyệt giảm ít nhất 50% so với quy trình thủ công; 100% lần apply có backup kiểm tra được; 0 lần ghi vào PBIP khi có lỗi chặn; 100% KPI được tạo có định nghĩa, nguồn dữ liệu và trạng thái xác minh hiển thị.

## 2. Phạm vi sản phẩm

### Trong phạm vi

- Nhập nhiều file `.xlsx` và `.csv` cùng một thư mục PBIP; đọc sheet/table của workbook, header/bản ghi CSV, schema, mẫu dữ liệu, công thức Excel có sẵn dưới dạng metadata; đọc TMDL và PBIR được hỗ trợ. CSV là định dạng nguồn riêng, không phải một loại sheet trong `.xlsx`.
- Profile dữ liệu: số dòng, kiểu dữ liệu, null, duplicate, khóa ứng viên, chênh lệch schema, giá trị bất thường và các dòng không đọc được.
- Nhận yêu cầu/insight bằng tiếng Việt hoặc tiếng Anh; phân biệt **mục tiêu phân tích**, **quy tắc nghiệp vụ đã xác nhận** và **giả thuyết cần kiểm chứng**.
- AI cục bộ đề xuất giải pháp kèm bằng chứng và rủi ro. Người dùng có thể duyệt, từ chối hoặc nêu phương án riêng; AI đánh giá phương án đó, nêu cách tối ưu nếu nên làm hoặc giải thích cụ thể nếu không nên làm. Nếu AI khuyên `không nên làm` nhưng không có lỗi chặn, người dùng được xác nhận rủi ro và tiếp tục **đúng phương án mình chọn**, không bị AI tự thay bằng phương án tối ưu. Không có phê duyệt ngầm sau phản hồi AI.
- Đề xuất mapping nguồn `.xlsx`/`.csv` → bảng/cột model, phép biến đổi M, measure DAX, relationship, format string, description và calculation group khi có đủ căn cứ.
- Tạo patch TMDL; tạo patch PBIR trong phạm vi các JSON thuộc `Report/definition` có schema được hỗ trợ để cập nhật visual hiện hữu hoặc thêm visual mới theo yêu cầu đã được người dùng duyệt.
- Phân tích mục tiêu và cấu trúc dữ liệu để đề xuất loại biểu đồ, measure, dimension, cách tổng hợp, bộ lọc, tiêu đề và vị trí; người dùng có thể sửa đề xuất trước khi tạo.
- Hiển thị preview dữ liệu, model, report impact và diff theo file; chạy kiểm tra; tạo bản copy PBIP, backup và apply/restore trên bản copy.
- Xuất gói patch và báo cáo kiểm tra để review mà không cần apply.
- Chạy một Excel task pane trên Excel Desktop Windows để nhận prompt, đọc workbook đang mở qua connector cục bộ, hiển thị plan/preview, rồi chỉ sau phê duyệt mới tạo và ghi công thức vào một bản copy workbook. Hợp đồng và cổng kiểm chi tiết nằm tại [`EXCEL_MCP_SPEC.md`](EXCEL_MCP_SPEC.md).

### Ngoài phạm vi bản đầu

- Tự động publish lên Power BI Service/Fabric, sửa `.pbix`/`.pbit` trực tiếp hoặc sửa model đang chạy qua TOM.
- Tự xây một dashboard hoàn chỉnh nhiều trang không có mục tiêu, KPI và phạm vi biểu đồ được người dùng xác nhận; hỗ trợ mọi custom visual bên thứ ba.
- Tự đánh giá đúng/sai về mặt nghiệp vụ khi thiếu định nghĩa KPI hoặc số đối chiếu.
- Thực thi Power Query M như một Power BI engine độc lập. Kết quả M/DAX trong Power BI chỉ được xác nhận sau khi Desktop load/refresh và chạy kiểm tra tương ứng.
- Ghi đè nguồn Excel/CSV; xử lý macro/VBA; triển khai gateway hoặc credential của nguồn dữ liệu.
- Gửi nội dung Excel, PBIP, metadata hoặc mẫu dữ liệu lên dịch vụ AI cloud.
- Ghi trực tiếp vào workbook Excel nguồn, điều khiển Excel từ máy khác, thực thi arbitrary script sinh từ prompt, hoặc hỗ trợ `.xls`/macro/VBA trong prototype Excel MCP.

### Lộ trình release đề xuất

| Release | Kết quả bàn giao |
|---|---|
| R1 — MVP | Nhập `.xlsx`/`.csv` + PBIP, xử lý và AI trên máy, profile, mapping có duyệt, vòng phản biện/rủi ro của đề xuất, đề xuất M/DAX/TMDL và biểu đồ, patch PBIR để thay binding hoặc thêm visual Power BI tiêu chuẩn, diff, kiểm tra tĩnh, tạo bản copy PBIP, backup/apply/restore trên bản copy và hướng dẫn xác minh trong Desktop. |
| R2 | Tự động hóa kiểm tra load/refresh và DAX query qua Desktop khi môi trường hỗ trợ; mở rộng catalog visual và các thao tác PBIR sau khi có fixture và kiểm tra tác động. |
| R3 | Calculation group và relationship nâng cao, benchmark DAX, nhiều report chung model, chính sách doanh nghiệp và chia sẻ phiên làm việc. |

## 3. Người dùng và quyền

| Vai trò | Nhiệm vụ | Quyền trong ứng dụng |
|---|---|---|
| BI Analyst | Nhập file, mô tả insight, mapping, review và tạo patch | Đọc/đề xuất/xuất; apply khi được cấu hình cho phép |
| BI Lead/Reviewer | Xác nhận định nghĩa KPI, relationship, thay đổi report | Duyệt đề xuất, duyệt thay đổi có tác động rộng |
| Project Owner | Chọn nơi lưu bản copy PBIP, khôi phục | Apply/restore trên bản copy có quyền ghi |
| Administrator | Cấu hình xử lý dữ liệu, model AI cục bộ và lưu vết | Cấu hình; không mặc nhiên đọc nội dung dữ liệu |

R1 gộp vai trò đề xuất yêu cầu và duyệt patch vào cùng một người dùng trên máy cá nhân; AI là bên tư vấn, không phải người duyệt. Nhật ký vẫn tách sự kiện AI đề xuất, người dùng phản biện và người dùng phê duyệt. Không giả định có hệ thống đăng nhập doanh nghiệp trong R1.

## 4. Luồng người dùng chính

1. Người dùng chọn một hoặc nhiều file `.xlsx`/`.csv` và thư mục PBIP. Hệ thống kiểm tra cấu trúc PBIP, định dạng TMDL/PBIR và quyền đọc.
2. Hệ thống tạo snapshot chỉ đọc: danh sách file, SHA-256 từng file, phiên bản schema và thời điểm đọc. Tất cả đề xuất gắn với snapshot này.
3. Hệ thống profile Excel/CSV và phân tích model/report hiện hữu. UI hiển thị các vấn đề và mức độ tin cậy của mapping.
4. Người dùng nhập mục tiêu, insight và quy tắc. Hệ thống hỏi về các điểm ảnh hưởng phép tính như grain, định nghĩa doanh thu, ngày phân tích, đơn hủy và hoàn trả.
5. Hệ thống lập kế hoạch có cấu trúc: nguồn → biến đổi M → bảng/cột model → relationship → measure → visual hiện hữu bị tác động và visual mới được đề xuất. Nếu người dùng yêu cầu biểu đồ cụ thể, hệ thống kiểm tra đủ trường dữ liệu và nêu lý do khi cần đề xuất loại khác. Người dùng có thể phản biện hoặc nêu phương án riêng; AI đánh giá bằng chứng, rủi ro và phương án tối ưu, rồi trả kết quả để người dùng quyết định lại. Nếu AI khuyên `không nên làm` mà không có lỗi chặn, người dùng có thể xác nhận rủi ro và duyệt đúng phương án của mình. Nếu có lỗi chặn, hệ thống hiện lỗi/nguyên nhân/cách khắc phục và không cho vượt qua. Chỉ phiên bản đề xuất được người dùng phê duyệt tường minh mới đi tiếp.
6. Hệ thống tạo patch trên một bản làm việc tách khỏi PBIP gốc. Static validation chạy trước khi hiện nút duyệt.
7. Người dùng xem preview từng thay đổi, sửa mapping/quy tắc hoặc bỏ chọn hạng mục, rồi duyệt patch. Sửa đổi sau phê duyệt làm mất hiệu lực phê duyệt cũ và buộc đánh giá/preview lại.
8. Trước apply, hệ thống kiểm tra lại hash nguồn, tạo bản copy PBIP ở nơi người dùng chọn, tạo backup nhất quán của bản copy, ghi manifest, áp dụng patch lên bản copy và xác minh file sau ghi. PBIP gốc luôn ở chế độ chỉ đọc.
9. Người dùng mở bản copy PBIP trong Power BI Desktop, refresh nếu M/partition thay đổi, chạy các kiểm tra runtime. UI ghi trạng thái `Applied — pending Desktop verification` hoặc `Verified` đúng theo bằng chứng có được.
10. Nếu phát hiện lỗi, người dùng xem lý do và restore từ backup phù hợp.

### Luồng thay thế — làm việc trực tiếp trong Excel

1. Người dùng mở workbook `.xlsx` đã lưu và mở task pane.
2. Excel connector tạo snapshot chỉ đọc của workbook/sheet/table/header và capability matrix.
3. Người dùng nhập prompt; local planner sinh plan revision, công thức và các câu hỏi cần xác nhận.
4. UI hiển thị `Simulated preview` trước/sau; chưa có thao tác ghi workbook.
5. Người dùng chọn operation và phê duyệt đúng snapshot/revision.
6. Connector kiểm tra lại hash, tạo và đọc lại một bản copy; nếu thất bại thì dừng.
7. MCP/connector chỉ ghi operation đã duyệt vào bản copy, yêu cầu Excel calculate và đọc lại formula/value/error.
8. Chỉ bằng chứng đọc lại từ Excel mới được gắn `Excel runtime verified`; workbook nguồn phải byte-identical.

Luồng lỗi bắt buộc: Excel lỗi/mật khẩu, PBIP không đúng cấu trúc, PBIR legacy, schema không hỗ trợ, mapping mơ hồ, TMDL/PBIR invalid, nguồn đổi sau preview, thiếu dung lượng backup, apply một phần, Desktop đang có thay đổi chưa lưu, refresh lỗi và kiểm tra số liệu không khớp.

## 5. Ví dụ xuyên suốt

**Đầu vào:** `Sales_2026_09.xlsx`, `Returns_2026_09.xlsx`, `Products.xlsx` và `Retail.pbip`. Model hiện có `FactSales`, `DimProduct`, `DimDate`, measure `[Gross Sales]`; report có visual đang dùng `[Gross Sales]`.

**Yêu cầu người dùng:** “Kiểm tra giả thuyết doanh thu thuần miền Nam giảm vì tỷ lệ trả hàng tăng. Tạo Net Sales, Return Rate và YoY; cập nhật biểu đồ doanh thu sang Net Sales và thêm biểu đồ xu hướng tỷ lệ trả hàng theo tháng.”

**Hệ thống phát hiện:** file Sales tháng 9 có cột `Mã SP` tương ứng nhiều khả năng với `ProductId`; 31 mã sản phẩm không có trong `DimProduct`; `DiscountPct` có cả `10` và `0,10`; report có 4 visual dùng `[Gross Sales]`.

**Điểm cần người dùng quyết định:** cách chuẩn hóa `DiscountPct`; có tính đơn `Cancelled` không; khoản hoàn trả ghi nhận theo `OrderDate` hay `ReturnDate`; thay cả 4 visual hay chỉ biểu đồ được chỉ định. Nếu chưa trả lời, hệ thống chỉ xuất đề xuất, không tạo patch apply cho các phép tính phụ thuộc.

**Đề xuất biểu đồ:** line chart “Tỷ lệ trả hàng theo tháng”, trục X `DimDate[Month]`, trục Y `[Return Rate]`, filter `Region = Miền Nam`; hệ thống nêu rằng dạng đường phù hợp để xem biến động theo thời gian. Nếu người dùng chọn bar chart, hệ thống dùng loại đó khi các vai trò dữ liệu hợp lệ và ghi nhận lựa chọn.

**Preview mong đợi:** bảng so sánh 20 dòng dữ liệu trước/sau; 31 mã chưa match được giữ trong bảng lỗi; diff M cho query Sales; diff TMDL thêm `[Net Sales]`, `[Return Rate]`, `[Net Sales YoY %]`; diff PBIR thay binding một visual và thêm `visual.json` cho line chart mới trên trang được chọn; đối chiếu tổng Sales/Returns theo tháng; cảnh báo tác động đến visual khác.

**Ví dụ phản biện:** nếu người dùng đề nghị dùng `Sales` sẵn có làm `Net Sales`, AI không tự đổi tên measure. AI kiểm tra `Sales` đã trừ discount/returns hay chưa, nêu rủi ro đếm đôi, đề xuất công thức/đối chiếu tối ưu nếu đủ căn cứ; thiếu định nghĩa thì trả `chưa đủ căn cứ`. Người dùng phải duyệt lại phiên bản đề xuất sau phản biện.

## 6. Yêu cầu chức năng

| ID | Ưu tiên | Release | Yêu cầu kiểm thử được |
|---|---|---|---|
| FR-001 | Must | R1 | Hệ thống phải nhận nhiều `.xlsx` và `.csv`; đọc sheet/table theo lựa chọn với workbook hoặc header/bản ghi với CSV; báo lỗi riêng cho file mật khẩu, lỗi định dạng, mã hóa hoặc không đọc được. |
| FR-002 | Must | R1 | Hệ thống phải chọn một PBIP và xác định report, semantic model, TMDL, loại PBIR, schema và các file không được phép sửa ngoài. |
| FR-003 | Must | R1 | Hệ thống phải profile từng nguồn `.xlsx`/`.csv` và hiển thị số dòng/null/duplicate, kiểu dữ liệu, giá trị mẫu đã giới hạn, schema drift và lý do các dòng lỗi. |
| FR-004 | Must | R1 | Hệ thống phải đề xuất mapping nguồn → model với bằng chứng (tên cột, kiểu, mức trùng, khóa) và cho người dùng sửa/xác nhận. |
| FR-005 | Must | R1 | Hệ thống phải lưu định nghĩa KPI có công thức nghiệp vụ, grain, ngày phân tích, bộ lọc, đơn vị, nguồn và trạng thái xác nhận trước khi sinh DAX liên quan. |
| FR-006 | Must | R1 | Hệ thống phải tạo kế hoạch thao tác có kiểu, target và dependency; từ chối các thao tác nằm ngoài danh mục được hỗ trợ. |
| FR-007 | Must | R1 | Hệ thống phải sinh M và patch TMDL trên bản làm việc; giữ nguyên các object/thuộc tính không thuộc patch. |
| FR-008 | Must | R1 | Hệ thống phải kiểm tra cú pháp/parse TMDL, tham chiếu model, tên trùng, dependency cycle, khóa quan hệ và tính hợp lệ của patch trong phạm vi khả dụng offline. |
| FR-009 | Must | R1 | Hệ thống phải hiển thị unified/side-by-side diff theo file và tóm tắt ngữ nghĩa: thêm/sửa/xóa bảng, cột, measure, relationship, M và report binding. |
| FR-010 | Must | R1 | Hệ thống phải cho phép duyệt/bỏ chọn từng thay đổi theo dependency; không cho apply tập thay đổi bị thiếu dependency. |
| FR-011 | Must | R1 | Hệ thống phải tạo bản copy PBIP và backup có manifest/hash, kiểm tra đọc lại được, trước khi ghi patch vào bản copy; không ghi vào PBIP gốc. |
| FR-012 | Must | R1 | Hệ thống phải kiểm tra hash PBIP gốc ngay trước khi tạo bản copy; nếu khác snapshot thì dừng và yêu cầu rebase/preview lại. |
| FR-013 | Must | R1 | Hệ thống phải ghi patch trên bản copy, xác minh hash và cung cấp restore cho bản copy; nếu một file ghi lỗi thì khôi phục các file đã ghi trong cùng phiên hoặc báo rõ trạng thái không nhất quán. |
| FR-014 | Must | R1 | Hệ thống phải xuất patch bundle gồm manifest, diff, file thay đổi, kiểm tra, quyết định của người dùng và hướng dẫn xác minh trong Desktop. |
| FR-015 | Must | R1 | Hệ thống phải phân biệt `static pass`, `runtime pass`, `warning`, `blocked` và `not run`; không gắn nhãn `Verified` khi chưa có bằng chứng runtime. |
| FR-016 | Must | R1 | Hệ thống phải cho phép thay measure binding trong visual PBIR hiện hữu nếu file thuộc `definition`, schema hỗ trợ và tham chiếu mới tồn tại. |
| FR-017 | Must | R1 | Hệ thống phải kiểm tra PBIR JSON với schema đúng phiên bản, phát hiện tham chiếu visual/bookmark/filter bị ảnh hưởng và cung cấp bước xác minh report load được bằng Desktop. |
| FR-018 | Should | R2 | Hệ thống phải chạy bộ DAX query đối chiếu trên model đã refresh, lưu kết quả theo filter context và so sánh với số kiểm soát do người dùng cung cấp. |
| FR-019 | Could | R3 | Hệ thống đề xuất calculation group, relationship phức tạp và benchmark measure trước/sau; chỉ apply khi tác động đã được duyệt. |
| FR-020 | Must | R1 | Hệ thống phải phân tích yêu cầu biểu đồ, kiểu/trạng thái dữ liệu và đề xuất visual tiêu chuẩn kèm loại biểu đồ, trường gắn vào từng vai trò, phép tổng hợp, filter, thời gian, tiêu đề, trang đích và lý do chọn. |
| FR-021 | Must | R1 | Hệ thống phải cho người dùng sửa/duyệt loại biểu đồ, trục, measure, filter, tiêu đề và trang đích trước khi sinh PBIR; nếu yêu cầu không đủ dữ liệu hoặc visual không được hỗ trợ, phải giải thích và không tự tạo visual sai. |
| FR-022 | Must | R1 | Hệ thống phải tạo visual mới bằng PBIR JSON trong bản copy PBIP theo schema hỗ trợ, cấp tên object duy nhất, đặt ở vị trí không đè visual khác hoặc trên trang mới đã được người dùng duyệt, hiển thị diff và cung cấp bước kiểm tra Desktop load. |
| FR-023 | Must | R1 | Khi nhập `.csv`, hệ thống phải hiển thị encoding, dấu phân cách, header và số cột đã phát hiện; nếu phát hiện mơ hồ hoặc dòng lỗi thì yêu cầu người dùng chọn/correct cách đọc trước khi dùng dữ liệu để lập patch. |
| FR-024 | Must | R1 | AI cục bộ phải trả đề xuất dưới dạng mục tiêu, bằng chứng từ snapshot, các giả định, thao tác dự kiến, rủi ro và mức độ chắc chắn; không tự phê duyệt đề xuất. |
| FR-025 | Must | R1 | Khi người dùng đưa phương án hoặc phản biện, hệ thống phải lưu nguyên văn ý kiến, tạo phiên bản đề xuất mới và trả một trong ba kết quả: `nên làm` kèm cách tối ưu, `không nên làm` kèm nguyên nhân/tác động, hoặc `chưa đủ căn cứ` kèm thông tin cần bổ sung. |
| FR-026 | Must | R1 | Hệ thống chỉ cho tạo patch từ phiên bản đề xuất được người dùng phê duyệt tường minh trên snapshot hiện hành; sửa nguồn/quy tắc/đề xuất hoặc thay đổi hash phải hủy hiệu lực phê duyệt cũ. Lỗi an toàn, schema hoặc dependency là cổng chặn độc lập với ý kiến AI. |
| FR-027 | Must | R1 | Nếu AI khuyên `không nên làm` và không có lỗi chặn, hệ thống phải cho người dùng xem reason/rủi ro, xác nhận rủi ro tường minh, rồi tiếp tục với đúng phương án/operation người dùng đã chọn; không tự áp phương án tối ưu của AI. Xác nhận gắn với revision, snapshot, actor và operation IDs. |
| FR-028 | Must | R1 | Nếu có lỗi chặn, hệ thống phải hiển thị mã lỗi, target, nguyên nhân và cách khắc phục khả dụng; vô hiệu hóa bước sinh/apply phụ thuộc, không cung cấp thao tác override bằng AI hoặc người dùng. |
| FR-029 | Must | Excel MCP prototype | Task pane phải bind đúng Excel session/workbook và tạo snapshot chỉ đọc gồm identity/hash/sheet/table/header/capability mà không sửa workbook. |
| FR-030 | Must | Excel MCP prototype | Prompt phải được xử lý cục bộ thành plan revision và typed operations; trường/sheet không tồn tại phải thành câu hỏi hoặc hard blocker, không được bịa mapping. |
| FR-031 | Must | Excel MCP prototype | UI phải hiển thị before/after `Simulated preview`, công thức dự kiến, assumptions, risk và validation trước khi cho phê duyệt; preview không được gọi tool ghi. |
| FR-032 | Must | Excel MCP prototype | Approval phải gắn snapshot/revision/operation IDs; thay đổi prompt, workbook, plan hoặc lựa chọn operation làm approval cũ hết hiệu lực. |
| FR-033 | Must | Excel MCP prototype | Sau approval, connector phải tạo bản copy không ghi đè và đọc lại được trước khi apply; tool ghi vào workbook nguồn phải trả hard block không override. |
| FR-034 | Must | Excel MCP prototype | Connector chỉ thực thi operation allowlist, calculate bản copy bằng Excel và đọc lại formula/value/error; không nhận arbitrary script từ prompt. |
| FR-035 | Must | Excel MCP prototype | Static preview và Excel runtime evidence phải có nhãn/trạng thái riêng; không được gắn `verified` khi chưa calculate và đọc lại kết quả từ Excel. |
| FR-036 | Must | Excel MCP prototype | Log/audit không được chứa raw cell, workbook binary, prompt raw hoặc token; chỉ lưu metadata cần thiết cho traceability. |

### Quy tắc nghiệp vụ

| ID | Quy tắc |
|---|---|
| BR-001 | Insight do người dùng nêu được lưu là giả thuyết cho đến khi có phép kiểm định và bằng chứng; không tự động chuyển thành kết luận. |
| BR-002 | KPI chưa có định nghĩa về grain, ngày và các khoản cộng/trừ liên quan được đánh dấu `Needs clarification`; không được apply measure phát sinh từ KPI đó. |
| BR-003 | Dòng dữ liệu bị loại vì lỗi/duplicate phải hiện trong thống kê và có thể truy vết; không được âm thầm biến mất. |
| BR-004 | Thay đổi relationship, xóa/đổi tên measure hoặc đổi binding của visual phải hiện danh sách phụ thuộc trước khi duyệt. |
| BR-005 | Preview chỉ có hiệu lực với snapshot nguồn tương ứng; hash thay đổi làm hết hiệu lực phê duyệt cũ. |
| BR-006 | Bản copy và backup phải hoàn tất, kiểm tra được trước apply. Restore chỉ tác động bản copy, là hành động tường minh, có preview và nhật ký. |
| BR-007 | Mọi kết quả kiểm tra ghi phương pháp, input, thời điểm và trạng thái; `not run` không được hiển thị như `pass`. |
| BR-008 | Yêu cầu biểu đồ của người dùng là ưu tiên đầu tiên; nếu dữ liệu không phù hợp với loại biểu đồ yêu cầu, hệ thống phải nêu nguyên nhân và đưa phương án thay thế để người dùng quyết định. |
| BR-009 | Visual mới chỉ được sinh khi measure/dimension/filter tham chiếu đã tồn tại hoặc nằm trong cùng patch, và trang đích/vị trí đã được duyệt. |
| BR-010 | AI tư vấn chứ không duyệt thay người dùng. Kết luận `nên làm` vẫn cần phê duyệt tường minh; `không nên làm` phải nêu bằng chứng, rủi ro và một phương án khả thi hơn nếu có. |
| BR-011 | Ý kiến phản biện của người dùng tạo phiên bản đề xuất mới; phê duyệt cũ không chuyển sang phiên bản mới. Cả đề xuất ban đầu, ý kiến người dùng, đánh giá AI và quyết định cuối phải truy vết được. |
| BR-012 | Cổng chặn tất định (file ngoài allowlist, bản gốc, schema không hỗ trợ, tham chiếu/dependency sai, backup không đạt) không được AI hoặc người dùng bỏ qua bằng hội thoại. Đánh giá rủi ro nghiệp vụ không thay thế kiểm tra tĩnh/runtime. |
| BR-013 | Lời khuyên `không nên làm` không phải lỗi chặn. Khi không có lỗi chặn, người dùng có thể chọn tiếp tục đúng phương án của mình sau khi xác nhận rủi ro riêng biệt và duyệt patch; phương án tối ưu của AI chỉ được dùng nếu người dùng chủ động chọn. |
| BR-014 | Lỗi chặn có ưu tiên cao hơn mọi lời khuyên AI và phê duyệt người dùng. Hệ thống phải nêu lỗi và target có thể xác định được, cùng bước khắc phục khả dụng; không tạo đường đi bỏ qua cổng chặn. |

## 7. Mô hình dữ liệu của ứng dụng

| Đối tượng | Trường cốt lõi | Ý nghĩa |
|---|---|---|
| `ProjectSnapshot` | `id`, `sourceRootPath`, `copyRootPath`, `fileHashes`, `schemaVersions`, `createdAt` | Mốc so sánh bất biến của PBIP gốc, bản copy và Excel |
| `SourceProfile` | `sourceId`, `sheet`, `rowCount`, `columnProfiles`, `issues` | Kết quả profile từng nguồn |
| `BusinessDefinition` | `id`, `name`, `formula`, `grain`, `dateRole`, `filters`, `unit`, `status`, `approver` | Định nghĩa KPI đã được người dùng xác nhận hoặc còn mở |
| `MappingDecision` | `sourceField`, `targetField`, `evidence`, `confidence`, `decision`, `actor` | Liên kết nguồn với model |
| `ProposedOperation` | `id`, `type`, `target`, `payload`, `dependsOn`, `reason`, `risk` | Thao tác đã giới hạn kiểu, có thể duyệt riêng |
| `PatchBundle` | `id`, `baseSnapshotId`, `operations`, `fileDiffs`, `validation`, `approval` | Gói thay đổi có thể xem lại/xuất |
| `BackupManifest` | `id`, `projectRoot`, `files`, `hashes`, `createdAt`, `restoreStatus` | Bằng chứng và đầu vào khôi phục |
| `AuditEvent` | `time`, `actor`, `action`, `target`, `result`, `correlationId` | Truy vết phiên làm việc |
| `VisualProposal` | `id`, `question`, `visualType`, `fieldRoles`, `aggregation`, `filters`, `targetPage`, `layout`, `rationale`, `status` | Đề xuất biểu đồ có thể sửa và duyệt trước khi tạo PBIR |
| `ProposalRevision` | `id`, `parentId`, `snapshotId`, `userFeedback`, `candidatePlan`, `createdAt` | Phiên bản mới sau phản biện; không kế thừa phê duyệt |
| `RiskAssessment` | `revisionId`, `verdict`, `evidence`, `assumptions`, `riskItems`, `optimization`, `reason`, `missingInfo` | Đánh giá tư vấn của AI, tách khỏi cổng chặn tất định |
| `ApprovalDecision` | `revisionId`, `snapshotId`, `selectedOperationIds`, `actor`, `decision`, `time`, `riskAcknowledgementId` | Quyết định tường minh của người dùng gắn với đúng phiên bản và nguồn |
| `RiskAcknowledgement` | `id`, `revisionId`, `snapshotId`, `operationIds`, `warningIds`, `actor`, `time` | Bằng chứng người dùng đã xem/xác nhận rủi ro khi đi ngược lời khuyên AI; không thay thế phê duyệt patch |

Không lưu nội dung Excel thô vào audit log. Metadata report PBIR có thể chứa giá trị từ slicer/filter; áp dụng cùng chính sách bảo vệ như dữ liệu nguồn.

## 8. Kiến trúc đề xuất

**Quyết định cho R1:** ứng dụng cục bộ trên Windows vì PBIP và Power BI Desktop nằm trên máy người dùng. Giao diện web cục bộ hoặc desktop shell; backend điều phối chỉ đọc PBIP gốc và chỉ ghi vào bản copy ở thư mục người dùng chọn. Phân tích dữ liệu và suy luận AI chạy trên máy; không gửi Excel, PBIP, metadata, mẫu dữ liệu hay prompt chứa dữ liệu dự án lên AI cloud. Runtime/model AI cụ thể và cấu hình máy tối thiểu sẽ được chọn sau khi đo prototype.

```text
UI phiên làm việc
  ├─ Importer & profiler (.xlsx + .csv)
  ├─ PBIP parser (TMDL + PBIR)
  ├─ Business definition & mapping registry
  ├─ Planner (AI cục bộ → typed operations; phản biện → risk review → revision)
  ├─ Generators (M, DAX, TMDL, PBIR)
  ├─ Visual recommender & layout checker
  ├─ Validators (static, reconciliation, Desktop runtime)
  └─ Patch engine (diff → backup → apply → restore)
```

Planner chỉ trả về thao tác theo schema nội bộ. AI diễn giải và lập luận rủi ro; các cổng file/schema/dependency/approval chạy bằng logic tất định. AI khuyên `không nên` không chặn nếu không có lỗi kỹ thuật/an toàn: người dùng có thể xác nhận rủi ro để tiếp tục đúng phương án mình chọn. Generator dùng parser/serializer chính thức hoặc được hỗ trợ thay vì tìm/thay text tự do trong TMDL. Microsoft có API `TmdlSerializer` để đọc/ghi folder TMDL. PBIR JSON được kiểm tra theo `$schema` trong từng file. Một patch phải có allowlist đường dẫn; tuyệt đối không ghi vào `.git`, `cache.abf`, `localSettings.json`, credential hoặc file ngoài PBIP đã chọn.

### Quy tắc đề xuất biểu đồ trong R1

Hệ thống chuyển câu hỏi của người dùng thành measure, dimension, kỳ thời gian và filter cần thiết; kiểm tra các field này trong model/patch, sau đó tổng hợp dữ liệu Excel/CSV cục bộ để tạo mẫu xem trước. Mẫu từ nguồn được gắn nhãn `Data preview`, vì kết quả có thể khác Power BI sau khi refresh và áp dụng relationship/filter của model.

| Nhu cầu phân tích | Đề xuất mặc định | Điều kiện tối thiểu |
|---|---|---|
| Xu hướng theo thời gian | Line chart | Trường ngày/tháng hợp lệ và một measure số |
| So sánh nhóm/cửa hàng/vùng | Bar/column chart | Dimension phân loại và một measure số |
| Một KPI tại filter hiện tại | Card | Một measure có định nghĩa và format |
| Xem chi tiết các bản ghi/nhóm | Table/matrix | Field hiển thị và quy tắc tổng hợp rõ ràng |
| So sánh hai thước đo trên cùng nhóm | Clustered bar/column | Hai measure cùng phạm vi lọc hoặc có chú thích khác biệt |

Nếu người dùng chỉ định loại biểu đồ, hệ thống dùng loại đó khi các vai trò dữ liệu hợp lệ; nếu không, hiển thị lý do và phương án thay thế để duyệt. Với insight “returns làm doanh thu giảm”, hệ thống có thể đề xuất hai visual liên quan: xu hướng `Return Rate` theo tháng và so sánh `Net Sales` với `Return Amount` theo vùng; cả hai chỉ được tạo khi người dùng chọn. Catalog R1 chỉ gồm các loại visual tiêu chuẩn đã được kiểm thử trên PBIR; loại không hỗ trợ được báo rõ trước khi apply.

### Ranh giới dữ liệu và kiểm tra

| Lớp | Có thể biết | Không thể kết luận chỉ từ lớp này |
|---|---|---|
| Excel/CSV | Dòng dữ liệu, kiểu, số tổng, lỗi nguồn | DAX thực thi đúng trong filter context của Power BI |
| PBIP/TMDL | Metadata model, DAX/M text, relationship | Dữ liệu import thực tế trong cache và thời gian chạy query |
| PBIR | Cấu trúc page/visual/binding, visual mới hợp schema | Visual render đúng cho mọi tương tác |
| Power BI Desktop sau refresh | Kết quả query, lỗi load, một phần performance | Tính đúng nghiệp vụ nếu không có số kiểm soát |

## 9. Hợp đồng patch và áp dụng

Gói patch đề xuất có cấu trúc sau (tên và vị trí lưu cuối cùng cần chốt khi thiết kế kỹ thuật):

```text
patch-20261002-001/
  manifest.json
  decisions.json
  validations.json
  changes.patch
  changed-files/
  README.md
```

`manifest.json` chứa `baseSnapshotId`, hash trước/sau theo từng file, operation ID, dependency, phiên bản ứng dụng/schema và trạng thái apply. `changed-files` chỉ chứa file được phép sửa. Gói phải giải nén/xem được độc lập nhưng không tự chạy khi người dùng mở.

**Giao thức apply:** (1) khóa phiên áp dụng; (2) xác nhận hash PBIP gốc; (3) tạo bản copy đầy đủ ở thư mục đích khác thư mục gốc, kiểm tra các tham chiếu tương đối giữa report và semantic model; (4) tạo backup của bản copy và kiểm tra đọc lại được; (5) bảo đảm bản copy chưa mở với thay đổi chưa lưu trong Desktop; (6) ghi patch vào bản copy từ staging; (7) đọc lại và so hash; (8) đánh dấu `Applied`; (9) yêu cầu Desktop mở bản copy và load/refresh để hoàn tất runtime validation. Nếu hỏng trong bước 6–7, phục hồi bản copy từ backup và ghi rõ file nào phục hồi thành công. Không coi nhiều file write là atomic tuyệt đối.

**Xung đột:** nếu `.xlsx`/`.csv`/PBIP đổi sau preview, patch trở về `Needs rebase`. Người dùng thấy thay đổi mới và duyệt lại. Diff kiểu Git là cách hiển thị, không yêu cầu PBIP phải nằm trong Git repository và không tự tạo commit.

**Khôi phục:** restore đọc manifest, kiểm tra đúng bản copy và cho xem diff ngược. Nếu bản copy đã thay đổi thêm sau lần apply, hệ thống không tự ghi đè; yêu cầu người dùng chọn một snapshot đích và xác nhận tác động. PBIP gốc không thuộc target restore.

## 10. Màn hình và nội dung preview

| Màn hình | Nội dung tối thiểu |
|---|---|
| S1 — Chọn đầu vào | File `.xlsx`/`.csv`, folder PBIP, encoding/delimiter CSV khi cần, định dạng phát hiện, lỗi import |
| S2 — Data profile | Schema, số dòng, null, duplicate, unmatched key, bảng dòng lỗi, dữ liệu mẫu giới hạn |
| S3 — Insight & business rules | Yêu cầu người dùng, giả thuyết, KPI definition, câu hỏi cần xác nhận, ý kiến phản biện và lịch sử revision |
| S4 — Mapping & plan | Source→target, độ tin cậy và bằng chứng, cây dependency, đề xuất biểu đồ với loại/trục/measure/filter/trang đích và lý do; khuyến nghị/rủi ro AI và xác nhận rủi ro riêng nếu AI khuyên không nên |
| S5 — Preview patch | Data before/after, model diff, PBIR impact, biểu đồ mẫu gắn nhãn `Data preview`, phác thảo vị trí visual mới, file diff, status validation, lý do mỗi thay đổi |
| S6 — Apply & history | Hash check, backup manifest, tiến trình apply, Desktop verification, restore; lỗi chặn có mã/target/nguyên nhân/hướng khắc phục và không có nút override |

Nút `Apply` chỉ bật khi mọi operation được chọn có đủ dependency, không có lỗi chặn, backup khả dụng, snapshot chưa đổi và người dùng đã duyệt các thay đổi có tác động rộng. Nếu AI khuyên `không nên làm`, xác nhận rủi ro hợp lệ cho đúng revision/snapshot/operation là điều kiện bổ sung; nó không thay thế bước duyệt diff/apply.

## 11. Kiểm tra và mức độ bằng chứng

| Nhóm | Kiểm tra | Mức kết luận |
|---|---|---|
| Import | File đọc được, sheet/table đúng, dữ liệu không vượt giới hạn xử lý đã cấu hình | Static |
| Data | Schema drift, khóa trùng, orphan key, null, số dòng trước/sau, reconciliation theo nhóm | Static trên Excel/CSV |
| Model | TMDL parse, object tồn tại, tên trùng, dependency, cardinality ứng viên | Static; một số quy tắc cần Desktop |
| M/DAX | Tham chiếu và cấu trúc, các mẫu lỗi đã biết, test case mẫu | Static; kết quả thực thi cần Desktop |
| PBIR | JSON schema, tên object duy nhất, vai trò dữ liệu, tham chiếu tới measure, vị trí không chồng lấn, file/object dependency | Static; khả năng render cần Desktop |
| Runtime | Load PBIP, refresh, DAX query với filter context, so số kiểm soát, visual lỗi | Runtime |

Một kiểm tra số liệu cần ghi rõ công thức đối chiếu. Ví dụ: `Gross Sales - Discount - Returns = Net Sales`, đối chiếu theo tháng/cửa hàng với sai số làm tròn được người dùng thiết lập. Không dùng một phép tính Python/JavaScript trên Excel làm bằng chứng rằng DAX trong Desktop trả đúng kết quả nếu model còn relationship/filter khác.

## 12. Phi chức năng và bảo mật — ngưỡng đề xuất cho R1

| ID | Yêu cầu | Ngưỡng nghiệm thu đề xuất |
|---|---|---|
| NFR-001 | Hiệu năng profile | p95 ≤ 60 giây cho 5 file `.xlsx`/`.csv`, tổng ≤ 250 MB, ≤ 500.000 dòng trên máy test chuẩn do dự án công bố. |
| NFR-002 | Preview | p95 ≤ 10 giây cho diff ≤ 1.000 file metadata và ≤ 20 MB text; profiling chạy nền có tiến trình. |
| NFR-003 | Toàn vẹn | 100% file PBIP trong bản copy được ghi có hash trước/sau; 100% apply có backup được đọc lại trước ghi; 0 lần ghi vào PBIP gốc. |
| NFR-004 | Khôi phục | Restore thành công trên 100% bộ test mô phỏng lỗi giữa chừng; báo file lỗi nếu hệ điều hành chặn restore. |
| NFR-005 | Quyền truy cập | PBIP gốc chỉ đọc; chỉ ghi patch vào bản copy và ghi backup/export vào các thư mục người dùng chọn; chống path traversal, symlink trỏ ra ngoài và file không thuộc allowlist. |
| NFR-006 | Dữ liệu AI | 0 yêu cầu chứa nội dung hoặc metadata dự án gửi tới AI cloud; kiểm tra bằng log mạng trong test và cấu hình chặn truy cập mạng của thành phần AI. |
| NFR-007 | Quan sát | Mỗi operation/apply/restore có correlation ID; log không chứa raw cell value, token, credential hoặc workbook binary. |
| NFR-008 | Khả dụng | Nếu AI cục bộ không khởi động được, người dùng vẫn xem profile, model, history và export dữ liệu kiểm tra đã có. |

Ngưỡng NFR-001/002 là mục tiêu thiết kế để đo ở prototype, chưa phải cam kết đã đạt. Cần thống nhất cấu hình máy test và giới hạn file thực tế với người dùng thử.

## 13. Acceptance criteria cho luồng trọng yếu

| ID | Tình huống | Kết quả mong đợi |
|---|---|---|
| AC-001 | Chọn 3 Excel hợp lệ và PBIP có TMDL/PBIR | Hiện 3 source profile, inventory model/report và snapshot ID; chưa ghi vào PBIP gốc. |
| AC-002 | `DiscountPct` có cả `10` và `0,10` | Gắn cờ mơ hồ, hỏi quy tắc chuẩn hóa; chặn measure phụ thuộc cho đến khi xác nhận. |
| AC-003 | Người dùng nói “miền Nam giảm vì returns tăng” | Lưu như giả thuyết; đề xuất các phép tính kiểm chứng; không hiển thị là kết luận. |
| AC-004 | Patch thêm `[Net Sales]` tham chiếu cột không tồn tại | Validation `blocked`, chỉ rõ file/object/cột; `Apply` bị vô hiệu. |
| AC-005 | PBIP thay đổi sau preview | Hash mismatch; hiển thị diff mới và buộc tạo preview/duyệt lại. |
| AC-006 | Không tạo/đọc lại được bản copy hoặc backup | Không ghi patch vào bản copy; PBIP gốc giữ nguyên; hiện nguyên nhân. |
| AC-007 | Lỗi khi ghi file thứ hai của bản copy | Phục hồi file đã ghi trong bản copy; nếu phục hồi thất bại, hiện trạng thái không nhất quán và đường dẫn backup. |
| AC-008 | Patch M apply thành công nhưng chưa refresh Desktop | Trạng thái `Applied — pending Desktop verification`; không hiển thị `Verified`. |
| AC-009 | PBIR legacy hoặc file PBIR ngoài allowlist | Chỉ xem/impact; không cho patch file đó; đề xuất chuyển định dạng bằng Power BI Desktop. |
| AC-010 | User bỏ chọn measure mà visual binding mới phụ thuộc | Hệ thống chặn tổ hợp hoặc tự bỏ chọn visual binding sau khi hiện rõ dependency. |
| AC-011 | PBIR schema valid nhưng Desktop báo visual lỗi | Ghi `Runtime failed`, giữ backup và cung cấp restore; không gắn nhãn thành công cuối. |
| AC-012 | User restore bản copy sau khi có thay đổi bổ sung | Hiển thị diff ngược và xung đột; không tự ghi đè thay đổi bổ sung hoặc tác động PBIP gốc. |
| AC-013 | User yêu cầu “biểu đồ xu hướng Return Rate theo tháng ở miền Nam” | Đề xuất line chart với trục tháng, measure `[Return Rate]`, filter miền Nam, trang đích và lý do; người dùng có thể sửa trước khi duyệt. |
| AC-014 | User duyệt biểu đồ mới và các measure phụ thuộc | Patch tạo object visual mới trong PBIR của bản copy, tên không trùng, binding hợp lệ, diff hiện file mới và Desktop mở report không báo lỗi chặn. |
| AC-015 | User yêu cầu scatter plot nhưng thiếu cả hai measure số | Hệ thống nêu các trường còn thiếu, đề xuất biểu đồ khác hoặc hỏi bổ sung; không sinh PBIR visual sai. |
| AC-016 | Trang đích không đủ chỗ cho visual mới | Preview đề xuất vị trí khác hoặc trang mới; chỉ tạo sau khi người dùng duyệt vị trí/trang. |
| AC-017 | Nhập `.csv` cùng `.xlsx` có header tương ứng | Profile riêng từng nguồn và so schema; không ép CSV thành sheet Excel hoặc ghi đè nguồn. |
| AC-018 | CSV có encoding/delimiter mơ hồ hoặc số cột không đồng nhất | Hiện lựa chọn đọc, số dòng lỗi và mẫu giới hạn; dừng mapping/patch phụ thuộc cho đến khi người dùng xác nhận cách đọc. |
| AC-019 | AI đề xuất KPI/chart và người dùng đồng ý | Lưu phê duyệt tường minh gắn `revisionId` và `snapshotId`; chỉ các operation được chọn mới vào patch. |
| AC-020 | Người dùng phản biện và phương án hợp lệ nhưng có thể tối ưu | Lưu ý kiến gốc, đánh giá rủi ro/bằng chứng và phiên bản tối ưu; phê duyệt cũ mất hiệu lực, không tự apply. |
| AC-021 | Người dùng đề nghị dùng `Sales` làm `Net Sales` nhưng chưa biết returns đã trừ chưa | Trả `chưa đủ căn cứ` hoặc `không nên làm` với lý do cụ thể, nêu định nghĩa/đối chiếu còn thiếu; không sinh measure phụ thuộc. |
| AC-022 | AI kết luận `nên làm` nhưng operation đụng PBIP gốc hoặc PBIR ngoài allowlist | Cổng an toàn trả `blocked`; cả đồng ý của người dùng lẫn lời AI không bật được apply. |
| AC-023 | Nguồn hoặc phiên bản đề xuất đổi sau khi đã duyệt | Phê duyệt cũ bị vô hiệu; hệ thống yêu cầu đánh giá, preview và duyệt lại trên snapshot/revision mới. |
| AC-024 | AI khuyên `không nên làm`, không có lỗi chặn; người dùng chọn giữ phương án của mình | UI hiện reason/rủi ro; sau xác nhận rủi ro riêng và phê duyệt đúng revision/snapshot/operations, patch/preview giữ đúng phương án người dùng, không âm thầm thay bằng tối ưu của AI. |
| AC-025 | Có lỗi chặn dù AI khuyên `nên làm` và người dùng muốn tiếp tục | Hiện mã lỗi, target, nguyên nhân và hướng khắc phục khả dụng; không cho xác nhận rủi ro để vượt qua; không sinh/apply thao tác phụ thuộc cho đến khi lỗi được sửa và kiểm tra lại. |
| AC-026 | Mở fixture `excel_mcp_sales_input.xlsx` và task pane | Connector nhận đúng `SalesTable`, `CommissionTable`, header/range/hash; nguồn không đổi. |
| AC-027 | Nhập prompt chuẩn trong manifest fixture | Plan có đúng bốn operation Net Revenue, Return Rate, Commission Value và Sales Rank, kèm dependency/evidence. |
| AC-028 | Xem preview nhưng chưa duyệt | Hiện before/after có nhãn `Simulated preview`; số write call bằng 0. |
| AC-029 | Duyệt đúng revision/snapshot/operations | Tạo bản copy đọc lại được, ghi công thức vào copy, Excel calculate và kết quả khớp manifest; nguồn byte-identical. |
| AC-030 | Sửa prompt hoặc workbook sau duyệt | Approval cũ bị invalidated; không tạo/apply từ revision cũ. |
| AC-031 | Tool apply thiếu token hoặc target workbook nguồn | Trả `APPROVAL_MISMATCH` hoặc `SOURCE_WRITE_FORBIDDEN`; không có override và không có write. |
| AC-032 | Excel trả lỗi công thức hoặc calculation timeout | Trạng thái `runtime_failed`, hiện target/error/remedy, giữ bản copy và không gắn `verified`. |

## 14. Rủi ro, phụ thuộc và giới hạn kỹ thuật

- Theo tài liệu Microsoft cập nhật 29/09/2026, PBIP/PBIR đã generally available nhưng tính năng phát hiện/nạp lại thay đổi ngoài Desktop vẫn ở preview; một trang tài liệu PBIR còn câu chữ preview cũ. Vì vậy cần chốt phiên bản Desktop thử nghiệm và kiểm tra schema/tập file hỗ trợ tại cổng release, không suy ra khả năng mở report chỉ từ JSON hợp lệ.
- Microsoft cho phép sửa PBIR JSON trong `definition`, nhưng một JSON hợp schema vẫn có thể làm report lỗi khi mở; Desktop validation là cổng nghiệm thu cuối cho patch PBIR.
- Microsoft nêu rõ `definition.pbir`, PBIR legacy `report.json`, `mobileState.json` và `semanticModelDiagramLayout.json` chưa hỗ trợ external editing. Các file này phải nằm ngoài allowlist ghi.
- Khi Desktop mở bản copy PBIP, thay đổi ngoài có thể ghi đè thay đổi chưa lưu; R1 yêu cầu người dùng lưu và đóng bản copy trước apply. Nếu project có `unappliedChanges.json`, cần xử lý pending changes trước khi sửa expression.
- Khi sao chép PBIP, cần giữ nguyên liên kết tương đối từ report đến semantic model. Project tham chiếu file ngoài thư mục gốc phải được phát hiện và yêu cầu người dùng xử lý trước khi apply.
- PBIP chứa metadata, không bảo đảm chứa dữ liệu import đầy đủ để chạy kiểm thử DAX offline. Kết quả runtime phụ thuộc Desktop refresh, nguồn dữ liệu và credential của người dùng.
- PBIR có thể chứa giá trị filter/slicer thực; suy luận AI và lưu vết cục bộ phải bảo vệ các giá trị này cùng mức với dữ liệu Excel.
- Tạo visual PBIR mới đòi hỏi đúng schema, tên object duy nhất, query binding và layout; JSON hợp schema vẫn cần Power BI Desktop xác nhận khả năng render. R1 chỉ phát hành các loại visual tiêu chuẩn đã có fixture và test trên phiên bản Desktop hỗ trợ.
- Calculation group và relationship có thể ảnh hưởng nhiều measure/visual; rollout sau khi impact analysis và test mẫu hoạt động ổn định.

## 15. Kế hoạch triển khai và kiểm thử

| Giai đoạn | Đầu ra | Điều kiện hoàn thành |
|---|---|---|
| P0 — Discovery/fixture | PBIP giả lập sát cấu trúc thật và bộ `.xlsx`/`.csv` tổng hợp; bảng giả định KPI/grain | Fixture có biến thể hợp lệ/lỗi; lựa chọn mục 16 được theo dõi; chưa coi fixture giả là Desktop-verified |
| P1 — Parser/profile | Inventory PBIP, profile `.xlsx`/`.csv`, schema drift, catalog model/report | AC-001/002/009/017/018 đạt trên fixture; parser đọc chứ không ghi; chưa tuyên bố runtime pass |
| P2 — Planner/generator | Business definition, typed operations, vòng AI phản biện/rủi ro, M/DAX/TMDL patch | AC-003/004/010/019–025 đạt; diff không thay file ngoài scope |
| P3 — Patch engine | Preview, backup, hash check, apply, restore | AC-005/006/007/008/012 đạt; fault injection qua từng bước ghi |
| P4 — PBIR | Binding patch, đề xuất/tạo visual mới và impact analysis | AC-011/013/014/015/016 đạt trên các Desktop version hỗ trợ |
| P5 — Pilot | Người dùng thật chạy song song với quy trình thủ công | Đo KPI mục 1 và ghi lỗi/độ lệch dữ liệu |

Bộ test cần có: Excel/CSV sai schema, CSV BOM/delimiter/encoding mơ hồ, file lớn, cột trùng tên, ngày theo locale, giá trị phần trăm 10/0,10, orphan key, phản biện AI trái dữ liệu, AI khuyên làm nhưng cổng an toàn chặn, M lỗi refresh, DAX sai filter context, nhiều report chung model, project không có Git, project có thay đổi chưa lưu, backup thiếu dung lượng, lỗi ghi giữa chừng và restore có xung đột. Phân rã công việc/test/điều kiện đạt nằm trong [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md).

## 16. Quyết định đã chốt và còn mở trước implementation

| ID | Câu hỏi | Phương án đề xuất | Vì sao quan trọng |
|---|---|---|---|
| OQ-001 — đã chốt | Dữ liệu có được gửi cho AI cloud không? | Không; phân tích và AI chạy trên máy, không gửi nội dung/metadata dự án lên AI cloud | Cần chọn runtime và cấu hình máy phù hợp |
| OQ-002 — đã chốt | Áp dụng vào bản PBIP nào? | Chỉ bản copy PBIP; bản gốc chỉ đọc | Bảo toàn project gốc và giới hạn target restore |
| OQ-003 — đã chốt | R1 có tạo biểu đồ mới theo yêu cầu người dùng không? | Có; phân tích dữ liệu, đề xuất loại biểu đồ, cho người dùng duyệt và thêm visual mới vào bản copy PBIP | Cần visual generator, layout preview và kiểm tra Desktop |
| OQ-004 — đã chốt | Những nguồn dữ liệu nào là bắt buộc? | R1 `.xlsx` và `.csv`; `.xls`, `.xlsm` và file có mật khẩu ngoài phạm vi R1 | Cần hai parser và bộ test lỗi đọc riêng |
| OQ-005 — đã chốt | Ai duyệt KPI/patch trong R1? | Chính người dùng; AI đề xuất/đánh giá, không phê duyệt | Cần phân biệt sự kiện tư vấn và quyết định người dùng |
| OQ-006 — đã chốt | Nếu AI khuyên `không nên làm` nhưng không có lỗi chặn tất định, người dùng có được tiếp tục không? | Có: hiển thị reason/rủi ro, nhận xác nhận rủi ro tường minh và làm đúng phương án người dùng chọn; phương án tối ưu của AI không tự thay thế. Nếu có lỗi chặn thì báo lỗi và không cho vượt qua. | Cần hai nhánh kiểm thử riêng: cảnh báo tư vấn và lỗi chặn |

**Phạm vi visual R1:** thêm chart/card/table tiêu chuẩn theo catalog đã kiểm thử; cập nhật measure binding của visual hiện hữu; chọn trang hiện hữu hoặc tạo trang mới khi người dùng duyệt. Việc sửa mọi chi tiết định dạng, hỗ trợ custom visual và tạo dashboard nhiều trang tự động thuộc release sau.

## 17. Tài liệu Microsoft dùng làm cơ sở kỹ thuật

- [Power BI Desktop projects (PBIP)](https://learn.microsoft.com/en-us/power-bi/developer/projects/projects-overview): cấu trúc project, giới hạn PBIX↔PBIP và external editing; trạng thái GA/preview cần đối chiếu ngày đọc từng tài liệu.
- [Edit PBIP files externally](https://learn.microsoft.com/en-us/power-bi/developer/projects/projects-external-editing): reload thay đổi, xung đột với Desktop và danh sách file chưa hỗ trợ sửa ngoài.
- [PBIR report folder](https://learn.microsoft.com/en-us/power-bi/developer/projects/projects-report): cấu trúc `definition`, JSON schema, giới hạn và lỗi khi mở lại.
- [TMDL view](https://learn.microsoft.com/en-us/power-bi/transform-model/desktop-tmdl-view): preview/apply TMDL, giới hạn refresh và tác động đến visual.
- [TmdlSerializer API](https://learn.microsoft.com/en-us/dotnet/api/microsoft.analysisservices.tabular.tmdlserializer?view=analysisservices-dotnet): parser/serializer TMDL.
- [Power Query combine files](https://learn.microsoft.com/en-us/power-query/combine-files-overview): gộp file có cấu trúc tương đồng.

---

Tài liệu này là **đặc tả đề xuất**, chưa phải baseline đã phê duyệt. Mọi giá trị mô tả sản phẩm ở đây bắt nguồn từ yêu cầu trong cuộc trao đổi; các chỉ số và lựa chọn công nghệ đánh dấu “đề xuất” cần được kiểm chứng ở P0.
