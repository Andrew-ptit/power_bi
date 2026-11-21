# Thiết kế trợ lý Supply Chain trong Excel

Ngày: 2026-11-13.

Trạng thái: người dùng đã duyệt bản minh họa luồng hỏi theo tab và xem/sửa câu trả lời. Tài liệu này tổng hợp thiết kế để duyệt phạm vi đầy đủ; chưa phải bằng chứng tính năng đã được triển khai hoặc kiểm chứng.

Cập nhật 2026-11-14: người dùng chọn hoàn thiện phần nền trước: nhập nguồn, làm sạch, hỏi/rà soát và undo/redo. KPI/domain business, đề xuất hành động nghiệp vụ và lưu/xuất/nhập quy tắc nghiệp vụ để giai đoạn sau. Sheet có sẵn trong workbook cá nhân phải tạo sheet kết quả riêng và giữ nguyên nguồn; chỉ sheet do lượt nhập trong phiên tạo ra mới có thể làm sạch trực tiếp. Kế hoạch phần 1 ở `specs/002-data-preparation/`; baseline 001 giữ nguyên.

## 1. Mục tiêu và người dùng

Người dùng đầu tiên đã biết nghiệp vụ Supply Chain/Logistics. Chủ sản phẩm vừa học, vừa phát triển công cụ thực dụng và tạo dấu ấn riêng qua xử lý dữ liệu minh bạch, dễ học cách dùng và phát hiện sai lệch nghiệp vụ.

Đầu ra mong muốn: dữ liệu sạch, bảng KPI và phần giải thích có bằng chứng, kèm hành động đề xuất để con người cân nhắc. Không tự thực hiện quyết định vận hành.

Cho phép đặt bài toán rộng, nhưng khả năng thực thi mở rộng theo từng nhóm bài toán đã kiểm chứng. OTIF là tình huống minh họa và ứng viên kiểm chứng, chưa được người dùng chốt là phạm vi nghiệp vụ duy nhất hoặc batch triển khai đầu tiên.

## 2. Cơ sở và giới hạn hiện tại

- Giao diện hiện có hai tab Trợ lý và PQ_Code-M. Trợ lý có các phần nguồn, đề bài, cách hiểu, kế hoạch A/B, chốt, ghi và record. PQ_Code-M có vòng đời Typed/Problem Chain riêng.
- Folder connector hiện chỉ append CSV cùng header thành một bảng; chưa đáp ứng nhập folder hỗn hợp thành các sheet riêng.
- Có API nhập worksheet trong luồng Advanced hiện tại, nhưng hợp đồng values-only của Advanced không phải chứng cứ giữ toàn vẹn công thức/định dạng cho tính năng mới.
- Session hiện có mặc định idle 1.800 giây và absolute 28.800 giây. Chưa có bảo đảm lịch sử hoàn tác đầy đủ như thiết kế này.
- Custom XML hiện lưu một số metadata/Problem Chain; bộ quy tắc nghiệp vụ và backup mới không được xem là đã có sẵn.
- Nguồn sở hữu hợp đồng: `docs/current/SPEC.md`, `EXCEL_MCP_SPEC.md`, `PQ_CODE_M_SPEC.md`, `PROBLEM_CHAIN_SPEC.md`, `TYPED_STEP_DIAGNOSTICS_SPEC.md`. `CURRENT_STATUS.md` sở hữu trạng thái kiểm chứng. Không nâng phiên bản hoặc đánh dấu hoàn thành từ việc duyệt mockup.

## 3. Các hướng đã thảo luận

| Quyết định | Các hướng và đánh đổi | Kết quả thảo luận |
| --- | --- | --- |
| Nhập nguồn | Append folder thành bảng; hoặc CSV/sheet XLSX thành sheet riêng trong workbook đang mở | Chọn sheet riêng; giữ công thức và định dạng XLSX |
| Chuẩn bị và phân tích | Hai trải nghiệm độc lập; hoặc một hành trình nguồn → đề bài → làm rõ → kế hoạch → kết quả | Định hướng hành trình liên tục. Chưa quyết định xóa/gộp hai tab hiện có |
| Làm sạch | Người dùng chọn thao tác trước; hoặc hệ thống quét và đề xuất để duyệt | Quét, giải thích, xem trước và duyệt |
| Độ rộng nghiệp vụ | Tổng quát ngay; hoặc mở rộng từng nhóm có kiểm chứng | Hỏi rộng, công khai đã hỗ trợ/hỗ trợ một phần/chưa hỗ trợ |
| Lưu quy tắc | Trong workbook; file riêng; hoặc đồng bộ tài khoản/cloud | Trong workbook và xuất/nhập file; chưa xây cloud |
| Câu hỏi | Danh sách dài; hỏi rời rạc; hoặc nhóm ngắn theo tab | Nhóm ngắn, hỏi từng câu, có sổ câu trả lời; prototype đã duyệt |

Không coi việc đã xem một phương án kỹ thuật là người dùng đã duyệt thay đổi stack hay mọi cơ chế nền. Dùng kiến trúc và dependency hiện có; quyết định khác phải có căn cứ khi lập kế hoạch.

## 4. Hành trình đề xuất

```text
Nhập folder vào workbook đang mở (khi cần)
  → Kiểm tra sơ bộ và chọn nguồn
  → Nhập đề bài
  → Hỏi lần lượt theo nhóm: nguồn / định nghĩa / ngoại lệ / rà soát
  → Đề xuất làm sạch và các bước giải
  → Xem trước, rà soát phạm vi và duyệt chính xác thay đổi
  → Làm sạch trên sheet đã nhập; tính và đối soát
  → Ghi kết quả đã duyệt, giải thích và đề xuất hành động
```

Người đã có dữ liệu trong workbook có thể chọn nguồn mà không nhập folder lại. Quét sơ bộ có thể chạy trước đề bài; không bắt buộc làm sạch hoàn toàn trước khi biết mục tiêu. Những sửa đổi phụ thuộc nghĩa nghiệp vụ phải chờ làm rõ. Không tạo kế hoạch sản phẩm thứ hai cạnh tranh với Spec Kit hiện có.

### 4.1 Nhập folder

- Folder có CSV và XLSX. Mỗi CSV tạo một sheet. Mỗi XLSX nhập toàn bộ sheet cùng lượt, mỗi sheet nguồn thành sheet riêng trong workbook đích đang mở.
- XLSX giữ công thức và định dạng; kiểm tra tham chiếu giữa sheet và tránh ghi đè sheet có sẵn khi tên trùng. Lưu ánh xạ file/sheet nguồn sang sheet đích để rà soát; đổi tên không được làm sai tham chiếu.
- File nguồn giữ nguyên. Sheet có sẵn không thuộc lượt nhập không được ghi đè.
- Hướng đề xuất: rà soát danh sách và tên sheet trước nút nhập. Quy tắc đặt tên cụ thể là quyết định triển khai, phải hợp lệ và ổn định, được hiện trước khi ghi.
- Import không đồng nghĩa refresh nguồn: không tự nạp lại file và ghi đè lần sau.
- Phải kiểm chứng phạm vi bảo toàn được trên host Excel mục tiêu. Nếu công thức, liên kết ngoài hoặc nội dung không được hỗ trợ khiến không thể bảo đảm yêu cầu, báo rõ và chặn phần nhập liên quan; không tự chuyển sang values-only.
- Nếu nhập bị gián đoạn, báo chính xác đã tạo sheet nào và trạng thái còn lại. Không hứa giao dịch nguyên tử hoặc tự retry khi chưa biết ghi tới đâu.

### 4.2 Chọn nguồn và làm sạch

- Từ đề bài, đề xuất sheet/bảng và khóa nối, giải thích lý do; người dùng xác nhận hoặc sửa. Không tự dùng mọi sheet.
- Quét lỗi cơ bản: ngày tháng, khoảng trắng đầu/cuối ô, số dạng chữ, dấu phân cách và mã có số 0 đầu. Báo ô thiếu, lỗi công thức và dòng nghi trùng.
- Ngày mơ hồ, quy tắc loại dòng, điền trống, xử lý trùng hoặc thay đổi có thể ảnh hưởng nghĩa phải được hỏi; không tự quyết.
- Xem trước gồm phạm vi, bước xử lý, số ô/dòng ảnh hưởng và ví dụ trước/sau.
- Người dùng đã chọn áp dụng lên chính các sheet vừa nhập. Đây là mở rộng có chủ đích so với giới hạn ghi hiện hành; hợp đồng phải được cập nhật qua workflow trước triển khai. Không áp mở rộng này cho sheet có sẵn, Typed, Advanced hoặc nguồn file.
- Đề xuất của người thiết kế: sửa các ô dữ liệu trực tiếp; công thức có kết quả bất thường thì báo, không thay công thức bằng giá trị. Cần duyệt nguyên tắc này cùng tài liệu.
- Đổi nguồn, dữ liệu hoặc quy tắc làm mất hiệu lực kế hoạch/preview/approval liên quan; không dùng kết quả cũ làm quyền ghi mới.

### 4.3 Hỏi theo tab và sửa câu trả lời

Prototype tại `.superpowers/brainstorm/651-1794586927/content/supply-chain-wizard.html` dùng dữ liệu giả lập, không kết nối Excel/AI.

- Tab được tạo theo nhóm câu hỏi của bài toán, không cố định mọi bài có bốn nhóm. Ví dụ: Nguồn → Định nghĩa KPI → Ngoại lệ → Rà soát.
- Mỗi nhóm hỏi từng câu; giữ câu trả lời khi tiến/lùi. Có sổ câu trả lời và nút xem/sửa đi thẳng tới câu tương ứng.
- Câu hỏi nêu điều chưa rõ, ảnh hưởng tới phép tính và cách bổ sung: trả lời, chọn cột hoặc cung cấp dữ liệu. Lời trả lời không thay được dữ liệu thực đang thiếu.
- Có thể xem nhóm sau để biết còn thiếu gì; không cho xác nhận/tính khi thiếu câu trả lời hoặc dữ liệu bắt buộc.
- Sửa câu trả lời giữ các lựa chọn độc lập, đánh dấu phần phụ thuộc cần rà soát và hủy quyền tính/ghi cũ. Chỉ bật lại hành động sau kiểm tra đủ điều kiện.
- Nút Quay lại/Tiếp tục là điều hướng câu hỏi. Nút ↶/↷ là hoàn tác/làm lại dữ liệu, không trộn hai nghĩa.
- Sổ câu trả lời phải dùng được trong task pane hẹp: đặt dưới câu hỏi hoặc mở trong vùng thu gọn; bố cục rộng trong mockup chỉ dùng để thử tư duy.
- Thiết kế nhãn và trạng thái keyboard/accessibility phải phù hợp giao diện hiện có, không bỏ trạng thái lỗi/busy/disclosure/approval.

### 4.4 Thông tin thiếu và ngoại lệ

- Thiếu thông tin quan trọng: dừng phần KPI liên quan, hỏi và chờ. Không tự đặt giả định để xuất kết quả.
- Nếu chỉ thiếu ở một số dòng: người dùng chọn bổ sung hoặc xác nhận loại, ghi lý do. Chưa được xác nhận thì chưa tính KPI phụ thuộc.
- Nếu loại: kết quả ghi tổng phạm vi ban đầu, số đơn/dòng bị loại, số còn đánh giá được và lý do. Không gọi KPI của tập con là KPI toàn bộ.
- Phần độc lập có thể tiếp tục kiểm tra. Không dùng lựa chọn nghiệp vụ để vượt hard blocker schema/security/dependency.

## 5. Quy tắc nghiệp vụ và kết quả

- Quy tắc đã được người dùng xác nhận được lưu trong workbook; xuất/nhập bằng file để chuyển máy hoặc dùng workbook khác. Chưa có tự đồng bộ đám mây.
- Đề xuất metadata: doanh nghiệp/phạm vi áp dụng, bài toán, định nghĩa, phiên bản và định danh. Không dùng số phiên bản đơn thuần để quyết định quy tắc đúng.
- Mỗi lần áp dụng hiện nội dung và phạm vi cho người dùng kiểm tra. Kiểm tra tương thích nguồn mới; không tự áp sang doanh nghiệp khác.
- Hai bộ khác nhau: giữ cả hai, hiển thị khác biệt và chọn bộ dùng cho lần phân tích; không tự ghi đè. Kết quả gắn với đúng bộ/phiên bản đã dùng.
- Sửa quy tắc tạo phiên bản mới thay vì đổi nghĩa của kết quả cũ. Lưu metadata vào workbook không tự gọi Save; cần nói rõ chuyển máy chỉ mang theo bản đã được Excel lưu.
- File quy tắc là dữ liệu có schema, không phải mã thực thi; định dạng/allowlist/giới hạn sẽ được chốt trong artifact hợp đồng.
- Giải thích phân biệt: phát hiện đã tính được, giả thuyết cần kiểm tra, thông tin còn thiếu. Hành động đề xuất kèm bằng chứng và điều kiện; không tự đổi quy tắc hoặc thực hiện tác vụ vận hành.
- Không kết luận báo cáo cố ý làm đẹp hoặc nguyên nhân nhân quả từ tương quan. Đối chiếu báo cáo cũ cần logic/dữ liệu báo cáo cũ.

## 6. Backup và ↶ / ↷ trong phiên

Người dùng yêu cầu thao tác ghi của add-in có backup và nút khôi phục riêng, không dựa vào Ctrl+Z. Đây là khả năng mới phải chứng minh trước khi mở thao tác ghi tương ứng; không biến thành lời hứa rollback cho các luồng hiện có.

- Bao phủ thao tác thay đổi workbook mới của luồng này: nhập sheet, làm sạch và ghi kết quả; khôi phục dữ liệu/công thức/định dạng/cấu trúc thực bị tác động. Không thay thế lịch sử Undo cho thao tác thủ công.
- Tạo và kiểm tra backup trước khi ghi. Thất bại thì không ghi; backup đơn lẻ lớn hơn toàn bộ ngân sách thì dừng trước thay đổi.
- Đóng/mở task pane vẫn giữ lịch sử khi phiên còn sống. Dữ liệu phục hồi phải do coordinator/session owner giữ ngoài vòng đời trang; lưu vùng tạm local có giới hạn dung lượng thay vì giữ không giới hạn trong JS.
- Mặc định theo session hiện có: 30 phút idle, tối đa 8 giờ. Đóng trang không tự hủy phiên; mở lại cần tái liên kết an toàn đúng workbook/phiên, không cấp lại quyền ghi cũ. Không làm yếu TTL hoặc lock hiện có.
- Hết hạn xóa backup tạm, không xóa dữ liệu đã ghi. Không bảo đảm lịch sử sau đóng Excel, crash hoặc restart coordinator; quy tắc lưu trong workbook là lớp khác.
- Giới hạn theo cả số điểm và tổng bytes; loại điểm cũ nhất khi đầy theo lựa chọn người dùng. Hiển thị số điểm còn lại và thông báo nhẹ khi loại; cắt lịch sử phải giữ chuỗi còn lại khôi phục được.
- Có làm lại sau hoàn tác. Thay đổi dữ liệu mới bằng add-in sau hoàn tác sẽ bỏ nhánh làm lại cũ. Phương án đã bị loại khỏi bộ nhớ không được hiện là khôi phục được.
- Trước hoàn tác/làm lại kiểm tra workbook identity và phần dữ liệu liên quan. Sửa tay gây xung đột thì không tự ghi đè; giữ trạng thái và hỏi. Không cho xác nhận vượt hard blocker kỹ thuật.
- Khôi phục từng bước cũng phải có read-back. Ghi/khôi phục thất bại sau khi có thể đã ghi là partial/unknown, không tự retry hoặc tuyên bố đã rollback.
- Ngân sách cụ thể, cơ chế snapshot và workbook/session rebinding là quyết định kỹ thuật phải có đo lường trong kế hoạch. Quyền chấp thuận mới cho backup không mở lại ngoại lệ Advanced vốn không hứa rollback.

## 7. Ranh giới và phần chưa triển khai

- Giữ Python stdlib, canonical module ownership, catalog Typed đóng 15 operations/10 expressions, hash/CAS/HEAD/source binding, staging và approval revision hiện hành.
- Không sửa tự do công thức/TMDL hoặc chạy mã quy tắc bên ngoài để vượt catalog. Thiếu khả năng thì báo phần hỗ trợ; không hứa mọi đề Supply Chain đều giải được.
- Nhập/làm sạch local không tự gửi dữ liệu sang AI. Luồng Analyze giữ disclosure, chỉ prompt cùng metadata được phép và tối đa 20 sample rows tổng; không gửi toàn workbook/path.
- Không tạo cloud sync, tối ưu tuyến xe, forecasting, refresh file định kỳ hoặc bộ KPI toàn ngành trong phạm vi mặc định này.
- Không đổi release metadata; không xem static/HTTP/Office.js simulation là live Excel evidence. Advanced live deferral vẫn giữ nguyên.
- Đây là dự án nhiều capability. UI mockup được duyệt không cấp chứng nhận cho runtime import, backup hoặc nghiệp vụ OTIF.

## 8. Kiểm chứng để lập kế hoạch

1. UI: tiến/lùi, xem/sửa từng câu, thiếu câu, bổ sung/loại dòng, lý do bắt buộc, trạng thái phụ thuộc và task pane hẹp. Câu trả lời sửa phải chặn quyền stale.
2. Import: fixture CSV/XLSX hỗn hợp, XLSX nhiều sheet có công thức chéo, tên trùng, sheet có sẵn và file nguồn giữ nguyên; trường hợp host không hỗ trợ và lỗi giữa lượt.
3. Cleaning: ngày mơ hồ, dấu số khác locale, khoảng trắng, mã 0 đầu, lỗi công thức; so trước/sau, approval đúng phiên bản và cập nhật đúng sheet nhập.
4. Restore: undo nhiều bước, redo, nhánh mới, quota eviction, backup quá lớn, đóng/mở task pane, TTL, source/manual edit conflict và failure injection/read-back. Kiểm tra công thức/format/cấu trúc bằng expected values độc lập.
5. Rules: workbook lưu/mở máy khác, xuất/nhập, hai phiên bản xung đột, chọn bản cho một lần, schema không hợp lệ và metadata không tự Save.
6. Analysis: chốt KPI, đúng grain, fan-out, phạm vi dòng thiếu và bằng chứng kết luận. Fixture có đáp án tính độc lập; business review không thay thế phép đối soát.

Các kiểm chứng live dùng synthetic harness, không dùng workbook người dùng làm fixture. Thiếu Excel/Codex/auth ghi Blocked/Not run và tiếp tục phần độc lập. Không chuyển nhiệm vụ kiểm chứng của người triển khai cho người dùng.

## 9. Bước tiếp theo sau duyệt tài liệu

Dùng `writing-plans` để xác định batch có phụ thuộc, rồi đưa requirements/plan/tasks vào Spec Kit theo workflow hiện có; đối chiếu `specs/001-business-assurance-baseline` trước, không thay hay nhân đôi baseline. Chọn feature artifact phù hợp cho capability mới, giữ ID/tiêu chí/evidence của việc đang có.

Thứ tự dự kiến cần được đánh giá trong kế hoạch: nền session/backup và khả năng nhập giữ công thức trước khi cho ghi; wizard có thể xây và kiểm tra độc lập với runtime còn Blocked. Không coi đây là lịch triển khai đã duyệt.

## 10. Kết quả rà soát khả năng lập kế hoạch

Reviewer độc lập đã đọc thiết kế. Quyết định còn lại đã được người dùng giải quyết: phần 1 nghiệm thu tới nhập/làm sạch/wizard và undo/redo; phân tích nghiệp vụ để sau. OTIF không thuộc tiêu chí nghiệm thu phần 1, không giao builder tự chọn thêm nghiệp vụ.

Không có câu hỏi sản phẩm quan trọng khác từ vòng rà soát này. Quota/cơ chế backup vẫn là quyết định kỹ thuật trong kế hoạch, không phải khả năng đã được chứng minh.
# Approved source-entry correction — 2026-11-14

The user approved the concrete first screen: compact `Book1 · Chưa có dữ liệu`, a single journey `1. Nguồn → 2. Làm sạch → 3. Đề bài`, and exactly two primary source actions `[Chọn thư mục] [Dùng dữ liệu trong workbook]`. Replace the stacked legacy source form in the main experience. Existing workbook metadata becomes collapsed detail; successful connection is not labelled successful data ingestion. Native folder selection is local and authenticated; cancellation is harmless. Empty workbooks cannot advance to cleaning. Existing cleaning controls are shown only after choosing workbook data, and business entry remains gated by an actual available source. Raw paths, Sheet/Table/Pattern fields and engine revision labels do not belong on the first screen. Existing legacy handlers remain compatibility internals. Folder inventory is read-only until import exists; selecting a directory must not pretend CSV-to-sheet import has happened. Existing native write/recovery gates are unchanged.
