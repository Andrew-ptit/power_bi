# Feature specification: bước Hiểu dữ liệu và sơ đồ quan hệ

**Feature**: `004-understand-data-step`. **Created**: 2026-11-21 (Asia/Saigon).
**Status**: Draft — phạm vi đã được người dùng duyệt ở bản thiết kế; spec/plan/tasks chờ người dùng xem. **Chưa sẵn sàng giao agent code** cho tới khi T400 pass (xem §10).
**Input**: [bản thiết kế 2026-11-21](../../docs/superpowers/specs/2026-11-21-understand-and-suggest-design.md) mục 5.1 và 9.1 (đợt Đ1); mockup tĩnh `.superpowers/brainstorm/1590-1795275786/content/flow-overview-v4.html`.
**Git**: không reset/stash/checkout toàn repo; không đổi release metadata.
**ID**: `H*` (yêu cầu), `HS*` (kịch bản), `HC*` (tiêu chí) là alias feature-local; không cấp lại FR/AF/SI/DP của tài liệu khác. Task `T400–T408`. Rà soát lần 2 ngày 2026-11-22 trên nhánh `integration/source-import-003`: thêm P8, P9, H19–H21, US6, HC09.

## 1. Vấn đề hiện tại (bằng chứng trong code, đọc ngày 2026-11-21 trên `main` bf26fda + working tree)

| # | Hiện trạng | Hệ quả với người dùng |
|---|---|---|
| P1 | Nút `flow-analyze-button` nằm trong thẻ đề bài và bị khóa khi ô đề bài rỗng; nó gọi `flowUnderstand` → `POST /api/assistant/understand` | Phải gõ đề bài trước rồi mới thấy cấu trúc dữ liệu |
| P2 | `POST /api/assistant/understand` nhận body rỗng; `AssistantSessionStore.understand` chỉ cần stage `ingested` | Đo cấu trúc chạy được trước đề bài, không cần đổi API |
| P3 | Kết quả hiểu gồm `roles`, `relationships`, `assumptions`, `warnings`; `_HASH_BASIS` là danh sách đóng. Khóa ứng viên (`key_report`) và nghĩa cột (`column_roles`) được tính nhưng không trả ra | Không đủ dữ liệu để vẽ "sheet có cột gì, nối bằng cột nào" |
| P4 | Khi không tìm thấy bảng fact, store trả `roles: []` và vẫn sang stage `understood` | Engine không chặn, nhưng UI không có cách trình bày riêng |
| P5 | `_questions` sinh câu hỏi xác nhận quan hệ (`Xác nhận`/`Không nối`/`Cần làm rõ`), vai trò (`Đúng`/`Cần sửa`), cảnh báo, giả định; câu trả lời vào request lập kế hoạch | Cơ chế xác nhận đã có; chỉ đang hiển thị sai chỗ (sau đề bài) |
| P6 | Thẻ `flow-understand-section` đứng sau thẻ đề bài, thu gọn, quan hệ là danh sách chữ | Không trực quan; không thấy cột nối |
| P7 | Feature 003 rút hành trình còn `1. Nguồn → 2. Đề bài` | Thiếu nhịp hiểu dữ liệu giữa nhập và đề bài |
| P8 | `preparationBusinessHandoff` (`taskpane_flow.js`) nạp nguồn ở chế độ `discover`: mỗi sheet chỉ gửi tối đa 20 dòng mẫu (`flowSampleOrdinals`). `understand` đo khóa, quan hệ, orphan, nhân dòng trên đúng các dòng mẫu đó. Bước quét của 003 đã đọc toàn bộ dòng vào task pane; store cho phép nạp `compute` ngay từ lần đầu | Với bảng lớn, mẫu 20 dòng của hai bảng hầu như không trùng khóa nhau, nên quan hệ đo ra thiếu hoặc sai. Sơ đồ vẽ trên số đo đó sẽ gây hiểu nhầm |
| P9 | `flowWorkbookCell` đổi ô số có numberFormat ngày thành chuỗi ngày ISO trước khi gửi (rà 2026-11-22) | Phép thử ngày ISO của engine dùng được cho sheet do 003 nhập; rủi ro "ngày dạng serial" nêu ở bản trước không còn là điểm chặn, chỉ cần xác nhận lại ở T400 |

## 2. Quyết định người dùng đã duyệt (2026-11-21)

| # | Quyết định |
|---|---|
| D1 | Thêm bước `Hiểu dữ liệu` giữa `Nguồn` và `Đề bài`. Hành trình: `1. Nguồn → 2. Hiểu dữ liệu → 3. Đề bài`. |
| D2 | Quan hệ giữa các sheet hiển thị dạng nối dây như Model view của Power BI: mỗi sheet có danh sách cột, dây nối từ cột khóa sang cột khóa. |
| D3 | Nút `Mở rộng` mở một cửa sổ riêng, bố cục 1 : 3 (danh sách : sơ đồ). |
| D4 | Triển khai bước Hiểu và sơ đồ trước. Quyền đọc giá trị, gộp nhóm, gợi ý đề bài làm sau. Danh mục bài toán hoãn (`[HOÃN-K]`). |

## 3. Phạm vi

**Trong phạm vi**

- Khung nhìn dẫn xuất `modelView` do engine tính: bảng, cột, khóa, loại bảng, quan hệ kèm số đo, cảnh báo.
- Phân loại bảng `event` / `snapshot` / `unknown` bằng số đo, và câu hỏi xác nhận cho bảng được đề xuất là `snapshot`.
- Bước `2. Hiểu dữ liệu` trong task pane: tổng quan, danh sách sheet, quan hệ (danh sách và sơ đồ), cảnh báo, chế độ từng sheet.
- Xác nhận/từ chối đề xuất ngay trên bước Hiểu bằng cơ chế câu hỏi/câu trả lời hiện có.
- Sơ đồ nối dây trong task pane (một sheet và hàng xóm) và cửa sổ mở rộng 1 : 3 (mọi sheet).
- Cập nhật owner docs và acceptance matrix.

**Ngoài phạm vi**

- Mọi lời gọi AI/Codex mới. Feature này không gửi thêm bất cứ dữ liệu nào ra ngoài.
- Quyền đọc giá trị (phần Q), gộp nhóm và sheet quy đổi (phần N), gợi ý đề bài (phần G): feature sau.
- Mọi mục `[HOÃN-K]` trong sổ việc hoãn của bản thiết kế (mục 9.2), gồm nghĩa cột riêng cho Supply Chain.
- Người dùng tự thêm quan hệ, đổi vai trò bảng sang giá trị khác, gán nghĩa cột, kéo thả dây. Feature này chỉ xác nhận/từ chối đề xuất đã đo.
- Thay đổi `understand`/`understandHash`, Domain Pack, Brief, Spec, Record, Typed, Problem Chain, Advanced M, PBIP.
- Thay đổi bước Nguồn của 003 và backend preparation.
- Đổi manifest, version, dependency.

## 4. User Scenarios & Testing

### US1 — Thấy bức tranh dữ liệu trước khi đặt đề bài (P1)

Sau khi nguồn được xác minh, task pane tự đo cấu trúc và mở bước `2. Hiểu dữ liệu`. Người dùng thấy có bao nhiêu sheet, sheet nào là bảng giao dịch hay danh mục, mỗi dòng ứng với khóa nào, và những gì cần họ xác nhận.

**Independent test**: fixture `tp-sales` (5 bảng) → bước Hiểu hiện đúng số bảng, đúng vai trò và khóa theo oracle độc lập; ô đề bài chưa được nhập ký tự nào; không có request nào tới route Codex.

- **HS01** Nguồn xác minh xong → tự gọi đo cấu trúc → bước `2. Hiểu dữ liệu` hiện tổng quan; không cần đề bài.
- **HS02** Mỗi sheet hiện: tên, vai trò đề xuất, số dòng, khóa ("Mỗi dòng ứng với một `<cột khóa>`" hoặc "Chưa tìm thấy khóa duy nhất"). Không suy diễn tên nghiệp vụ từ tên cột.
- **HS03** Tổng quan đếm đúng: số bảng theo vai trò, số quan hệ, số mục cần xác nhận, số cảnh báo.
- **HS04** `Tiếp tục: Đề bài` bật khi đo cấu trúc đã xong trên đúng snapshot hiện tại, kể cả khi còn mục chưa xác nhận; chân trang nêu số mục còn lại.

### US2 — Xác nhận hoặc từ chối đề xuất tại chỗ (P1)

Mục cần người dùng quyết định (quan hệ nhân dòng, quan hệ có mã không khớp, bảng được đề xuất là ảnh chụp, vai trò độ tin cậy thấp) nổi bật và có nút trả lời ngay tại dòng đó.

**Independent test**: fixture có một quan hệ nhân dòng → bấm `Không nối` trên dòng quan hệ → câu trả lời tương ứng xuất hiện trong `answers` của request lập kế hoạch (dùng planner giả), đúng `questionId`.

- **HS05** Trả lời ở bước Hiểu ghi vào cùng trạng thái câu trả lời mà bước Đề bài dùng; sang bước Đề bài thấy câu đó đã được trả lời.
- **HS06** Đổi câu trả lời sau khi đã có kế hoạch làm kế hoạch/kết quả nhánh mất hiệu lực theo cơ chế hiện có; không dùng lại quyền cũ.
- **HS07** Bảng được đề xuất `snapshot` có câu hỏi xác nhận riêng; bảng `event`/`unknown` không sinh câu hỏi.

### US3 — Sơ đồ nối dây (P1)

Trong khối Quan hệ, người dùng chuyển giữa `Danh sách` và `Sơ đồ`. Sơ đồ vẽ sheet đang chọn và các sheet nối trực tiếp với nó; dây đi từ dòng cột nối bên này sang dòng cột khóa bên kia.

**Independent test**: `modelView` cố định có 8 bảng, 7 quan hệ (1 nhân dòng, 1 có orphan) → chọn `orders` → vẽ đúng 3 hàng xóm, đúng 3 dây, mỗi dây gắn đúng cặp cột; dây nhân dòng và dây orphan mang đúng lớp trạng thái; chọn một dây hiện đúng số đo.

- **HS08** Đầu dây ghi nhiều/một theo `cardinality`; ba trạng thái dây: an toàn, nhân dòng (`fanOutRisk=high`), có mã không khớp (`orphan>0`). Nhân dòng thắng orphan khi cùng xảy ra.
- **HS09** Chọn dây: tô sáng hai cột, hiện câu giải thích kèm `orphan`, `rowsBefore`, `rowsAfter`; nếu dây có câu hỏi thì hiện nút trả lời.
- **HS10** Mọi thao tác chuột có đường bàn phím tương đương; trạng thái không chỉ thể hiện bằng màu.

### US4 — Cửa sổ mở rộng 1 : 3 (P2)

Bấm `Mở rộng` mở cửa sổ riêng: cột trái liệt kê sheet và quan hệ, bên phải là sơ đồ đầy đủ mọi sheet.

**Independent test**: với Office giả hỗ trợ `DialogApi 1.2` → mở hộp thoại, nhận `modelView` qua message, chọn một quan hệ ở cột trái làm nổi dây tương ứng; trả lời trong hộp thoại gửi message về task pane và task pane cập nhật câu trả lời. Với Office giả không hỗ trợ → nút `Mở rộng` ẩn, không lỗi.

- **HS11** Hộp thoại không giữ token, không gọi coordinator, không ghi workbook; mọi quyền ở task pane.
- **HS12** Nguồn đổi hoặc `modelViewHash` đổi khi hộp thoại đang mở → hộp thoại hiện trạng thái hết hiệu lực, không nhận trả lời.

### US5 — Không dựng được mô hình (P2)

Một sheet phẳng hoặc các sheet không nối được: bước Hiểu chuyển sang chế độ từng sheet, vẫn cho đi tiếp.

**Independent test**: fixture `tp-unknown` hoặc một bảng đơn → `mode = per_sheet`, không có lỗi, mỗi sheet có số dòng/cột/khóa, quan hệ ứng viên (nếu có) hiện với overlap; `Tiếp tục: Đề bài` bật.

- **HS13** Chế độ từng sheet hiện thông báo giải thích; không gọi đó là lỗi.

### US6 — Dữ liệu lớn (P2)

**Independent test**: coordinator giả trả `AF_UNDERSTAND_LIMIT` cho lần đo `compute` → task pane nạp lại đúng một lần ở `discover`, bước Hiểu hiện cảnh báo "đo trên mẫu", mọi dây có nhãn mẫu, `Tiếp tục: Đề bài` vẫn bật.

- **HS14** Đo trên toàn bộ dữ liệu là mặc định; đường lui sang mẫu chỉ xảy ra với lỗi giới hạn, đúng một lần, và luôn được nói rõ trên màn hình.

### Edge Cases

Bảng 0 dòng; bảng > 200 cột; tên sheet/cột Unicode và dài; hai quan hệ giữa cùng một cặp bảng; quan hệ tự tham chiếu; khóa ghép 2–3 cột; bảng không có cột ngày; cột ngày có ô trống; vượt giới hạn tính toán của WL2 (lỗi rõ); đổi workbook giữa chừng; hai task pane; panel 360px; mất kết nối coordinator khi đang đo; phiên hết hạn khi hộp thoại đang mở.

## 5. Yêu cầu chức năng

- **H01** Sau khi nguồn được xác minh (nhập xong hoặc chọn dữ liệu trong workbook), task pane tự thực hiện ingest hiện có (chế độ theo H19/H20) rồi `POST /api/assistant/understand`, và mở bước `2. Hiểu dữ liệu`. Không yêu cầu đề bài. Không gọi Codex.
- **H02** Phản hồi của `understand` và `state` có thêm khóa cấp trên `modelView` theo [contracts/model-view.md](contracts/model-view.md). Đối tượng `understand` và `understandHash` không đổi một byte so với trước feature này trên mọi fixture hiện có.
- **H03** `modelView.mode` là `model` khi `understand.roles` khác rỗng, `per_sheet` khi rỗng. Chế độ `per_sheet` không phải lỗi và không chặn bước Đề bài.
- **H04** Mỗi bảng có `grainKind ∈ {event, snapshot, unknown}` theo luật ở §6. Luật tất định, chỉ dùng số đo.
- **H05** Câu hỏi xác nhận `topic: "grain"` được sinh cho bảng có `grainKind = snapshot` và vai trò không phải `dim`/`lookup`. Câu hỏi hiện có không đổi `id`.
- **H06** Bước Hiểu trình bày: tổng quan, danh sách sheet, khối Quan hệ (Danh sách | Sơ đồ), cảnh báo. Mục có câu hỏi chưa trả lời được đánh dấu "cần xác nhận" và có nút trả lời tại chỗ.
- **H07** Trả lời tại bước Hiểu dùng đúng trạng thái câu trả lời hiện có của luồng Trợ lý (cùng `questionId`, cùng chuỗi lựa chọn). Không tạo kho câu trả lời thứ hai.
- **H08** Cổng sang `3. Đề bài`: stage `understood` trên đúng snapshot hiện tại. Không bắt buộc trả lời hết.
- **H09** Nguồn đổi, thêm nguồn, đổi workbook, hoặc phiên mới: bước Hiểu và mọi thứ phụ thuộc mất hiệu lực theo cơ chế hiện có; hành trình về `1. Nguồn` hoặc đo lại, không hiển thị kết quả cũ như hiện hành.
- **H10** Ở bước Đề bài, khi kết quả hiểu còn hiệu lực thì không cần bấm nút để đo cấu trúc; danh sách câu hỏi vẫn hiển thị đầy đủ như hiện có với các câu đã trả lời ở bước Hiểu được điền sẵn.
- **H11** Sơ đồ trong task pane: một bảng trung tâm và các bảng nối trực tiếp; bảng hàng xóm chỉ hiện cột khóa và cột nối, kèm "+ N cột khác". Bộ chọn bảng trung tâm liệt kê mọi bảng.
- **H12** Bố cục sơ đồ tất định: cùng `modelView` và cùng bảng trung tâm cho cùng tọa độ. Hàm bố cục là hàm thuần, test được không cần DOM thật.
- **H13** Cửa sổ mở rộng dùng `Office.context.ui.displayDialogAsync` với trang cùng origin, truyền dữ liệu bằng `messageChild`/`messageParent`. Chỉ hiện nút khi `DialogApi 1.2` được hỗ trợ. Không đưa token hay dữ liệu vào URL.
- **H14** Mọi văn bản từ dữ liệu người dùng (tên sheet, tên cột) render bằng `textContent`; SVG dựng bằng DOM API, không nối chuỗi HTML.
- **H15** Accessibility: bàn phím đi hết danh sách/sơ đồ/hộp thoại; `aria-live` cho tiến độ và kết quả chọn; không tràn ngang ở 360px; hit target ≥ 32px; trạng thái dây có nhãn chữ.
- **H16** Không gửi dữ liệu ra ngoài máy; không log tên sheet/cột, giá trị ô, đường dẫn. `modelView` không chứa giá trị ô ngoài `dateRange` (xem contract §4).
- **H17** Giới hạn hiển thị: mỗi bảng tối đa 200 cột trong `modelView`; sơ đồ vẽ tối đa 12 cột mỗi bảng rồi gộp phần còn lại; hộp thoại từ chối payload vượt giới hạn message với thông báo rõ.
- **H19** Bước Hiểu nạp nguồn ở chế độ `compute` (toàn bộ dòng đã quét) để số đo dựa trên toàn bộ dữ liệu. `modelView.measuredOn` là `full`; mỗi bảng ghi `rowCount` (tổng số dòng) và `measuredRows` (số dòng engine đã đo). Dữ liệu chỉ tới coordinator local như ở bước tính hiện có; ngân sách gửi Codex (tối đa 20 dòng mẫu khi lập kế hoạch) không đổi.
- **H20** Khi đo trên toàn bộ dữ liệu vượt giới hạn tính toán của WL2 hoặc giới hạn request, server trả `AF_UNDERSTAND_LIMIT` (hoặc `REQUEST_LIMIT` hiện có); task pane nạp lại một lần ở chế độ `discover` và đo trên mẫu. Khi đó `measuredOn = sample`, bước Hiểu hiện cảnh báo cố định rằng khóa và quan hệ được đo trên mẫu và có thể thiếu hoặc sai, và mọi dây trong sơ đồ mang nhãn "đo trên mẫu". Không lặp lại quá một lần; lỗi khác không kích hoạt đường lui này.
- **H21** Nếu nguồn đã ở chế độ `compute` khi tới bước tính nhánh thì không yêu cầu đọc lại toàn bộ; đường đọc lại hiện có vẫn hoạt động cho trường hợp `sample`.
- **H18** Mọi hành vi mới có test tự động (Python unittest + Node taskpane script); mọi script task-pane đang có trong gate tiếp tục chạy.

## 6. Luật phân loại `grainKind` (bắt buộc, tất định)

Áp dụng cho từng bảng, dùng danh sách khóa ứng viên tối thiểu mà `key_report` đã tính (không tính lại tổ hợp) và phép thử ngày ISO đang dùng trong `assistant_roles`.

1. **Cột ngày**: cột có ≥ 95% giá trị không rỗng là ngày ISO, và có ít nhất 1 giá trị không rỗng.
2. **snapshot** khi tồn tại một khóa ứng viên duy nhất, không null, gồm ≥ 2 cột, trong đó đúng một cột là cột ngày `D`, và với `E` là các cột còn lại của khóa:
   - số giá trị khác nhau của `D` ≥ 3, và
   - ít nhất 50% tổ hợp `E` khác nhau xuất hiện ở ≥ 2 giá trị `D`.
   Nếu nhiều khóa thỏa, chọn khóa ít cột nhất, rồi theo thứ tự tên cột.
3. **event** khi không thỏa (2) và bảng có ít nhất một cột ngày.
4. **unknown** khi bảng không có cột ngày, hoặc bảng 0 dòng.
5. `grainEvidence` ghi số đo đã dùng (cột ngày, cột thực thể, số ngày khác nhau, số tổ hợp lặp/tổng) hoặc `null` khi `unknown`.
6. Ngưỡng 95%, 3 và 50% là hằng số có tên trong module và được test ở biên.

Các ngưỡng là đề xuất của người thiết kế, chưa được kiểm bằng dữ liệu thật. Kết quả luôn là đề xuất cần người dùng xác nhận (H05).

## 7. Key entities

`ModelView`, `ModelTable`, `ModelColumn`, `ModelRelationship`, `GrainEvidence`, `DiagramLayout`, `DialogMessage`. Chi tiết: [data-model.md](data-model.md); hình dạng dữ liệu: [contracts/model-view.md](contracts/model-view.md).

## 8. Success Criteria

- **HC01** `understandHash`, `snapshotHash` của TP-FIN, TP-SALES, TP-UNKNOWN và các variant bằng đúng giá trị trước feature (so trực tiếp trước/sau trong cùng lần chạy).
- **HC02** `modelView` của mỗi fixture khớp oracle viết tay độc lập (bảng, khóa, vai trò, `grainKind`, quan hệ, số đếm); chạy hai lần cho `modelViewHash` giống nhau.
- **HC03** Bước Hiểu hiện ra mà ô đề bài rỗng; trong toàn bộ bước không có request tới `/api/assistant/plan-draft` hay route Codex nào.
- **HC04** Trả lời tại bước Hiểu xuất hiện trong request lập kế hoạch với đúng `questionId`.
- **HC05** Sơ đồ: mỗi dây nối đúng cặp cột; ba trạng thái đúng; bố cục tất định; dùng được bằng bàn phím ở 360px.
- **HC06** Hộp thoại: mở/đồng bộ/đóng với Office giả; ẩn nút khi không hỗ trợ; không token trong URL hay message.
- **HC07** Chế độ `per_sheet` đi tiếp được; không lỗi.
- **HC09** Với fixture có bảng > 20 dòng, quan hệ và orphan trong `modelView` khớp oracle tính trên toàn bộ dòng (không phải trên mẫu); đường lui `sample` hiện đúng cảnh báo.
- **HC08** Gate: `py tools/run_checks.py fast` xanh (mốc 1.293 test trước feature); `runtime` và full discovery không có lỗi mới so với baseline T400; mọi script task-pane cũ cùng script mới chạy.

## 9. Supersession

- Feature 003: SI01 và SC04 ("journey đúng hai bước") được thay bằng hành trình ba bước của feature này, có ghi ngày. Phần còn lại của 003 giữ nguyên.
- `ASSISTANT_FLOW_SPEC.md` §16 (UI): vị trí thẻ cấu trúc và nút đo cấu trúc được thay; state machine không đổi.

## 10. Assumptions & open points

- **Nền chưa chốt.** Tại ngày viết, `main` có nhiều thay đổi chưa commit, feature 003 nằm ở worktree chưa merge, và người dùng đang cho một agent khác dọn lại cấu trúc (ví dụ `taskpane.js` đang được tách). Đường dẫn file trong plan/tasks là đường dẫn tại ngày viết. T400 bắt buộc đối chiếu lại trước khi code; nếu 003 chưa có trên nền thì dừng.
- Thêm câu hỏi `grain` làm đổi danh sách câu hỏi và do đó `requestHash`/`planningHash` của fixture có bảng `snapshot`. Nếu có test ghim hash cố định bị ảnh hưởng: dừng và báo, không tự sửa golden.
- Ngày trong sheet: `flowWorkbookCell` đổi serial có numberFormat ngày thành chuỗi ISO (P9). T400 xác nhận lại rằng cột ngày do 003 nhập (`yyyy-mm-dd`) tới `raw_tables` ở dạng chuỗi ISO. Chỉ dừng nếu kết quả khác.
- H19–H21 đổi một hành vi hiện có (bước đầu nạp `discover`). Đây là đề xuất của người thiết kế sau khi rà code ngày 2026-11-22, **chờ người dùng duyệt** (HANDOFF Q8). Nếu không được duyệt: giữ `discover`, `measuredOn` luôn là `sample`, và cảnh báo ở H20 luôn hiện.
- Chưa đo thời gian `understand` trên dữ liệu đầy đủ gần trần 400.000 ô. T403 ghi thời gian đo với fixture lớn tổng hợp; nếu quá chậm để dùng tương tác thì báo, không tự hạ hay nâng giới hạn.
- `DialogApi 1.2` trên Excel Desktop mục tiêu và giới hạn kích thước message chưa được kiểm chứng trong dự án. Nếu không dùng được: US4 ghi `Blocked`, phần còn lại vẫn giao.
- Windows Excel Desktop, ExcelApi ≥ 1.9 như hiện tại; không nâng manifest floor. Nếu hộp thoại buộc phải sửa manifest: dừng và hỏi người dùng.
- Mockup ghi "1 dòng = 1 đơn hàng"; spec này dùng cách nói theo cột khóa (HS02) vì tên nghiệp vụ là suy diễn chưa có căn cứ.
