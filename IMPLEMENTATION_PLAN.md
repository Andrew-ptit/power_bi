# Kế hoạch triển khai R1 — Excel/CSV + PBIP, đề xuất và phản biện AI

> Cập nhật 04/10/2026: Người dùng đã chấp thuận nhánh Excel task pane gửi prompt + mẫu workbook có giới hạn tới OpenAI qua Codex khi bấm Phân tích. Quyết định này thay thế local-only **chỉ cho nhánh Excel Codex**, không mở quyền gửi toàn bộ workbook/PBIP hoặc các luồng khác. Lát cắt Codex read-only đã nối vào ô prompt và đọc usedRange không có Table; unit/API tests + synthetic Codex smoke đạt. Smoke đọc-chỉ với mẫu tối đa 20 dòng từ `Logistics_Data_Lab_Fulfillment.xlsx` trả 3 công thức đề xuất và 1 câu hỏi cần làm rõ; không ghi file, chưa xác minh công thức bằng Excel. Dynamic formula safety/preview-after/approval/copy/apply vẫn chưa làm, nên W-23/GX3 chưa nghiệm thu.

| Thuộc tính | Giá trị |
|---|---|
| Phiên bản | 0.5, ngày 12/10/2026 |
| Nguồn yêu cầu | `SPEC.md` v0.6; `BPMN_MODEL.md` v0.5; `EXCEL_MCP_SPEC.md` v0.1 |
| Chủ sở hữu quyết định nghiệp vụ | Người dùng khởi xướng dự án |
| Trạng thái | Kế hoạch chi tiết để review; chưa phải xác nhận nghiệm thu R1 |
| Phạm vi lượt này | Theo dõi R1 và evidence Excel add-in; không coi PBIP giả là Desktop-verified, manual Excel sideload vẫn là gate riêng |

## Tiến độ triển khai (12/10/2026)

W-02/W-03 có fixture tái lập và manifest hash. TMDL baseline đã qua `TmdlSerializer` chính thức; 8/8 JSON baseline đã qua một lượt schema Microsoft thủ công, nhưng Desktop cấp B vẫn `desktop_not_run`. W-04/W-05 đã hoàn thành importer/profile read-only cho CSV/XLSX, sheet/table selection và schema comparison. W-06 đã chốt OD-02 bằng bridge .NET cục bộ pin `Microsoft.AnalysisServices` 19.117.0; catalog và round-trip spike đạt. W-07 đã hoàn thành catalog PBIR và các cổng tĩnh; do chưa có full offline JSON Schema nên `static_patch_candidate` tách riêng và `patch_eligible: false`.

Ngày 03/10/2026, baseline trước nhánh Excel MCP đạt 98 test, 1 skip do quyền symlink; spike TMDL riêng đạt 3/3. W-04…W-07 được nghiệm thu trong phạm vi read-only. W-01/Figma v0.5 đã hoàn thành với một frame tổng quan và bốn frame W-01A…D; preflight, render findings, reflow và layout audit đều sạch. W-17A source-only UI đã có functional prototype loopback cho XLSX/CSV; browser walkthrough chưa chạy do không có phiên Browser. **G0 và G1 đã đóng trong đúng phạm vi cấu trúc/read-only đã định nghĩa**; Power BI Desktop runtime vẫn chưa chạy và thuộc G5. Ngày 04/10/2026, W-20/GX0 có spec + fixture; W-21-A…D tiếp tục có task pane prototype, connector copy/apply/calculate thật và isolated Excel 16.0 smoke. Full suite hiện đạt 118 test/1 skip; W-21-E sideload thủ công và MCP server W-22 vẫn chưa chạy.

## 1. Quyết định và ranh giới

**Đã chốt từ người dùng:** R1 nhận `.xlsx` **và** `.csv` (hai định dạng độc lập), PBIP; AI đề xuất trước; người dùng có thể duyệt hoặc phản biện/đưa phương án riêng; AI phân tích rủi ro, nêu cách tối ưu nếu nên làm, hoặc giải thích cụ thể nếu không nên làm. Nếu AI khuyên `không nên làm` nhưng không có lỗi chặn, người dùng được xác nhận rủi ro rồi **vẫn làm đúng phương án đã chọn**. Nếu có lỗi chặn, hiện lỗi và không cho vượt qua. PBIP mẫu được phép dựng từ dữ liệu giả thay vì đòi PBIP của người dùng. Xử lý/AI cục bộ; không gửi dữ liệu/metadata dự án tới AI cloud; PBIP nguồn chỉ đọc, mọi patch chỉ lên bản copy.

**Ranh giới quyết định:** AI là bên tư vấn, không phải người phê duyệt và không phải bằng chứng rằng số liệu nghiệp vụ đúng. Kết quả tư vấn có ba nhãn `nên làm`, `không nên làm`, `chưa đủ căn cứ`. Cổng chặn tất định có nhãn riêng `blocked`: truy cập bản gốc, file ngoài allowlist, schema không hỗ trợ, tham chiếu/dependency sai, hash đổi, backup thất bại. Một lời khuyên `nên làm` không vượt qua được cổng `blocked`; một lời khuyên `không nên làm` phải có reason và phương án giảm rủi ro nếu có. Xác nhận rủi ro và duyệt patch là **hai hành động tường minh khác nhau**.

**Đã chốt — OD-01 (người dùng, 02/10/2026):** khi AI khuyên `không nên làm` mà không có lỗi chặn, hệ thống hiển thị reason/rủi ro và cho người dùng xác nhận rủi ro để tiếp tục đúng phương án người dùng chọn. Không tự thay bằng phương án tối ưu. Khi có lỗi chặn, hiển thị mã lỗi, target, nguyên nhân và hướng khắc phục; không có thao tác override. Xác nhận rủi ro phải gắn với `revisionId`, `snapshotId`, đúng tập operation và actor; thay đổi một trong các yếu tố đó làm xác nhận cũ hết hiệu lực.

**Đã chốt — OD-02 (kỹ thuật, 03/10/2026):** dùng bridge .NET 8 cục bộ, package khóa `Microsoft.AnalysisServices` 19.117.0 và API `TmdlSerializer`; Python chỉ điều phối typed catalog/staging. Runtime không restore NuGet và không dùng tìm/thay text tự do. Round-trip lần hai byte-stable trên spike; writer production vẫn thuộc W-12.

**Đã chốt một phần — OD-03 (người dùng, 03/10/2026):** UI dùng web app cục bộ dạng side-panel tại `127.0.0.1`, hỗ trợ kéo/thả `.xlsx` và `.csv`, tái sử dụng parser Python. W-17A source-only dùng Python standard library, không CDN và không yêu cầu PBIP. Runtime AI cục bộ/cấu hình máy vẫn còn mở trước W-10 sau spike W-09; full W-17 chỉ nghiệm thu sau W-08…16.

**Đã chốt — OD-04 (người dùng, 03/10/2026):** bổ sung trải nghiệm trực tiếp trong Excel: workbook đang mở → side-panel prompt → connector đọc cấu trúc → local planner sinh plan/công thức → preview → user duyệt → tạo bản copy → MCP/connector ghi vào copy → Excel calculate và hiển thị kết quả. Nguồn vẫn chỉ đọc; executor cuối cùng phải qua spike Office.js/Windows helper trước khi khóa.

## 2. Quy trình mục tiêu và trạng thái

BPMN Figma v0.5 đã cập nhật ngày 03/10/2026. Frame tổng quan giữ luồng end-to-end; W-01A…D mô tả riêng: người dùng chọn **duyệt**, **phản biện**, hoặc **không áp dụng**; AI trả verdict/rủi ro/tối ưu hoặc câu hỏi còn thiếu; nhánh `không nên` cho phép giữ phương án sau risk acknowledgement riêng; hard block hiện lỗi và không có override. Không có đường tắt từ phản biện sang sinh patch. Inventory và model JSON tái tạo nằm trong `BPMN_MODEL.md`.

| Trạng thái đề xuất | Sự kiện | Cổng kiểm | Trạng thái tiếp theo |
|---|---|---|---|
| `proposed` | Người dùng đồng ý | Đã chọn operation, định nghĩa KPI đủ, nguồn hiện hành | `approved_for_preview` |
| `proposed` | Người dùng phản biện | Lưu nguyên văn ý kiến và snapshot | `assessing_revision` |
| `assessing_revision` | AI khuyên nên làm | Nêu bằng chứng, rủi ro, cách tối ưu; tạo revision mới | `awaiting_user_decision` |
| `assessing_revision` | AI khuyên không nên làm | Nêu nguyên nhân, tác động, phương án khác nếu có | `awaiting_user_decision` |
| `assessing_revision` | Thiếu căn cứ | Nêu đúng câu hỏi/dữ liệu thiếu | `needs_clarification` |
| `awaiting_user_decision` | Người dùng giữ phương án bị AI khuyên không nên | Không có hard-block; giữ nguyên operation người dùng chọn | `awaiting_risk_ack` |
| `awaiting_risk_ack` | Người dùng xác nhận đã hiểu rủi ro | Lưu `RiskAcknowledgement` theo revision/snapshot/operation | `risk_acknowledged` |
| `risk_acknowledged` | Người dùng duyệt phương án | Kiểm lại hard gate, revision và snapshot | `approved_for_preview` hoặc `blocked` |
| `awaiting_user_decision` | Người dùng chọn tối ưu của AI hoặc sửa phương án | Tạo revision mới, không kế thừa approval/risk acknowledgement | `assessing_revision` |
| `awaiting_user_decision` | Người dùng duyệt phương án được AI khuyên nên | Không có hard-block; phê duyệt tường minh | `approved_for_preview` |
| Bất kỳ trạng thái trước apply | Cổng an toàn/schema/dependency lỗi | Hiển thị mã lỗi, target, nguyên nhân, hướng khắc phục | `blocked` — không override |
| `approved_for_preview` | Sinh/kiểm tra diff | Schema, tham chiếu, allowlist, dependency | `preview_ready` hoặc `blocked` |
| `preview_ready` | Duyệt apply | Hash/backup, quyết định đúng revision | `applied_pending_desktop` hoặc `needs_rebase`/`blocked` |
| `applied_pending_desktop` | Desktop refresh/kiểm tra | Bằng chứng runtime | `verified`, `runtime_failed` hoặc `not_run` |

Phản biện có thể lặp nhưng mỗi vòng có `revisionId` mới, `parentId`, lý do thay đổi và mốc nguồn. Nếu người dùng từ chối hoặc dừng, phiên kết thúc `not_applied`; không tạo patch. `approved_for_preview` chỉ là duyệt phương án; duyệt diff/apply là một quyết định riêng. `RiskAcknowledgement` không phải approval và không thể dùng lại cho phương án khác.

#### DT-001 — Cảnh báo AI và lỗi chặn

**Điều kiện vào:** dữ liệu/quy tắc cần thiết đã đủ; verdict AI là `nên làm` hoặc `không nên làm`. Verdict `chưa đủ căn cứ` đi riêng tới `needs_clarification`, chưa xét bảng này. `Duyệt` nghĩa là phê duyệt tường minh đúng revision, snapshot và operation IDs.

**Bảng quyết định:**

| # | Hard-block? | AI khuyên không nên? | Đã xác nhận rủi ro? | Đã duyệt? | Hành động | Ghi chú |
|---|---|---|---|---|---|---|
| 1 | Y | — | — | — | Hiện lỗi và chặn sinh/apply; không override | 8 tổ hợp gộp; lỗi thắng mọi quyết định |
| 2 | N | Y | N | — | Hiện reason/rủi ro; chờ xác nhận | 2 tổ hợp gộp; nút duyệt chưa đủ |
| 3 | N | Y | Y | N | Chờ duyệt tường minh | 1 tổ hợp |
| 4 | N | Y | Y | Y | Tiếp tục **đúng phương án người dùng chọn** tới preview/kiểm tra | 1 tổ hợp; không tự áp tối ưu của AI |
| 5 | N | N | — | N | Chờ duyệt tường minh | 2 tổ hợp gộp; risk ack không cần xét |
| 6 | N | N | — | Y | Tiếp tục phương án đã duyệt tới preview/kiểm tra | 2 tổ hợp gộp |

**Kiểm đủ tổ hợp:** 2 × 2 × 2 × 2 = 16; 6 dòng bao phủ 8 + 2 + 1 + 1 + 2 + 2 = 16 tổ hợp. Dấu `—` là không xét điều kiện đó vì điều kiện ưu tiên đã quyết định hành động. **Kiểm mâu thuẫn:** không có hai dòng cùng tổ hợp điều kiện mà cho hai hành động khác nhau. Mọi nhánh “tiếp tục” vẫn phải qua static validation, preview, hash, copy/backup và duyệt apply riêng; đây không phải quyền bỏ qua bước sau.

### Hợp đồng đánh giá rủi ro AI

Mỗi kết quả có: `revisionId`, `snapshotId`, `verdict`, bằng chứng theo file/bảng/cột hoặc quy tắc đã xác nhận, giả định chưa chứng minh, rủi ro (ảnh hưởng số liệu, model, visual, hiệu năng, an toàn/khôi phục), tác động, phương án tối ưu/thay thế, lý do và thông tin còn thiếu. AI không được biến một giả thuyết thành kết luận thực tế hoặc tự tạo KPI chưa được định nghĩa. Validator tất định kiểm tra nội dung có đủ trường và tham chiếu hợp lệ trước khi hiển thị như một đề xuất có thể duyệt.

Ví dụ cần kiểm: người dùng nói “dùng cột `Sales` làm Net Sales”. Nếu chưa biết `Sales` đã trừ discount/returns hay chưa, kết quả là `chưa đủ căn cứ` hoặc `không nên làm`, chỉ rõ nguy cơ tính trùng và hỏi định nghĩa/số đối chiếu; không tự sinh measure. Nếu người dùng muốn bar chart thay line chart cho xu hướng tháng, AI có thể chấp nhận kèm tối ưu sắp xếp tháng/trục; quyết định loại chart vẫn thuộc người dùng. Nếu yêu cầu ghi PBIP gốc, validator chặn dù AI có đánh giá tích cực.

## 3. Bộ fixture tổng hợp — đủ sát để test, không giả là PBIP thật

Nguồn dữ liệu dùng 17 tên cột của CSV người dùng đã cung cấp, nhưng **không sao chép dòng thật**. Tạo `Orders_synthetic.xlsx` và `Orders_synthetic.csv` cùng dữ liệu có kiểm soát: `Completed`, `Returned`, `Cancelled`; `Quantity` âm/0/dương; `Discount` 0/5/10/30; nhiều đơn một khách, khóa sản phẩm không khớp, ngày nhiều định dạng, cột/null/schema drift theo kỳ. Bảng phụ tổng hợp `Products`, `Customers`, `Calendar` giúp kiểm tra mapping và relationship. Mỗi fixture có expected counts/totals trong manifest riêng, không suy diễn rằng `Sales` luôn là Net Sales.

PBIP giả `Retail.pbip` cần có cấu trúc gần thực tế: một `Retail.SemanticModel/definition` với database/model/table/relationship TMDL; bảng `FactOrders`, `DimProduct`, `DimCustomer`, `DimDate`, measure `[Gross Sales]` và `[Order Count]`; một `Retail.Report/definition` PBIR có version/report/page/visual JSON, visual hiện hữu dùng `[Gross Sales]`, page Overview và `definition.pbir` tham chiếu model bằng đường dẫn tương đối. Có thêm biến thể legacy, schema lạ, measure trùng, tham chiếu hỏng, file ngoài allowlist và thay đổi hash. Không chép credential, tenant ID hoặc dữ liệu nhạy cảm thật.

**Hai cấp chứng cứ bắt buộc:** (A) fixture mô phỏng vượt kiểm tra cấu trúc/schema và test tự động; (B) một PBIP được mở/lưu bằng Desktop trên máy thử nghiệm, sau đó chạy lại cùng test. Nếu chưa có cấp B, vẫn phát triển parser/planner và preview tĩnh, nhưng không tuyên bố PBIR generation “Desktop verified” hay hoàn thành R1. Tài liệu Microsoft mô tả PBIR `definition/` theo JSON schema và `definition.pbir` có tham chiếu `byPath`; schema-valid vẫn có thể lỗi khi mở Desktop.

## 4. Bảng công việc, đầu ra, test và điều kiện đạt

Mỗi W là một lát cắt riêng: tạo fixture trước, triển khai, chạy unit/negative test ngay, rồi mới sang W phụ thuộc. `T` là test **cần viết**, không phải test đã có. `AC`/`FR` tham chiếu `SPEC.md`; `N` tham chiếu BPMN.

| W / thứ tự | Phụ thuộc; BPMN/FR | Đầu ra cụ thể | Fixture và test cần viết | Điều kiện đạt để mở việc kế |
|---|---|---|---|---|
| W-00 — baseline | —; toàn luồng | Spec v0.5, plan này, OD-01/02 đã chốt; OD-03 đã chốt UI loopback, runtime AI còn mở | Kiểm link/ID FR–AC–W; rà sai lệch scope `.xlsx`/`.csv` và DT-001 | Không có FR mới thiếu W/test; điểm mở có owner/gate |
| W-01 — BPMN v0.5 | W-00; N-006/N-007 | **Hoàn thành 03/10/2026:** frame tổng quan + W-01A…D cho phản biện, verdict, risk acknowledgement, approval riêng và lỗi chặn; inventory/model JSON đã đồng bộ | Preflight và render findings 0; 58 flow reflow không thiếu; 5 layout audit đều 0 issue/style hint; so DT-001/bảng trạng thái mục 2 | Đạt trong phạm vi mô hình quy trình; không phải bằng chứng Desktop runtime |
| W-02 — fixture nguồn | W-00; N-003/FR-001,003,023 | Generator `.xlsx`/`.csv` và manifest expected counts, tổng, khóa | T-02: CSV UTF-8/BOM, dấu phẩy/chấm phẩy, quote/newline, cột thiếu/thừa, encoding lỗi; XLSX bảng, ngày/style, formula cache | Mỗi biến thể có expected result; không dùng dòng CSV thật; test tái tạo được offline |
| W-03 — fixture PBIP | W-00; N-003/FR-002 | PBIP giả cấu trúc TMDL/PBIR + biến thể legacy/lỗi; danh sách file/đường dẫn được phép | T-03: đọc JSON, relative `byPath`, schema URL/version, file không sửa; Desktop round-trip ở cổng B | Cấp A pass; ghi riêng `desktop_not_run` nếu chưa có cấp B; fixture hiện tại trong `demo_inputs` không được coi là đủ |
| W-04 — importer/profile CSV | W-02; N-003/FR-001,003,023 | Parser CSV read-only, chọn encoding/delimiter/header, profile + lỗi theo dòng | T-04: BOM, delimiter mơ hồ, dấu ngoặc kép, newline trong ô, duplicate header, lệch cột, file lớn, CSV formula-like text | Không mất/nuốt dòng lỗi; mơ hồ chặn mapping; nguồn và hash không đổi |
| W-05 — Excel profile nâng cao | W-02; N-003/FR-001,003 | Bổ sung table metadata, ngày/style và schema drift giữa nhiều file; giữ cảnh báo formula cache | T-05: ngày serial/locale, cột trùng, null, workbook rỗng/khóa/mật khẩu, 10 vs 0.10 | Kiểu ngày không bị nhận nhầm âm thầm; lỗi/giới hạn hiển thị; fixture Excel hiện có vẫn pass |
| W-06 — TMDL adapter/catalog | W-03, OD-02; N-003/FR-002,008 | Adapter parser/serializer hỗ trợ, catalog tables/columns/measures/relationships/M; read-only trước | T-06: round-trip, trùng tên, thiếu cột, relationship không hợp lệ, TMDL hỏng; so hash source | Không ghi nguồn; metadata ngoài scope giữ nguyên; parse lỗi = blocked, không regex patch |
| W-07 — PBIR catalog/schema | W-03; N-003/FR-002,017 | Đọc page/visual/binding/bookmark/filter + version/schema allowlist; legacy view-only | T-07: modern/legacy, schema lạ, binding thiếu, `definition.pbir` byPath ngoài root, file ngoài allowlist | Unsupported = view-only; không gắn `patch_eligible` khi chưa qua schema gate |
| W-17A — UI source-only prototype | W-04/05; N-002/N-003; OD-03 UI | **Hoàn thành 03/10/2026:** side-panel loopback cho upload tạm, CSV options, preview/profile/issues/schema; không PBIP/AI/write | T-17A: token/origin/path/extension/cleanup; XLSX+CSV; delimiter retry; preview opt-in; JS syntax; full regression | 7/7 web integration test và 98 test toàn suite đạt, 1 skip symlink; browser walkthrough chưa chạy do không có phiên Browser |
| W-08 — mapping/định nghĩa KPI | W-04..07; N-006/N-007/FR-004,005 | Evidence source→model; registry grain/date/discount/returns/status; quyết định người dùng | T-08: orphan ProductID, `Discount` 10 vs 0.10, đơn hủy/trả, mapping mơ hồ | Mọi KPI phụ thuộc quy tắc thiếu ở `needs_clarification`; không sinh DAX |
| W-09 — hợp đồng AI cục bộ | W-08; N-006/FR-024 | Adapter local-only + fake deterministic cho test; schema output có evidence/risk/assumptions | T-09: network disabled, model không chạy, output sai schema, tham chiếu bịa; fallback read-only | Không có payload dự án tới AI cloud; output sai bị chặn; import/profile vẫn dùng được khi AI lỗi |
| W-10 — phản biện/risk review | W-09; N-006/N-007/FR-025,026 | ProposalRevision, RiskAssessment, 3 verdict, tối ưu/reason/missing-info; audit | T-10: chấp nhận chart khác có tối ưu; phản biện Net Sales bị thiếu căn cứ; AI nói “không” có reason; lịch sử revision | Không phản hồi rỗng/không căn cứ; không sửa đề xuất gốc; không tự phê duyệt |
| W-11 — approval & hard gates | W-08,10; N-007/N-012/FR-010,026..028 | RiskAcknowledgement riêng approval; giữ nguyên operation người dùng chọn; rule engine an toàn/dependency tách AI; lỗi chặn có mã/target/reason/cách khắc phục | T-11: 16 tổ hợp DT-001; AI `không nên` + risk ack + duyệt làm đúng phương án user; thiếu ack chặn; AI `nên` nhưng path/schema sai vẫn báo error; thay revision/snapshot/operations làm ack cũ vô hiệu | Không đổi sang tối ưu AI nếu user chưa chọn; 100% hard-block không tới generator/apply; warning không bị xử lý như hard-block |
| W-12 — M/DAX/TMDL | W-06,08,11; N-008/N-009/FR-006..008 | Generator cho tập operation R1 đã hỗ trợ; TMDL staging riêng; static validation | T-12: DAX tham chiếu thiếu, tên trùng, cycle, M path quoting, serializer round-trip, object ngoài scope | Không có lỗi chặn; changed-file list đúng allowlist; chưa gắn `runtime_pass` |
| W-13 — visual PBIR | W-07,11,12; N-008/N-009/FR-016,017,020..022 | Binding update, thêm visual tiêu chuẩn đã test, page/layout plan, schema validation | T-13: line/bar/card/table, missing measure, tên trùng, trang thiếu chỗ, bookmarks/filter impact, schema lạ | Visual chỉ được sinh sau duyệt type/field/page/position; schema pass; cần cấp B trước nghiệm thu runtime |
| W-14 — preview/diff/bundle | W-12,13; N-009/N-012/FR-009,014,015 | Unified diff + tóm tắt ngữ nghĩa, data preview có nhãn, bundle manifest/decisions/checks | T-14: add/edit/delete file, không lộ raw cell trong log, bundle mở offline, diff đúng hash | Người dùng thấy toàn bộ tác động; `not_run` không hiển thị là pass; export không tự apply |
| W-15 — copy/backup | W-11,14; N-015/FR-011,012 | Preflight, so hash, tạo copy PBIP, backup + manifest/hash/read-back | T-15: thiếu dung lượng, source đổi, path traversal/symlink, byPath sau copy, quyền ghi lỗi | PBIP gốc byte-identical; chưa có write patch nếu backup/read-back không đạt |
| W-16 — apply/restore | W-15; N-018/N-019/N-031/FR-013,027,028 | Apply allowlist vào copy; kiểm lại risk ack/approval gắn cùng revision/snapshot/operations; fault injection; restore có preview/conflict | T-16: AI khuyên không + ack hợp lệ → apply đúng phương án user; ack hết hiệu lực → dừng; hard-block → error/no write; fail file thứ hai, hash sai, restore conflict, crash/retry | Test lỗi giữa chừng khôi phục copy hoặc báo chính xác trạng thái bất nhất; không bao giờ sửa gốc |
| W-17 — UI cục bộ | W-08..16, OD-03; N-002..N-025 | 6 màn hình spec, vòng phản biện, nút xác nhận rủi ro riêng và trạng thái lỗi chặn; UI không gửi dữ liệu ra cloud | T-17: walkthrough approve/revise/reject, risk ack, keyboard/error state, lỗi chặn hiện code/target/reason/remedy và không có nút vượt qua | Người dùng phân biệt AI advice, risk ack, user approval, hard error, static pass và Desktop not run; các đường lỗi quan trọng dùng được |
| W-18 — Desktop validation | W-13,16,17; N-021..N-023/FR-015,017 | Hướng dẫn mở copy, refresh, đo/check kết quả và nhập bằng chứng; lỗi/restore | T-18: load/refresh, visual render, DAX đối chiếu theo filter, lỗi runtime, copy có thay đổi chưa lưu | Chỉ `Verified` khi có bằng chứng Desktop; lỗi thành `runtime_failed`, backup vẫn dùng được |
| W-19 — pilot/đóng R1 | W-18; P5 | Chạy kịch bản mẫu đầu-cuối, ma trận truy vết, số đo thời gian và lỗi | T-19: AC-001..025, happy/negative/exception; so baseline thủ công | Tất cả AC R1 áp dụng đạt hoặc ngoại lệ được người dùng chấp thuận; không gọi R1 hoàn thành nếu thiếu Desktop gate |
| W-20 — Excel MCP spec + fixture | W-05; FR-029..036/AC-026..032 | **Nghiệm thu GX0 ngày 04/10/2026:** `EXCEL_MCP_SPEC.md`, workbook `Sales` + `Dim_Commission`, manifest prompt/formula/control totals | T-20: deterministic bytes/hash, 2 sheet/2 table, 0 source formula, parser read-only, tính lại control outputs từ business rules | 4 test fixture và full suite 102 test xanh, 1 skip symlink; chưa tính là MCP/Excel runtime pass |
| W-21 — connector spike | W-20 | **Automated/isolated slice hoàn tất 04/10/2026:** Office.js task pane, loopback HTTPS coordinator, deterministic fixture plan/preview, safe export-to-copy, allowlisted COM helper, calculate/read-back, manifest/runbook. Executor chọn: Office.js đọc/xuất workbook + Windows helper chỉ mở copy | T-21: 16 unit/API/asset tests; JavaScript/Python/PowerShell syntax; HTTPS health; isolated Excel 16.0 smoke ghi 4 cột, 6 dòng, 0 formula error, khớp manifest, source hash bất biến | W21-A…D đạt; **W21-E/manual sideload còn chờ**, nên GX1 chưa đóng. Không gọi đây là MCP server hoặc general AI planner |
| PQ-Code-M — Advanced M preview sheet rồi ghi lại nguồn | W-21 task pane; quyết định user 06–11/10/2026 | [`PQ_CODE_M_SPEC.md`](./PQ_CODE_M_SPEC.md); Excel COM chạy M trên copy tạm; Chạy thử tạo/reuse marked `PQ_Result` values-only để review nhưng không đổi source; nút/xác nhận Apply riêng ghi đúng Table hoặc toàn bộ usedRange; không backup/auto-Save | T-PQ: JS/API/unit cho marked preview reuse, fingerprint ignore-preview/detect-source-change, stale code/source, Table shrink/collision, usedRange clear-tail; package audit; Excel smoke; manual sideload/UAT | Automated slice cần xanh; **manual import/reuse preview + Table/usedRange Apply còn là gate riêng**. M tùy ý không có sandbox/rollback; partial source write phải báo chính xác |
| PQ-Typed-v2 — typed planning/validation/approval/repair | PQ-Code-M; quyết định user 08/10/2026 | Typed cards mặc định; authoritative IDs; immutable revisions; deterministic validator/lineage/compiler; Excel runtime preview; one-use approval; values-only marked result; proposal patches; API/approval tách biệt Advanced M | T-PQ2: schema/negative/golden compiler; full API lifecycle; stale/replay/forged approval; JS 0-write-before-approval; Excel 16.0 cross-check filter/add/sort, aggregate, append, merge/expand | Automated implementation và isolated runtime smoke đạt; **manual sideload Office.js write/reuse còn là exit gate**, không gọi kết quả là business Verified |
| PQ-Release-0.6 — Trusted policy + strict schema + coordinator hardening | PQ-Code-M, PQ-Typed-v2 | Policy `advanced-m-trusted-v1`; strict 15-operation/10-expression schema preflight; session TTL 30 phút/8 giờ; Codex/Excel fail-fast slots; marked temp lifecycle | T-PQ6: implementer + independent cross-review; live Codex; HTTP race/TTL/log/temp oracles; real Excel external/Typed smoke; full regression | **Automated Complete 12/10/2026:** 214 pass, 0 fail, 1 environmental symlink skip; Excel runtime 8/8; manual sideload vẫn Not run |
| PQ-Problem-Chain-P1 — linear history | PQ-Typed-v2; Wave 0 Custom XML pass 14/10/2026 | [`PROBLEM_CHAIN_SPEC.md`](./PROBLEM_CHAIN_SPEC.md); immutable root/child and `manualEdit` revisions, Custom XML persistence, CAS mutation protocol, checkout, head-bound preview/approval | T-PC1: domain/hash/CAS; fake Office.js 0/1/>1 parts; API load/problem/manual-edit/checkout/commit; blocked dependency; Save/reopen/Save As; full regression | **Automated pass:** independent cross-check 34/34, focused API/UI integration 75/75, live Codex continuation, and full Python regression **282 tests/0 fail/1 environmental skip in 394.047 s** on 17/10/2026. User reported successful Phase 1 workbook test; screenshot-level integrated sideload evidence was not retained. See [`PHASE1_CROSSCHECK.md`](./PHASE1_CROSSCHECK.md) |
| PQ-Problem-Chain-P1.1 — versioned staging/result cache and checkout restore | PQ-Problem-Chain-P1; user decision 17/10/2026 | Five FIFO confirmed display snapshots in panel plus five complete values-only results (64 MiB cap) in coordinator; changed-source checkbox increments session `dataVersion` without deleting old cache; Preview is staging and only successful Confirm/write/read-back promotes cache; checkout requires version plus HEAD/history/review hash/workbook identity/source fingerprint; no workbook-history payload | T-PC1.1: FIFO/size/identity, staging cancel/confirm, version mismatch, forgotten-checkbox fingerprint mismatch, checkout single write, managed result sheet excluded from source hash, API head binding, runtime Excel smoke, manual sideload | Prior focused Python/JS and real Excel runtime smoke passed on 17/10/2026 for the pre-version implementation. Version/staging update has **not** been retested at user request; integrated manual sideload remains Not run. Manifest unchanged. |
| PQ-Problem-Chain-P2 — branch tree, impact and explicit subtree delete | PQ-Problem-Chain-P1 | Explicit `continue`/`branch`/`editProblem` modes; `Làm tiếp` creates child, `Làm lại` creates sibling; deterministic tree UI; conservative impact report; explicit leaf/subtree deletion with parent confirmation and root protection | T-PC2: adversarial tree/CAS/source/head/edit-base/delete tests; HTTP request binding; fake Office.js confirmation oracle; live Codex/manual sideload | **Focused automated pass 18/10/2026:** domain delete/branch oracle, HTTP Phase 1/2 cross-check, fake Office.js branch/edit/delete and Excel values-only type oracles passed. Full regression was not rerun for this increment. Live Codex branch smoke and manual Excel remain Not run. |
| PQ-Typed-Step-Diagnostics — sampled checks, full selected-step run and session cache | Problem Chain P1.1; `TYPED_STEP_DIAGNOSTICS_SPEC.md` v0.2 | S0–S4 implemented: deterministic source profile/sample, selected-step prefix runner, staging/cache and task-pane UX. Diagnostic limit 100.000 rows/75 columns/1 million cells; intermediate Confirm never writes a sheet. | Focused sampler/domain/API tests and syntax checks pass. S5 full regression, Excel runtime and manual sideload intentionally not run; user is the primary manual tester. | **Implemented; manual validation pending.** Do not mark release Complete until the remaining runtime/manual gates are run. |
| W-22 — MCP contract + fake connector | W-20/21 | Tool schemas `session/snapshot/range/copy/apply/calculate/results`, envelope lỗi, in-memory fake và Inspector examples | T-22: schema/limit/token/session/unsupported tool, raw-data log capture | 100% contract test xanh; write tool không chạy nếu thiếu approval/copy |
| W-23 — prompt/plan/preview trong task pane | W-08..11, W-22 | Ô prompt, deterministic fixture planner, revision/questions/risks, operation selector, before/after simulated preview | T-23: prompt chuẩn/thiếu cột/quá dài/revision invalidation; spy write count | AC-027/028/030; preview có nhãn simulated và 0 write |
| W-24 — approval + copy + apply | W-15/16 logic, W-22/23 | Approval token, source re-hash, safe destination, copy read-back, allowlisted formula/format writer, partial-apply audit | T-24: token mismatch, source target, destination exists, protected sheet, failure injection từng operation | AC-029/031 trừ runtime value; source byte-identical; copy không ghi đè |
| W-25 — Excel calculate + runtime evidence | W-24 | Calculate timeout/cancel, read-back formula/value/error, reconciliation manifest, trạng thái verified/runtime_failed | T-25: 4 output fixture, `#N/A/#REF!`, timeout, connector disconnect | AC-029/032; chỉ đọc lại từ Excel mới được `Excel runtime verified` |
| W-26 — Excel MCP pilot | W-25 | UAT/runbook setup-cleanup, version matrix, log/privacy review, performance measurement | T-26: EX-T-01..28 áp dụng, happy/negative/exception, máy test chuẩn | Exit gate mục 11 `EXCEL_MCP_SPEC.md` đạt; không gộp với PBIP Desktop verification |

## 5. Cổng kiểm theo thứ tự

| Cổng | Điều kiện mở | Chứng cứ tối thiểu để đóng |
|---|---|---|
| G0 — scope/fixture | W-00..03 | `.xlsx` + `.csv` chốt; PBIP giả cấu trúc cấp A; BPMN v0.5 đồng bộ; OD có owner |
| G1 — read-only ingestion | W-04..07 | Test CSV/Excel/PBIP pass; lỗi đọc phân loại; không có write nguồn; AC-001/009/017/018 trong phạm vi tĩnh |
| G2 — quyết định có căn cứ | W-08..11 | User phản biện → AI có verdict/reason/optimization → risk ack riêng khi AI khuyên không → user duyệt đúng revision và đúng phương án; hard error độc lập; DT-001 và AC-003/010/019..025 |
| G3 — preview an toàn | W-12..14 | Parse/schema pass, diff/bundle đúng, không file ngoài scope; AC-004/013/015/016; runtime vẫn `not_run` |
| G4 — apply có thể phục hồi | W-15..17 | Copy+backup trước ghi, fault injection pass, original bất biến; AC-005..008/012 |
| G5 — R1 xác minh | W-18..19 | Desktop load/refresh/visual pass trên PBIP cấp B; AC-011/014 và pilot; còn lỗi thì không `Verified` |

Quy tắc tiến độ: chỉ bắt đầu W phụ thuộc khi cổng trước pass; test hiện có (`py -m unittest discover -s tests -v`) phải tiếp tục pass sau **mỗi** W; thêm test của W đó ngay trong cùng lát cắt, không dồn QA đến cuối. Ngày 12/10/2026 catalog có **214 test pass, 0 fail, 1 skip** do máy không hỗ trợ symlink. Cross-workstream focused integration đạt 82/82. Excel runtime riêng đạt 8/8, gồm external `File.Contents`, Table/usedRange, static values/error path và Typed filter/add/sort, aggregate, append, merge/expand. Live Structured Output và real `CodexTypedRunner` đạt. Các timeout Excel/Mashup của lượt 11/10 không tái hiện trong hai lượt runtime ngày 12/10. Manual sideload vẫn chưa chạy và không được suy diễn từ COM smoke, nhất là Office.js import/reuse `PQ_Result`, resize/thay Table và thay/clear-tail usedRange. W-17A được kéo sớm như prototype S1/S2 theo quyết định người dùng, không mở cổng G4 và không được hiểu là full W-17 đã hoàn thành.

### Cổng riêng cho nhánh Excel MCP

| Cổng | Work package | Điều kiện đóng |
|---|---|---|
| GX0 — spec/fixture | W-20 | Spec v0.1, workbook/manifest deterministic, parser hiện tại đọc được và nguồn không có formula |
| GX1 — connector khả thi | W-21 | Task pane bind đúng workbook; create-copy/write/calculate chạy trên disposable copy; executor decision được ghi |
| GX2 — tool an toàn | W-22 | MCP contract/fake xanh; token/session/limit/log gate đầy đủ; không arbitrary script |
| GX3 — review trước write | W-23 | Prompt → typed plan → simulated preview → approval; 0 write trước approval |
| GX4 — apply vào copy | W-24 | Source hash bất biến; copy read-back trước write; fault injection và partial state rõ |
| GX5 — Excel runtime | W-25/26 | Excel calculate/read-back khớp manifest, UAT negative pass và version máy test được ghi |

## 6. Ma trận rủi ro và quyết định cần review

| Rủi ro | Cách kiểm soát trong plan | Còn lại |
|---|---|---|
| PBIP giả không phản ánh Desktop thật | Fixture cấp A + PBIP cấp B do Desktop mở/lưu; schema pin theo file | Cần Desktop ở G5, không cần PBIP thật của người dùng |
| AI bịa field/định nghĩa hoặc đánh giá quá tự tin | Output typed, evidence phải map snapshot, giả định lộ rõ, validator tất định | Cần bộ eval nội bộ trước khi chọn runtime/model |
| CSV locale/encoding làm sai số | Preview cách đọc, lựa chọn người dùng khi mơ hồ, test BOM/quote/delimiter/decimal | Mã hóa ngoài phạm vi đã kiểm thử phải báo unsupported |
| Phản biện nhiều vòng làm duyệt sai bản | Revision/snapshot/operation IDs, risk acknowledgement và approval riêng, invalidation, audit event | OD-01 đã chốt; phải test mọi tổ hợp DT-001 trước apply |
| Patch PBIR hợp schema nhưng không render | Desktop gate cấp B, backup/restore, không gắn Verified từ test tĩnh | Không tự động hóa runtime R1; hướng dẫn/người dùng cung cấp bằng chứng |
| TMDL round-trip đổi metadata ngoài scope | Đã chọn `TmdlSerializer`; source hash/read-only và round-trip lần hai được test | Writer/staging và semantic diff vẫn phải kiểm ở W-12 |

## 7. Nguồn kỹ thuật cần đối chiếu lúc triển khai

- Microsoft: [external PBIP editing](https://learn.microsoft.com/en-us/power-bi/developer/projects/projects-external-editing) — tại 02/10/2026 ghi PBIP/PBIR GA, external reload preview và danh sách file không được sửa ngoài.
- Microsoft: [PBIR report folder](https://learn.microsoft.com/en-us/power-bi/developer/projects/projects-report) — `definition/`, `$schema`, `definition.pbir`/`byPath`, giới hạn schema-valid ≠ Desktop-valid.
- Microsoft: [TMDL overview/API](https://learn.microsoft.com/en-us/analysis-services/tmdl/tmdl-overview) — W-06 đã kiểm `TmdlSerializer` deserialize/serialize folder với package pin 19.117.0; kiểm lại khi nâng package.

Các trang tài liệu Microsoft có thể không đồng bộ câu chữ về trạng thái preview/GA; ma trận hỗ trợ của dự án phải dựa trên schema và bản Power BI Desktop thực sự test, không chỉ nhãn release trong một trang web.
