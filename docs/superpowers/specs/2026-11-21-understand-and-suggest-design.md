# Thiết kế: bước Hiểu dữ liệu và gợi ý bài toán Supply Chain

Ngày: 2026-11-21 (Asia/Saigon).

Trạng thái: người dùng đã duyệt triển khai theo phạm vi ở mục 9.1 (bước Hiểu dữ liệu và sơ đồ; quyền đọc giá trị và gộp nhóm; cơ chế gợi ý) và hoãn danh mục bài toán theo mục 9.2, ngày 2026-11-21. Chưa có dòng code nào được viết cho thiết kế này. Tài liệu này không phải bằng chứng tính năng đã được triển khai hoặc kiểm chứng, và không thay đổi release metadata.

Quan hệ với tài liệu khác: nối tiếp `2026-11-13-supply-chain-assistant-design.md` (phần KPI/nghiệp vụ được để "giai đoạn sau") và feature `specs/003-source-import-redesign`. Các nguồn sở hữu hợp đồng trong `docs/current/` giữ nguyên quyền sở hữu; mọi thay đổi hợp đồng nêu ở mục 8 phải đi qua Spec Kit trước khi code.

Quy ước ghi nhận: "Người dùng quyết định" là điều người dùng đã nói trong trao đổi 2026-11-21. "Đề xuất" là lựa chọn của người thiết kế, người dùng chưa phản đối nhưng cũng chưa duyệt từng điểm; duyệt tài liệu này là duyệt các đề xuất đó.

## 1. Vấn đề và lý do

Hành trình hiện tại đi từ nhập/làm sạch thẳng tới ô đề bài. Làm sạch chỉ trả lời "từng ô có đúng kiểu không". Người dùng phải viết đề bài khi chưa biết các sheet có hình dạng gì, nối với nhau thế nào và trả lời được câu hỏi nào. Người dùng mô tả điều này là "chưa logic về mặt tư duy trong xử lý dữ liệu".

Bằng chứng trong code:

| # | Hiện trạng | Hệ quả |
|---|---|---|
| P1 | `ASSISTANT_FLOW_SPEC.md` mục 5 đặt pha `1 · Hiểu` trước pha `2 · Khung` (đề bài) | Tài liệu đã đúng thứ tự |
| P2 | `taskpane.html`: nút `flow-analyze-button` ("Đo cấu trúc và hỏi điểm chưa rõ") nằm trong thẻ đề bài; thẻ `flow-understand-section` đứng sau và thu gọn | Giao diện đặt ngược: gõ đề bài trước, thấy cấu trúc sau |
| P3 | `POST /api/assistant/understand` nhận body rỗng, không cần đề bài | Bước hiểu chạy được trước đề bài mà không đổi API |
| P4 | `assistant_roles.structural_roles` ném `ValueError` khi không có bảng lớn nhất với khóa ngoại lặp và ít nhất hai bảng đích. `AssistantSessionStore.understand` đã bắt đúng lỗi này và trả kết quả với `roles: []` (đính chính 2026-11-21 sau khi đọc store) | Engine không chặn; nhưng giao diện chưa có cách trình bày riêng cho trường hợp không có vai trò bảng |
| P8 | Kết quả hiểu chỉ gồm vai trò bảng, quan hệ, giả định, cảnh báo. Khóa ứng viên và nghĩa cột được tính (`key_report`, `column_roles`) nhưng không trả ra; `_HASH_BASIS` của kết quả hiểu là danh sách đóng | Sơ đồ cần cột và khóa của từng bảng, nên phải có một khung nhìn dẫn xuất riêng, không thêm trường vào đối tượng đã hash |
| P9 | `_questions` trong store đã sinh câu hỏi xác nhận cho quan hệ (`Xác nhận` / `Không nối` / `Cần làm rõ`), vai trò, cảnh báo, giả định; câu trả lời đi vào request lập kế hoạch và do đó vào `requestHash` | Xác nhận ở bước Hiểu có thể dùng lại đúng cơ chế câu hỏi/câu trả lời này |
| P5 | `build_understand` chỉ nhận pack `generic` hoặc `fin-pl-v1`; pack `generic` thực chất mang chữ ký bán hàng (Orders/OrderItems/Customers/Products/Territory) | Chưa có kiến thức tồn kho; chưa phân biệt bảng sự kiện và bảng ảnh chụp |
| P6 | Feature 003 (worktree `codex/source-import-003`, chưa merge) rút hành trình còn `1. Nguồn → 2. Đề bài` | Khoảng trống giữa nhập và đề bài rõ hơn |
| P7 | Ô đề bài là textarea trống, không có gợi ý | Người dùng không biết dữ liệu hỏi được gì |

## 2. Mục tiêu, ngoài phạm vi, điều phải tránh

Mục tiêu:

- Người dùng thấy và xác nhận được bức tranh dữ liệu (mỗi sheet là gì, nối ra sao, cảnh báo mức bảng) trước khi đặt đề bài.
- Ô đề bài gợi ý các bài toán bán hàng và tồn kho mà dữ liệu hiện có đủ điều kiện để hỏi, nói rõ bài toán nào thiếu gì.
- AI đề xuất thêm bài toán, hiển thị cùng chỗ, phân biệt rõ với gợi ý đã đối chiếu dữ liệu.

Ngoài phạm vi:

- Dự báo nhu cầu, tối ưu tuyến, tối ưu tồn kho, refresh định kỳ, đồng bộ cloud.
- Sinh kế hoạch Typed không qua Codex. Gợi ý chỉ điền đề bài; lập phương án A/B vẫn theo luồng hiện có.
- Mở rộng catalog Typed (vẫn đóng 15 operation / 10 expression). Thay đổi Typed, Problem Chain, PBIP, Advanced M.
- Lưu gợi ý bài toán vào workbook. Xuất/nhập quy tắc nghiệp vụ ra file và quản lý phiên bản quy tắc (vẫn là giai đoạn sau của thiết kế 13/11). Ngoại lệ duy nhất được đưa vào đây là sheet bảng quy đổi ở phần N.
- Khớp mã sản phẩm giữa các hệ thống, khớp gần đúng trên cột nhiều giá trị.
- Đổi version phát hành. Đóng các gate live đang mở (Office.js ghi thật, parity Typed-local so với M).

Điều phải tránh (làm được về kỹ thuật nhưng vẫn là thất bại):

- Gắn nhãn "đủ dữ liệu" cho bài toán mà dữ liệu hoặc engine không tính được.
- Cộng dồn số tồn kho qua các ngày như cộng doanh thu mà không cảnh báo.
- Dữ liệu trong ô rời máy mà người dùng không được báo.
- Thao tác do người dùng bấm bị từ chối vì lô gợi ý AI đang chạy nền.
- Bước hiểu dữ liệu chặn người dùng chỉ có một sheet.

## 3. Quyết định của người dùng (2026-11-21)

| # | Quyết định |
|---|---|
| U1 | Thêm nhịp "hiểu dữ liệu" giữa nhập nguồn và đặt đề bài. |
| U2 | Lĩnh vực nghiên cứu: Supply Chain, gồm bài toán bán hàng, tồn kho và ETL. Đây là bài toán đặt ra để nghiên cứu, chưa có bộ 8 sheet thật làm chuẩn. |
| U3 | Bước đề bài có AI đề xuất bài toán liên quan đến các sheet. |
| U4 | Chọn hướng kết hợp: gợi ý local theo mẫu làm nền, AI mở rộng thêm. |
| U5 | Hiển thị gợi ý ngay dưới ô nhập như gợi ý tìm kiếm, không dùng nút riêng. |
| U6 | AI gợi ý mặc định, không yêu cầu tick đồng ý. |
| U7 | Quan hệ giữa các sheet hiển thị dạng nối dây như Model view của Power BI: mỗi sheet có danh sách cột, dây nối từ cột khóa sang cột khóa. |
| U8 | Nút "Mở rộng" mở một cửa sổ riêng với bố cục 1 : 3 (danh sách : sơ đồ). |
| U9 | Sau khi nhập xong ở bước Nguồn, hỏi người dùng có cho phép AI đọc giá trị dữ liệu không. Có quyền thì bước hiểu dữ liệu hiểu kỹ hơn. |
| U10 | AI đề xuất gộp nhóm giá trị để chuẩn hóa (ví dụ shopee, shopee hỏa tốc, tiktok shop, tiktok social quy về sàn). |
| U11 | Kết quả gộp nhóm được lưu thành một sheet bảng quy đổi mới; dữ liệu gốc không đổi. |
| U12 | Chuẩn hóa tách hai tầng: sửa cách viết ở bước Hiểu dữ liệu; gộp theo nghĩa nghiệp vụ ở bước Đề bài, sau khi biết bài toán. Sheet quy đổi có thể mang nhiều cột nhóm để dùng lại. |

U6 và U9 thay đổi quy tắc hiện hành về dữ liệu gửi qua Codex; xem mục 8.

## 4. Các hướng đã cân nhắc

Nguồn gợi ý:

| Hướng | Mô tả | Đánh đổi | Kết quả |
|---|---|---|---|
| A. Theo mẫu, không AI | Danh mục bài toán mẫu khai báo dữ liệu cần có; engine đối chiếu với kết quả hiểu | Local, ổn định, không gợi ý thứ thiếu dữ liệu; chỉ có những gì viết sẵn | Làm nền |
| B. AI tự do | Gửi cấu trúc cho Codex, AI nghĩ ra bài toán | Linh hoạt; có thể gợi ý thứ dữ liệu/engine không làm được, kết quả không ổn định | Không dùng riêng |
| C. Kết hợp | A là nền; AI sinh thêm, mỗi gợi ý AI được đối chiếu tên bảng/cột | Nhiều việc hơn A | Người dùng chọn (U4) |

Cách hiển thị và gọi AI:

| Hướng | Đánh đổi | Kết quả |
|---|---|---|
| Nút "Gợi ý thêm bằng AI" | Giữ nguyên quy tắc gửi sau hành động người dùng; trải nghiệm rời rạc | Người dùng loại (U5) |
| Gọi AI theo từng phím gõ | Không khả thi: lần lập kế hoạch Codex đo được 28,458 giây; chiếm slot Codex duy nhất | Loại |
| Sinh một lô AI một lần sau bước hiểu, lưu trong phiên; gõ phím chỉ lọc local | Hiển thị tức thì; chỉ một lời gọi AI cho mỗi phiên bản hiểu dữ liệu | Chọn |

Nơi đặt kiến thức Supply Chain:

| Hướng | Đánh đổi | Kết quả |
|---|---|---|
| Thêm vào Domain Pack hiện có | Schema pack đóng (`additionalProperties: false`), `validate_pack` gắn cứng số policy theo ngành, pack tham gia hash của Brief/Record | Không chọn |
| Danh mục bài toán mẫu riêng, có schema riêng | Không đụng hash/validation hiện có; thêm một resource và một schema | Đề xuất |

## 5. Hành trình sau thay đổi

```text
1. Nguồn  →  2. Hiểu dữ liệu  →  3. Đề bài  →  (như hiện có) phương án A/B → chốt → duyệt → ghi → record
```

Thay đổi so với 003: thêm một bước ở giữa; bước Nguồn của 003 giữ nguyên. Thay đổi so với `main`: thẻ cấu trúc chuyển lên trước thẻ đề bài và trở thành một bước có cổng riêng.

### 5.1 Phần H — bước Hiểu dữ liệu

- **H01** Sau khi nguồn được xác minh (nhập xong hoặc chọn dữ liệu trong workbook), task pane tự chạy đo cấu trúc bằng `POST /api/assistant/understand` hiện có và mở bước `2. Hiểu dữ liệu`. Không cần đề bài. Không gọi AI để đo.
- **H02** Bước hiển thị, theo thứ tự: danh sách sheet với vai trò đề xuất và "một dòng là gì"; quan hệ giữa các sheet kèm cardinality và cảnh báo nhân dòng; cảnh báo mức bảng (khóa trùng, mã không khớp giữa hai bảng, phạm vi ngày của từng bảng). Mọi mục là đề xuất có số đo, không gắn "đã xác minh".
- **H03** Đường lui khi không dựng được mô hình: nếu không có bảng nào đạt tiêu chí fact, bước không báo lỗi mà chuyển sang chế độ từng sheet. Store đã trả `roles: []` cho trường hợp này (P4); phần cần làm là khung nhìn và giao diện. Mỗi sheet được mô tả độc lập (số dòng, cột, kiểu, khóa ứng viên); quan hệ ứng viên vẫn được liệt kê. Gợi ý ở mục 5.3 khi đó chỉ gồm bài toán một sheet. Kết quả của các fixture hiện có (TP-FIN, TP-SALES) phải giữ nguyên hash.
- **H04** Phân loại bảng giao dịch thành `event` (mỗi dòng là một sự kiện, cộng dồn được theo thời gian), `snapshot` (mỗi dòng là trạng thái tại một thời điểm, không cộng dồn theo thời gian) hoặc `unknown`. Phân loại dựa trên số đo: khóa ứng viên có chứa cột ngày và cùng tổ hợp thực thể lặp lại ở nhiều ngày là dấu hiệu snapshot. Kết quả luôn là đề xuất; bài toán tồn kho chỉ được coi là đủ điều kiện khi người dùng đã xác nhận phân loại.
- **H05** `[HOÃN-K]` Ánh xạ nghĩa cột cho Supply Chain (ngày đơn, số lượng, đơn giá, thành tiền, trạng thái đơn, mã sản phẩm, mã kho, số tồn...). Engine đề xuất từ kiểu dữ liệu và tên cột; đề xuất theo tên luôn cần người dùng xác nhận. Không đủ bằng chứng thì để `unknown`, không đoán.
- **H06** Người dùng sửa được vai trò bảng, phân loại event/snapshot, quan hệ dùng để nối và nghĩa cột. Mỗi lần sửa tạo một phiên bản hiểu dữ liệu mới với hash mới, không sửa snapshot nguồn. Engine hiện chỉ sinh kết quả đo; chỉnh sửa tự do của người dùng (đổi vai trò bảng, tự thêm quan hệ, gán nghĩa cột) là khả năng mới. Riêng việc xác nhận hoặc từ chối một đề xuất đã có đường đi sẵn: câu hỏi đo được và câu trả lời của store (P9). Feature 004 chỉ dùng đường có sẵn này; chỉnh sửa tự do để sau. Không tái dụng hai trường `variantOf`/`variantReason`: runtime luôn đặt chúng là null và các bước chốt/quyết định từ chối giá trị khác null.
- **H07** Cổng sang `3. Đề bài`: bước hiểu đã chạy xong trên đúng snapshot nguồn hiện tại. Không bắt buộc xác nhận từng mục; mục chưa xác nhận chỉ hạ mức gợi ý liên quan (mục 5.3). Hard blocker schema/bảo mật/phụ thuộc hiện có không bị nới.
- **H08** Nguồn đổi, hoặc người dùng thêm nguồn, làm mất hiệu lực kết quả hiểu và mọi thứ phụ thuộc (gợi ý, đề bài đã phân tích, kế hoạch, approval) theo cơ chế vô hiệu hóa hiện có.
- **H09** Nút phân tích trong thẻ đề bài không còn đo cấu trúc; nó chỉ sinh câu hỏi làm rõ cho đề bài dựa trên kết quả hiểu đã có.

- **H10** Quan hệ có hai cách xem: danh sách và sơ đồ nối dây (U7). Trong task pane 360px, sơ đồ vẽ một sheet đang chọn và các sheet nối trực tiếp với nó; sheet hàng xóm chỉ hiện cột khóa và cột nối. Dây đi từ dòng cột này sang dòng cột kia, đầu dây ghi nhiều/một, màu dây phân biệt: nối an toàn, nối sẽ nhân dòng, có mã không khớp. Chọn một dây hiện giải thích bằng lời và số đo.
- **H11** Nút "Mở rộng" mở cửa sổ riêng bố cục 1 : 3 (U8): cột trái liệt kê sheet và quan hệ, bên phải là sơ đồ đầy đủ mọi sheet với danh sách cột. Chọn ở một bên làm nổi phần tương ứng ở bên kia. Cửa sổ riêng dựa trên cơ chế hộp thoại của Office, chưa được kiểm chứng trong dự án này; add-in không tự đổi được bề rộng task pane. Nếu hộp thoại không dùng được trên host mục tiêu thì chỉ còn chế độ H10, và phải ghi `Blocked` thay vì giả lập. Cửa sổ riêng không có quyền ghi riêng: mọi sửa đổi đi qua cùng phiên và cùng cơ chế H06.
- **H12** Tạo và sửa quan hệ lượt đầu dùng nút chọn bảng/cột, không kéo thả dây. Kéo thả là mở rộng về sau.
- **H13** Chuẩn hóa tầng 1 (U12): với cột phân loại ít giá trị, engine local phát hiện các giá trị chỉ khác cách viết (hoa/thường, khoảng trắng, dấu) và báo số nhóm trùng. Bước Hiểu chỉ báo và gợi ý rằng cột có thể cần gộp nhóm khi đặt bài toán; không gọi AI và không sửa ô dữ liệu.

Phác thảo trực quan đầy đủ: `.superpowers/brainstorm/1590-1795275786/content/` (mockup tĩnh, dữ liệu giả lập, không kết nối Excel/AI).

Phác thảo ở task pane hẹp:

```text
1. Nguồn   [2. Hiểu dữ liệu]   3. Đề bài

8 sheet · 3 bảng giao dịch · 5 bảng danh mục

orders        Giao dịch (sự kiện) · 1 dòng = 1 đơn      [Sửa]
inventory     Giao dịch (ảnh chụp?) · cần xác nhận      [Xác nhận] [Sửa]
products      Danh mục · khóa: product_id               [Sửa]
...
Quan hệ (6)                                             [Xem]
  order_lines → products   nhiều-một
  orders → shipments       một-nhiều · nối sẽ nhân dòng
Cảnh báo (3)                                            [Xem]
  37 dòng order_lines có mã sản phẩm không có trong products

                                        [Tiếp tục: Đề bài]
```

### 5.2 Phần K — danh mục bài toán mẫu Supply Chain `[HOÃN-K]`

> `[HOÃN-K]` Toàn bộ phần này được giữ làm ghi chú thiết kế, không triển khai. Xem sổ việc hoãn ở mục 9.2. Danh sách ứng viên bên dưới chưa được kiểm bằng dữ liệu thật và có thể thay đổi hoàn toàn.

- **K01** Một resource dữ liệu mới có schema đóng, nạp qua `core.resources`. Là dữ liệu, không phải mã thực thi. Không thay đổi Domain Pack, hash Brief hay hash Record hiện có.
- **K02** Mỗi bài toán mẫu khai báo: mã định danh, nhóm (`sales`, `inventory`, `combined`), tiêu đề và câu đề bài tiếng Việt, dữ liệu cần có (vai trò bảng, phân loại event/snapshot, nghĩa cột bắt buộc và tùy chọn), các điểm định nghĩa cần hỏi người dùng (ví dụ đơn hủy có tính không), và quy tắc cộng dồn.
- **K03** Một bài toán mẫu chỉ được đưa vào danh mục phát hành khi có fixture tổng hợp với đáp án tính độc lập và hành trình đi hết luồng hiện có (đề bài → kế hoạch → tính local → đối soát) cho ra đúng đáp án. Bài toán không dựng được bằng 15 operation Typed thì không vào danh mục.
- **K04** Danh sách ứng viên lượt đầu (đề xuất, phải qua K03 mới được giữ):

| Nhóm | Bài toán | Ghi chú khả thi |
|---|---|---|
| sales | Doanh thu theo khách hàng / sản phẩm / tháng | group + sum; tháng qua `date.year`, `date.month` |
| sales | Số đơn và giá trị đơn trung bình theo kỳ | `countDistinct`, `safeDivide` |
| sales | Tỷ lệ đơn hủy / trả hàng | cần cột trạng thái; hỏi định nghĩa |
| sales | Xếp hạng sản phẩm theo doanh thu | chỉ sắp xếp; catalog không có phép "giữ N dòng đầu" nên không hứa "top N" |
| inventory | Tồn cuối kỳ theo kho / sản phẩm | lấy ngày lớn nhất mỗi nhóm rồi nối lại; cần xác nhận snapshot |
| inventory | Tồn bình quân theo kỳ | `average` trên snapshot, không `sum` qua ngày |
| inventory | Sản phẩm có tồn nhưng không có bán trong kỳ | `leftAnti` giữa tồn và bán |
| combined | Vòng quay tồn kho, số ngày tồn | đưa hai bảng về cùng mức sản phẩm × kỳ trước khi chia |

- **K05** Bài toán cần hiệu hai ngày (hàng chậm luân chuyển theo số ngày, giao đúng hạn theo số ngày trễ) chưa được xác nhận là dựng được: `FUNCTIONS` của Typed chỉ có `date.year/month/day`. Executor local có xử lý giá trị `timedelta`, nhưng chưa có bằng chứng compiler M và executor local cùng hỗ trợ trừ hai ngày ra số ngày. Người lập kế hoạch phải kiểm tra cả hai; nếu không được hỗ trợ thì các bài toán này bị loại khỏi lượt đầu, không mở rộng catalog để chứa chúng.
- **K06** Thứ tự: sales trước, inventory sau, combined cuối. Lý do: số liệu bán hàng cộng được và dễ có đáp án độc lập; tồn kho phụ thuộc H04.

### 5.3 Phần G — gợi ý ở bước Đề bài

- **G01** Dưới ô đề bài có danh sách gợi ý, mở sẵn khi vào bước và lọc theo nội dung đang gõ. Lọc chạy hoàn toàn trong task pane trên dữ liệu đã có; không có lời gọi mạng theo phím gõ.
- **G02** Ba nguồn hòa trong một danh sách: bài toán mẫu đã đối chiếu (K), từ vựng của dữ liệu (tên sheet, tên cột, nghĩa cột đã xác nhận, để gợi ý vế "theo kho", "theo khách hàng"), và lô gợi ý AI (G06).
- **G03** `[HOÃN-K]` Mỗi bài toán mẫu có một trong ba mức, do engine tính từ kết quả hiểu:
  - `Đủ dữ liệu`: mọi bảng/cột bắt buộc có mặt và đã được người dùng xác nhận khi cần.
  - `Cần xác nhận` hoặc `Một phần`: có dữ liệu nhưng còn mục chưa xác nhận (H04, H05), hoặc phạm vi dữ liệu không phủ hết (ví dụ bảng giao hàng bắt đầu muộn hơn bảng đơn). Dòng gợi ý nêu đúng điều còn thiếu.
  - `Chưa đủ`: thiếu bảng hoặc cột bắt buộc; nêu tên thứ còn thiếu.
- **G04** `[HOÃN-K]` Mức `Đủ dữ liệu` chỉ khẳng định dữ liệu cần có đã hiện diện. Nó không khẳng định kết quả đúng nghiệp vụ và không thay bước đối soát.
- **G05** Chọn một gợi ý chỉ điền câu đề bài vào ô nhập. Người dùng sửa được. Đề bài vẫn đi qua câu hỏi làm rõ, phương án A/B, đối soát, chốt và duyệt như hiện tại. Ô tự viết luôn dùng được.
- **G06** Lô gợi ý AI: sau khi bước hiểu hoàn tất, coordinator gọi Codex một lần ở nền để sinh tối đa 20 gợi ý. Kết quả gắn với hash của phiên bản hiểu dữ liệu; phiên bản đổi thì lô cũ bị bỏ và sinh lại.
- **G07** Dữ liệu gửi cho lô AI là một allowlist đóng: tên sheet, tên cột, kiểu và nghĩa cột đề xuất, vai trò bảng, phân loại event/snapshot, quan hệ (bảng, cột, cardinality), số dòng mỗi bảng, và mã các bài toán mẫu đã có để tránh trùng. Không gửi giá trị ô, dòng mẫu, đường dẫn, tên file gốc hay binary. Lưu ý: tên cột là nội dung dòng tiêu đề của người dùng và tên sheet có thể sinh từ tên file; thông báo ở G09 phải nói rõ điều này.
- **G08** Mỗi gợi ý AI qua schema phản hồi đóng, giới hạn độ dài, và phải tham chiếu tên bảng/cột tồn tại trong kết quả hiểu; gợi ý tham chiếu thứ không tồn tại hoặc trùng bài toán mẫu bị loại. Gợi ý AI luôn mang nhãn `AI · chưa kiểm chứng` và không bao giờ nhận mức `Đủ dữ liệu`. Hiển thị bằng `textContent`.
- **G09** Vì AI chạy mặc định (U6), bước đề bài luôn hiện một dòng trạng thái cho biết AI đang hoặc đã gợi ý từ tên sheet và tên cột, kèm công tắc tắt. Tắt thì hủy lô đang chạy, bỏ lô đã có và không gọi lại trong phiên. Đây là đề xuất tối thiểu để U6 không thành gửi âm thầm.
- **G10** Lô AI dùng slot Codex hiện có, không thêm slot thứ hai và không nới fail-fast. Khi người dùng bấm một hành động cần Codex (tạo kế hoạch, phân tích), lô gợi ý phải nhường: hành động của người dùng không được nhận `COORDINATOR_BUSY` vì lô gợi ý. Lô bị nhường được chạy lại sau nếu phiên bản hiểu còn hiệu lực. Cơ chế (hủy subprocess hay xếp ưu tiên) là quyết định của người lập kế hoạch.
- **G11** Codex không có, lỗi, quá thời gian hoặc phản hồi sai schema: danh sách chỉ còn gợi ý local, dòng trạng thái ghi "Chưa có gợi ý AI". Không hiện hộp lỗi, không chặn bước.
- **G12** Bước tạo kế hoạch A/B vẫn yêu cầu tick disclosure như hiện tại, vì bước đó gửi tối đa 20 dòng mẫu. U6 chỉ áp dụng cho lô gợi ý gửi cấu trúc.
- **G13** Accessibility: danh sách theo mẫu combobox, đi được bằng bàn phím, thông báo số gợi ý qua `aria-live`, không tràn ngang ở 360px, hit target tối thiểu 32px (cùng chuẩn với 003).

Phác thảo:

```text
Bạn muốn xử lý dữ liệu thế nào?
┌──────────────────────────────────────────────┐
│ tồn kho|                                     │
├──────────────────────────────────────────────┤
│ Tồn cuối kỳ theo kho           Đủ dữ liệu    │
│ Tồn bình quân theo tháng       Cần xác nhận  │
│   inventory là ảnh chụp theo ngày?           │
│ Tồn kho so với sức bán 30 ngày  AI · chưa KC │
│ Vòng quay tồn kho              Chưa đủ       │
│   thiếu: cột giá vốn                         │
└──────────────────────────────────────────────┘
AI đã gợi ý từ tên sheet và tên cột.  [Tắt]
```

### 5.4 Phần Q — quyền cho AI đọc giá trị

- **Q01** Sau khi nhập xong ở bước Nguồn (hoặc sau khi chọn dữ liệu trong workbook), task pane hỏi một lần cho phiên: cho phép AI đọc giá trị trong các sheet hay chỉ dùng tên sheet và tên cột. Câu hỏi nêu rõ gửi gì và không gửi gì. Không có lựa chọn mặc định ngầm: chưa trả lời được coi là không cho phép.
- **Q02** Hai mức dữ liệu qua Codex:

| Mức | Nội dung | Điều kiện |
|---|---|---|
| Cấu trúc | Allowlist ở G07 | Mặc định (U6), có công tắc tắt (G09) |
| Giá trị | Thêm danh sách giá trị khác nhau kèm số lần xuất hiện của các cột phân loại ít giá trị | Chỉ khi người dùng cho phép ở Q01 |

- **Q03** Mức giá trị không gửi nguyên dòng, không gửi cột có nhiều giá trị khác nhau (mã, tên, số điện thoại, số tiền), không gửi đường dẫn hay binary. Ngưỡng "ít giá trị", độ dài tối đa mỗi giá trị và tổng dung lượng là giới hạn đóng do người lập kế hoạch chốt và nằm trong trần request hiện có (512 KiB). Đề xuất khởi điểm: tối đa 50 giá trị khác nhau mỗi cột.
- **Q04** Quyền gắn với phiên và workbook hiện tại, không lưu vào workbook, không tự cấp lại khi mở phiên mới. Người dùng thu hồi được bất cứ lúc nào; thu hồi hủy lời gọi đang chạy và bỏ kết quả AI dựa trên giá trị chưa được người dùng chấp nhận.
- **Q05** Không có quyền: mọi thứ local vẫn chạy (đo cấu trúc, H13, gợi ý local); gộp nhóm tầng 2 do người dùng tự làm bằng tay trong cùng giao diện.
- **Q06** `[HOÃN-K]` Đề xuất, cần duyệt riêng: khi đã cho phép ở Q01, bỏ ô tick disclosure ở bước tạo kế hoạch A/B (bước đó gửi tối đa 20 dòng mẫu) để không hỏi hai lần. Nếu không duyệt điểm này, G12 giữ nguyên.

### 5.5 Phần N — gộp nhóm giá trị (chuẩn hóa tầng 2)

- **N01** Gộp theo nghĩa nghiệp vụ phụ thuộc bài toán, nên diễn ra ở bước Đề bài, trong phần câu hỏi làm rõ sau khi người dùng gửi đề bài (U12). Khi đề bài cần một chiều phân tích mà cột nguồn có nhiều giá trị rời rạc, task pane hiện đề xuất gộp cho đúng cột đó.
- **N02** AI đề xuất tên nhóm và giá trị thuộc nhóm. Engine kiểm tra: mọi giá trị gốc được nhắc tới phải tồn tại, mỗi giá trị thuộc đúng một nhóm trong một cách gộp, giá trị AI bỏ sót giữ nguyên là nhóm của chính nó. Số dòng mỗi nhóm do engine đếm; AI không viết số.
- **N03** Người dùng sửa được: chuyển giá trị giữa các nhóm, đổi tên nhóm, tách nhóm. Chỉ cách gộp người dùng chấp nhận mới được dùng; đề xuất của AI không tự có hiệu lực.
- **N04** Khi một giá trị thật sự mơ hồ và ảnh hưởng tới kết quả, hai phương án A/B hiện có thể hiện hai cách gộp kèm chênh lệch do engine tính.
- **N05** Cách gộp đã chấp nhận được ghi vào một sheet bảng quy đổi mới (U11): cột đầu là giá trị gốc, mỗi cách gộp là một cột nhóm (ví dụ `sàn`, `hình thức giao`). Dữ liệu gốc không bị sửa. Việc ghi dùng các cổng ghi hiện có (duyệt đúng phiên bản, ghi values-only, đọc lại, không tự Save, không đè sheet có sẵn); ghi không chắc chắn là partial/unknown và không tự ghi lại.
- **N06** Sheet quy đổi là một bảng danh mục bình thường đối với engine: cột giá trị gốc phải là khóa duy nhất, nối nhiều–một với cột nguồn, được đo và hiển thị trong bước Hiểu như mọi quan hệ khác. Người dùng sửa tay sheet này được; sửa tay làm đổi fingerprint nguồn và vô hiệu hóa như mọi thay đổi nguồn.
- **N07** Dùng lại: bài toán mới cần cách gộp đã có thì task pane đề nghị dùng lại cột nhóm đó, không gọi AI. Giá trị mới xuất hiện trong dữ liệu mà chưa có trong sheet quy đổi được báo là chưa phân nhóm, không tự gán.
- **N08** `[HOÃN-K]` Cột nhóm đã lưu tham gia đối chiếu gợi ý ở G03 (ví dụ "Doanh thu theo sàn" đạt `Đủ dữ liệu` khi cột `sàn` tồn tại).
- **N09** Lượt đầu chỉ áp dụng cho cột phân loại ít giá trị. Khớp mã sản phẩm giữa các hệ thống (nhiều nghìn giá trị, khớp gần đúng) nằm ngoài phạm vi.

## 6. Trạng thái và vô hiệu hóa

```text
nguồn (snapshotHash)
  └─ hiểu dữ liệu (understandHash; mỗi lần người dùng sửa = phiên bản mới)
       ├─ gợi ý local   (tính lại ngay)
       ├─ lô gợi ý AI   (bỏ, sinh lại ở nền)
       └─ đề bài đã phân tích → kế hoạch → ... (vô hiệu hóa như hiện có)
```

Gợi ý không tạo quyền nào: không approval, không permit ghi, không lưu vào workbook, không vào Decision Record. Chỉ câu đề bài cuối cùng người dùng gửi đi mới tham gia các hash hiện có.

## 7. Ràng buộc giữ nguyên

- Python runtime chỉ dùng standard library. Không thêm database, framework hay dependency runtime.
- Implementation nằm trong module canonical (`sources`, `coordinator`, `adapters/codex`, `excel_addin`); đường dẫn resource qua `core.resources`.
- Catalog Typed đóng; history bất biến, CAS, gắn HEAD/nguồn, staging, approval đúng revision.
- AI không cấp approval. Hard blocker không bị override.
- TTL phiên 30 phút idle / 8 giờ tuyệt đối; guard host/origin/token; slot fail-fast độc lập.
- Không log giá trị ô, prompt, token, đường dẫn riêng. Fixture tổng hợp; không dùng workbook người dùng làm fixture.
- Mô phỏng unit/HTTP/Office.js không phải bằng chứng live Excel.

## 8. Thay đổi hợp đồng cần duyệt trước khi code

| Tài liệu | Thay đổi |
|---|---|
| `AGENTS.md` (Product boundaries) | Hiện ghi: Excel Analyze chỉ gửi prompt và mẫu giới hạn qua Codex sau hành động của người dùng, có disclosure. Bổ sung hai điểm: (1) lô gợi ý bài toán gửi allowlist cấu trúc ở G07 mặc định, có dòng trạng thái và công tắc tắt; (2) mức giá trị ở Q02/Q03 chỉ sau khi người dùng cho phép ở Q01. Quy tắc cũ giữ nguyên cho luồng gửi dòng mẫu, trừ khi Q06 được duyệt. Bổ sung quyền ghi mới: add-in được tạo sheet bảng quy đổi (N05) qua các cổng ghi hiện có. |
| `docs/current/EXCEL_MCP_SPEC.md` | Ghi quyết định bổ sung có ngày, theo cách quyết định 04/10/2026 đã ghi. |
| `docs/current/ASSISTANT_FLOW_SPEC.md`, `TASKPANE_UI.md` | Hành trình ba bước; bước Hiểu là một bước có cổng; danh sách gợi ý. |
| `docs/current/ASSISTANT_WL2.md` | Chế độ từng sheet (H03), phân loại event/snapshot (H04), nghĩa cột Supply Chain (H05). |
| `2026-11-13-supply-chain-assistant-design.md` mục 7 | Câu "Nhập/làm sạch local không tự gửi dữ liệu sang AI" vẫn đúng cho nhập/làm sạch; thêm tham chiếu tới ngoại lệ gợi ý. |
| `specs/003-source-import-redesign` | SI01/SC04 (hành trình đúng hai bước) bị thay bằng ba bước. Ghi là supersession có ngày, không sửa lặng lẽ. |

Test đang bảo vệ ranh giới cũ (ví dụ kiểm tra `AF_DISCLOSURE_REQUIRED`, allowlist `_safe_understand`, số bước hành trình) phải được cập nhật có chủ đích cùng hợp đồng, kèm test mới cho ranh giới mới. Không gỡ test để gate xanh.

## 9. Điều kiện tiên quyết và thứ tự đề xuất

Điều kiện tiên quyết, do người dùng quyết định, không thuộc thiết kế này:

- `main` có 224 path chưa commit (toàn bộ Trợ lý v2, preparation, test, tài liệu). Cần commit trước khi merge bất cứ thứ gì.
- Feature 003 đã xong T301–T307 trên worktree, chưa merge, T308 (live) chưa chạy. Thiết kế này xây trên hành trình của 003, nên 003 cần được merge hoặc quyết định khác đi trước.

### 9.1 Phạm vi triển khai người dùng đã duyệt (2026-11-21)

Người dùng duyệt triển khai theo ba đợt và hoãn danh mục bài toán. Kế hoạch chi tiết và task ID lập bằng Spec Kit; bảng dưới là phạm vi, chưa phải lịch.

| Đợt | Nội dung | Mã yêu cầu | Phụ thuộc |
|---|---|---|---|
| Đ0 | Điều kiện tiên quyết ở trên | — | — |
| Đ1 | Bước Hiểu dữ liệu và sơ đồ nối dây: sửa hợp đồng liên quan, chế độ từng sheet, hành trình ba bước, sửa/xác nhận, vô hiệu hóa, phân loại event/snapshot, sơ đồ trong task pane, cửa sổ mở rộng 1 : 3 | H01–H04, H06–H12 | Đ0 |
| Đ2 | Quyền đọc giá trị, chuẩn hóa hai tầng, sheet quy đổi | Q01–Q05, H13, N01–N07, N09 | Đ1 |
| Đ3 | Cơ chế gợi ý dưới ô đề bài, không có danh mục bài toán: nguồn gợi ý gồm từ vựng dữ liệu, cột nhóm đã lưu và lô AI | G01, G02 (trừ bài toán mẫu), G05–G13 | Đ1; lô AI dùng adapter của Đ2 |
| Đ4 | Hồi quy đầy đủ, live Codex opt-in, live Excel tổng hợp nếu có; cập nhật `CURRENT_STATUS.md` | — | Đ1–Đ3 |

Mỗi đợt giao được và kiểm chứng được riêng; dừng sau đợt nào thì phần đã xong vẫn dùng được. Trong Đ1, việc kiểm tra khả năng mở hộp thoại trên host (H11) làm sớm vì kết quả có thể là `Blocked`.

### 9.2 Sổ việc hoãn

Quy ước nhận biết: mọi mục hoãn mang thẻ `[HOÃN-K]` ở đây và ở nơi nó được mô tả trong tài liệu. Tìm chuỗi `HOÃN-K` để liệt kê toàn bộ. Mục hoãn không được triển khai, không được tạo task, và không được tính là capability đang có. Chỉ người dùng mở lại được, bằng cách sửa bảng này.

| Thẻ | Mục | Nội dung | Lý do hoãn | Điều kiện mở lại |
|---|---|---|---|---|
| `[HOÃN-K]` | K01–K06 | Toàn bộ danh mục bài toán mẫu Supply Chain (bán hàng, tồn kho, kết hợp) | Nội dung phụ thuộc năm khoảng trống ở mục 12; chưa có dữ liệu và người dùng thật | Người dùng đã tìm hiểu nghiệp vụ và có ít nhất một bộ file thật đã ẩn danh; quyết định lại danh sách, kể cả nhóm đối soát |
| `[HOÃN-K]` | G03, G04 | Đối chiếu ba mức `Đủ dữ liệu` / `Cần xác nhận` / `Chưa đủ` cho bài toán mẫu | Không có bài toán mẫu thì không có gì để đối chiếu | Cùng K |
| `[HOÃN-K]` | N08 | Cột nhóm đã lưu làm bài toán mẫu đạt `Đủ dữ liệu` | Phụ thuộc G03 | Cùng K. Phần "cột nhóm đã lưu xuất hiện trong từ vựng gợi ý" không hoãn |
| `[HOÃN-K]` | H05 | Nghĩa cột riêng cho Supply Chain (số lượng, đơn giá, số tồn, mã kho…) | Bảng nghĩa cột do danh mục bài toán quyết định | Cùng K. Nghĩa cột chung hiện có (ngày, số tiền, khóa, chữ) vẫn hiển thị ở Đ1 |
| `[HOÃN-K]` | Q06 | Bỏ ô tick disclosure ở bước tạo kế hoạch A/B khi đã cho phép đọc giá trị | Chưa được người dùng duyệt riêng | Người dùng duyệt điểm này |
| `[HOÃN-K]` | Mục 12, khoảng trống 1–5 | Chạy lại theo kỳ, đối soát, file bẩn/xoay bảng, kết quả dạng số, giới hạn kích thước | Người dùng cần tìm hiểu thêm | Từng khoảng trống có thiết kế riêng được duyệt |

Hệ quả trong các đợt đang làm: danh sách gợi ý ở Đ3 không có dòng nào mang mức `Đủ dữ liệu`; gợi ý AI vẫn mang nhãn `AI · chưa kiểm chứng`. H04 (event/snapshot) vẫn làm ở Đ1 vì nó là một phần của việc hiểu bảng, nhưng chưa có bài toán tồn kho nào tiêu thụ nó cho tới khi K được mở lại.

## 10. Kiểm chứng

1. Hiểu dữ liệu: một sheet phẳng, các sheet rời không nối được, mô hình sao chuẩn; hash TP-FIN/TP-SALES không đổi; chạy hai lần cho cùng hash; sửa của người dùng tạo phiên bản mới và vô hiệu hóa đúng thứ phụ thuộc.
2. Event/snapshot: fixture bán hàng, fixture tồn theo ngày, fixture tồn thiếu ngày, bảng không có cột ngày (`unknown`); chưa xác nhận thì bài toán tồn kho không đạt `Đủ dữ liệu`.
3. Bài toán mẫu: mỗi bài một fixture có đáp án tính độc lập; trường hợp nối nhân dòng phải bị phát hiện bởi đối soát; tồn bình quân không được bằng tổng qua ngày.
4. Đối chiếu ba mức: thiếu cột bắt buộc, thiếu cột tùy chọn, phạm vi ngày lệch, cột chưa xác nhận; mỗi dòng nêu đúng thứ còn thiếu.
5. Danh sách gợi ý: lọc theo phím gõ không phát sinh request; bàn phím; 360px; chọn gợi ý chỉ điền ô nhập; nội dung hiển thị là text.
6. Lô AI: payload chỉ chứa allowlist (test bằng fixture có giá trị ô đánh dấu để chứng minh không lọt); phản hồi sai schema, tham chiếu cột không tồn tại, quá dài, trùng mẫu; Codex vắng/lỗi/timeout; tắt công tắc; nhường slot khi người dùng tạo kế hoạch; phiên bản hiểu đổi thì lô cũ không hiện.
7. Sơ đồ: dây nối đúng cặp cột; ba trạng thái dây; chọn dây/sheet; bàn phím thay cho thao tác chuột; cửa sổ mở rộng đồng bộ với task pane; host không mở được hộp thoại.
8. Quyền đọc giá trị: chưa trả lời và từ chối đều không gửi giá trị nào (fixture có giá trị đánh dấu); cột nhiều giá trị không bao giờ lọt; thu hồi giữa chừng; phiên mới không thừa hưởng quyền.
9. Gộp nhóm: AI nhắc giá trị không tồn tại, gán một giá trị vào hai nhóm, bỏ sót giá trị; số dòng nhóm khớp đáp án độc lập; sheet quy đổi là khóa duy nhất và nối không nhân dòng; dùng lại cột nhóm không gọi AI; giá trị mới chưa phân nhóm; tên sheet trùng; ghi lỗi giữa chừng là partial/unknown.
10. Hồi quy: `py tools/run_checks.py fast`; toàn bộ script task-pane hiện có trong gate cộng script mới; `runtime` và live Codex opt-in theo quy tắc hiện hành. Thiếu Excel/Codex ghi `Blocked` hoặc `Not run`.

## 11. Phần để người lập kế hoạch quyết định

- Tên và vị trí file danh mục bài toán, tên route mới (nếu cần) và việc đăng ký vào `route_paths.json`.
- Dấu hiệu số học chính xác và ngưỡng cho phân loại snapshot (H04); bảng từ đồng nghĩa tên cột Việt/Anh (H05).
- Cơ chế nhường slot Codex (G10) và thời gian chờ của lô AI. Transport Codex dùng chung hiện chưa có đường hủy một lời gọi đang chạy.
- Cách biểu diễn và hash phần chỉnh sửa của người dùng trên kết quả hiểu (H06), và cách nó đi vào các bước sau mà không phá các hash hiện có.
- Cách người dùng sửa quan hệ trong task pane hẹp.
- Pack `generic` hiện mang chữ ký bán hàng và `select_pack` còn được `assistant_brief.py` dùng: giữ nguyên, hay để danh mục bài toán thay vai trò đó ở luồng v2. Cần đối chiếu đường chạy thực của luồng v2 trước khi quyết định.
- Tên sheet quy đổi, marker nhận diện sheet do add-in tạo, và cách thêm cột nhóm vào sheet quy đổi đã tồn tại mà không đè nội dung người dùng đã sửa tay.
- Luồng ghi sheet quy đổi dùng đường ghi nào trong số các đường hiện có (preparation direct hay handoff của Trợ lý v2).
- Ngưỡng và giới hạn ở Q03; quy tắc so khớp cách viết ở H13.
- Công tắc tắt AI có nhớ qua các phiên hay chỉ trong phiên (đề xuất: chỉ trong phiên, vì chưa có nơi lưu tùy chọn người dùng).

## 12. Giới hạn đã biết

- Luồng ghi Office.js thật, lưu/mở lại và parity Typed-local so với M vẫn chưa kiểm chứng live. Thiết kế này không đóng các gate đó; phát hành 1.2.0 vẫn phụ thuộc chúng.
- Người dùng chưa có bộ dữ liệu Supply Chain thật làm chuẩn (U2). Fixture tổng hợp chứng minh phép tính đúng theo định nghĩa đã chọn, không chứng minh định nghĩa đó khớp thực tế một doanh nghiệp.
- Năm khoảng trống so với việc thủ công thực tế của doanh nghiệp, người dùng công nhận ngày 2026-11-21 và cần tìm hiểu thêm. Chưa có thiết kế nào cho chúng trong tài liệu này; các nhận định là phán đoán, chưa được kiểm bằng dữ liệu hay người dùng thật:
  1. Công việc lặp lại theo kỳ: chưa có cách chạy lại quy trình đã chốt trên file kỳ mới.
  2. Đối soát giữa hai nguồn (đơn hàng so với tiền sàn trả, tồn hệ thống so với kiểm kê, thu hộ so với đơn đã giao) chưa có trong danh mục bài toán.
  3. File thật có dòng tiêu đề báo cáo, tiêu đề nhiều tầng, ô gộp, dòng tổng, bảng dạng ngang; bước nhập chặn dòng lệch cột và catalog Typed không có phép xoay bảng.
  4. Số thập phân trong sheet kết quả được ghi dạng Text nên không cộng hay vẽ biểu đồ trực tiếp được.
  5. Giới hạn 100.000 dòng mỗi file thấp so với tồn kho chụp theo ngày.
- Chất lượng gợi ý AI không được bảo đảm; thiết kế chỉ bảo đảm gợi ý AI không tham chiếu thứ không tồn tại và không được trình bày như đã kiểm chứng.
