# Bàn giao source cho DeepSeek

Ngày: 22/10/2026, múi giờ Asia/Saigon. Workspace: `C:\Users\COLAIG\Downloads\power_bi`.

Đây là bản bàn giao kỹ thuật của source hiện tại. Tài liệu này không phải xác nhận đã hoàn tất tối ưu hoặc đủ điều kiện phát hành. Đọc `AGENTS.md` ở root trước khi sửa code.

## 1. Mục tiêu tiếp quản

Người dùng muốn source tinh gọn, dễ bảo trì, có ranh giới feature rõ và design pattern phù hợp. Xoá phần đã lỗi thời sau khi đối chiếu, giữ các test bảo vệ luồng hiện tại. Không tạo thêm framework, database hoặc dependency runtime Python.

Các quyết định đang có hiệu lực:

- Advanced M: tạm bỏ qua theo yêu cầu người dùng; giữ implementation hiện hữu, không tiếp tục mở rộng hoặc kiểm chứng nhánh này trong phạm vi hiện tại.
- Bỏ phạm vi annotation/name/note editor, semantic/runtime diff và persisted runtime summary. Bốn trường tương thích `name`, `note`, `annotationUpdatedAt`, `runtimeSummary` vẫn phải tồn tại và chỉ nhận null.
- Không đưa các thư mục báo cáo wave/phase, wireframe và ledger đối chiếu đã xoá trở lại source. Khi cần tra lịch sử, dùng Git.
- Add-in kiểm thử **Excel Gate** đã được gỡ khỏi developer registration/catalog; đã kiểm tra ribbon không còn nút này. Add-in chính **Reqwise-excel-mcp** được giữ. Không tự cài lại Excel Gate để làm bước mở đầu tiếp quản.
- Chưa phát hành 1.2.0. Không thay version để biểu thị một gate chưa chạy là hoàn tất.

## 2. Snapshot Git và thay đổi local

Commit code/cleanup gần nhất trước bản bàn giao:

| Commit | Nội dung |
|---|---|
| `03448f6` | Xoá báo cáo/prototype/ledger cũ; giữ tài liệu hiện hành và required-case guard |
| `8820cfc` | Sửa fingerprint nguồn bị thay đổi giả khi Office.js import sheet kết quả |

Tại thời điểm kiểm tra bàn giao, `git status --short` báo ba path modified:

- `pbip_assistant/excel_addin/taskpane.js`: byte giống HEAD.
- `tests/taskpane/taskpane_pq.js`: byte giống HEAD.
- `tools/excel_addin/manifest.xml`: khác HEAD; byte khớp `C:\AddinManifests\manifest.xml`. Đây là cấu hình có sẵn ngoài commit cleanup; không tự restore hoặc ghi đè.

SHA-256 manifest hiện tại: `9e156b065a913943ee6d5d63b2eeac92075ab9e47efde89b4fce5f2a949de8a3`.

Đọc lại Git/diff/cấu hình khi tiếp quản; snapshot này không thay thế trạng thái thực tế về sau. Không dùng `git reset --hard`, blanket checkout hoặc xoá thư mục chỉ dựa vào tên.

## 3. Sản phẩm và cấu trúc

Ứng dụng hỗ trợ xử lý local CSV/XLSX, inventory PBIP và Excel task pane. Task pane có Typed Power Query, Problem Chain, lịch sử bất biến, Preview/staging, xác nhận ghi values và cache theo phiên. MCP/pilot và PBIP patching tổng quát chưa được coi là capability hoàn tất.

| Path | Trách nhiệm |
|---|---|
| `pbip_assistant/core/` | Lỗi/hợp đồng dùng chung, snapshot giới hạn, resource resolver |
| `pbip_assistant/sources/` | CSV/XLSX, profile/schema, fingerprint và source workflows |
| `pbip_assistant/powerbi/` | PBIP/PBIR/TMDL, proposal/approval policy |
| `pbip_assistant/coordinator/` | Composition, HTTP endpoint adapters, session/slots/temp lifecycle |
| `pbip_assistant/excel/` | Connector và fixture use case Excel |
| `pbip_assistant/powerquery/typed/` | Model, validation, compiler, closed operation registry, stateful store |
| `pbip_assistant/powerquery/history/` | Document/hash, mutations, candidate/CAS/commit store |
| `pbip_assistant/powerquery/diagnostics/` | Sampling và diagnostic staging/cache |
| `pbip_assistant/powerquery/advanced/` | Advanced M hiện có; đang tạm hoãn |
| `pbip_assistant/adapters/codex/` | Planner adapters và subprocess transport dùng chung |
| `pbip_assistant/schemas/` | Schema canonical |
| `pbip_assistant/excel_addin/`, `web/` | Office.js task pane và source-only web UI |
| `tests/` | Unit/contracts/integration/journeys/taskpane/runtime/live, support và fixtures |
| `examples/` | Lệnh/dữ liệu mẫu chạy lại được; generator chỉ dùng cho test đã chuyển sang `tests/support/` |
| `tools/` | Gate runner, Excel PowerShell helper, add-in setup, TMDL bridge |
| `third_party/lucide/` | License của icon SVG đang dùng |
| `docs/current/` | Hợp đồng, kiến trúc và trạng thái hiện hành |

Flat Python modules là facade tương thích cho caller/entrypoint hiện tại. Năm JSON schema alias cũng đang được giữ cùng parity test. Không coi chúng là bản copy implementation cũ để xoá ngay; kiểm tra caller và tiến trình đang chạy trước khi thay hợp đồng tương thích.

Python runtime dùng standard library. Có Node cho kiểm tra JS/sideload, PowerShell cho isolated Excel COM và bridge .NET 8 với package lock; bridge chạy offline sau setup.

## 4. Pattern đã áp dụng và phần chưa hoàn tất

Đã có Adapter cho HTTP/runner, Protocol + dependency injection, Facade tương thích, registry đóng ghép validator/compiler và tách hàm thuần khỏi stateful authority. Typed hỗ trợ đúng 15 operation và 10 expression kind; registry không phải cơ chế plugin động.

Chưa nên gọi toàn repo là đã clean/tối ưu hết:

- Typed store vẫn gộp preview/approval/apply/cache; **diagnostics đã tách** sang `powerquery/typed/diagnostics_service.py` (163 dòng) — service lo dựng context, gọi preview, kiểm giới hạn staging và chiếu payload công khai; store giữ lock, slot staging đơn, cache và **toàn bộ guard** quyết định promote/discard (17 mã/lời nhắn guard trước và sau giống nhau). Store chỉ giảm 1099 → 1055 dòng và tổng hai file tăng ~120 dòng — đây là đánh đổi có chủ ý: sequence đọc được một chỗ, guard nguyên tử không di chuyển. History store còn nhiều orchestration trong một module.
- Typed/history Codex planner classes **đã rút** sang `adapters/codex/typed.py` và `adapters/codex/problem_chain.py`. Hai store re-export `CodexTypedRunner`, `CodexProblemChainPlanner`, các preflight và failure-code, nên import cũ vẫn chạy; `tests/contracts/test_codex_adapter_seams.py` khoá alias này. **Seam patch đã chuyển**: patch `find_codex_executable`, `subprocess.run` và preflight phải trỏ module adapter — patch qua `pbip_assistant.pq_typed`/`problem_chain` giờ là no-op im lặng.
- Task pane còn là script lớn; controller/view/state transitions chưa tách thành các module nhỏ.
- `examples/` đã được dọn: `pbip_fixtures`/`source_fixtures` chuyển sang `tests/support` (7 caller cập nhật), `make_sample.py` sửa import path cũ sang `tests.support.fixtures`. Không còn generator chỉ phục vụ test trong `examples/`; demo `excel_mcp_fixtures`/`w21_excel_smoke`/`pq_clean_orders_with_errors.m` được giữ vì có caller tài liệu.
- Compiler đã dùng lookup map và tránh dựng lại set trong vòng lặp. Chưa có bằng chứng tăng tốc toàn luồng Excel/Codex. Tối ưu theo profile/đo đạc; không bỏ defensive copy hoặc fingerprint để giảm thời gian.

Hướng duy trì: một ứng dụng modular theo feature/domain với application services và adapter rõ. Skill chỉ phù hợp để chuẩn hoá quy trình làm việc của AI/developer; không chuyển state/approval/runtime logic thành prompt hoặc skill.

## 5. Invariant phải bảo toàn

- Nguồn Excel/PBIP mặc định chỉ đọc. Chỉ sửa PBIP copy được chọn rõ. Không dùng workbook người dùng đang mở làm fixture.
- AI không cấp approval. Approval, Preview, HEAD/review/history hash, source fingerprint và data version phải khớp đúng revision/phiên. Hard blocker không được override.
- History revision bất biến; mutations là candidate tách rời, XML read-back khớp mới commit. Giữ nguyên schema, canonical hash và lịch sử workbook cũ; không tự Save/migrate.
- Preview là staging. Confirm/write/read-back thành công mới promote cache; Cancel giữ cache/result trước đó. Cache stale/missing không được ghi kết quả cũ.
- Không tự replay POST khi hết session hoặc trạng thái ghi chưa chắc chắn. Báo partial/unknown nếu write có thể đã bắt đầu.
- Giữ TTL idle 1.800 giây/absolute 28.800 giây, host/origin/token guards, execution slots và state lock. Không chuyển quyền lock sang helper thuần khi refactor.
- `core.resources` sở hữu path resolution. Giữ entrypoint/URL/payload/status/error code, Custom XML và marker contracts.
- Source-only web UI local-only. Nhánh Excel Analyze chỉ được gửi prompt do người dùng nhập và bounded sample qua Codex khi người dùng chủ động yêu cầu; không gửi binary toàn workbook/private path.
- Không log raw cells, prompt, token, XML/Base64 hoặc private paths. `.artifacts`, `.certs`, workbook/CSV/ảnh cá nhân, demo data và binary bridge cần cho offline runtime không phải rác để xoá theo tên.
- Nếu manifest chính thay đổi: đồng bộ đúng file sang `C:\AddinManifests\manifest.xml` rồi đối chiếu SHA-256; giữ các file catalog khác.

Chi tiết: [history security](HISTORY_SECURITY.md), [UI contract](TASKPANE_UI.md), [Problem Chain](PROBLEM_CHAIN_SPEC.md), [architecture](ARCHITECTURE.md).

## 6. Kiểm chứng thực tế và gate còn mở

| Lớp | Trạng thái đã biết |
|---|---|
| Fast gate sau cleanup | 375 run: 373 pass, 0 fail/error, 2 skip; 60.591 giây. Hiện tại sau di chuyển fixture + import smoke + rút Codex planner + tách diagnostics: **386 run: 384 pass, 2 skip, 50.504 giây** |
| Runtime gate (isolated Excel COM) | 16 run, 16 pass, 0 skip; 427.694 giây (đo trên `efe9afe`; chưa chạy lại sau hai lần tách) |
| Import smoke toàn package | 93 module (`pbip_assistant` 73, `tests.support` 17, `examples` 3), 0 fail; 0.250 giây. Đã kiểm chứng ngược: cố tình tái tạo `from tests.fixtures import ...` thì test fail và nêu đúng tên module |
| Focused sau rút Codex planner | schema + crosscheck + problem-chain: 40 pass; seam guard mới: 3 pass |
| Focused sau di chuyển fixture | 50 pass, 0 fail/skip, 5.278 giây; module TMDL bị đổi import: 5 pass, 4.341 giây |
| Focused fingerprint/cache/Typed/diagnostics/history | 64 pass, 0 fail/skip; 4.446 giây |
| Focused sau tách diagnostics | Characterization guard viết **trước** khi tách: 7 case; sau tách vẫn 7/7 pass. So guard trước/sau: 17 mã+lời nhắn, không mất cái nào |
| Discovery lúc bàn giao | 393 case toàn bộ, 375 case fast; chỉ chạy `--list`, không chạy lại test trong lượt bàn giao. Hiện tại: 404 case toàn bộ, 386 case fast |
| Required-case guard | 384 ID bắt buộc trong `tests/required_cases.json`; không được bỏ guard để làm test xanh |
| Live Office.js trước fingerprint fix | Root/child commit, Preview và Confirm đã chạy trên workbook tổng hợp; root 4 hàng x 10 cột, child 2 hàng x 10 cột; nguồn giữ nguyên |
| Live cache/recovery sau fingerprint fix | Blocked, không có bằng chứng nào: add-in gate đã nạp và gate server nhận request asset của nó, nhưng cửa sổ Excel đó không phơi ribbon control cho UI Automation nên driver task pane không khởi động được |
| Advanced M | Tạm hoãn theo yêu cầu người dùng |
| Exact-current full regression/live Codex/release | Còn mở |

Hai skip của fast gate: quyền symlink không có và thiếu CSV riêng tư tùy chọn. Không chuyển kết quả simulation thành live Excel pass. Không lấy một lượt test của revision trước làm bằng chứng cho code vừa thay đổi.

Di chuyển hoặc xoá một module: cập nhật mọi caller, cập nhật `ANCHOR_MODULES` trong `tests/unit/test_import_smoke.py` nếu đó là module mỏ neo, và không nới lỏng smoke test để làm gate xanh.

Lỗi cache đã sửa: Office.js import sheet kết quả bổ sung/reindex style làm fingerprint nguồn đổi giả. Fix resolve style được nguồn tham chiếu theo nội dung, chuẩn hoá numeric/default style và named-range scope; giữ phát hiện thay đổi format nguồn kể cả khi `include_styles=False`. Không revert về hash style index thô hoặc bỏ kiểm tra format để làm cache hit.

Một phát hiện đang hoãn: chuyển Typed sang Advanced M có thể gửi tên `PQ_Typed_Result` trong `ignoredSheetNames`, bị `PQ_PREVIEW_SHEET_INVALID`. Bản sửa nhánh đó chưa được áp dụng; không tự coi là đã xử lý. Chỉ tiếp tục khi người dùng mở lại phạm vi Advanced M.

## 7. Lệnh chạy

Chạy từ root bằng PowerShell:

```powershell
py -m pbip_assistant --help
py -m pbip_assistant.webapp --port 8765 --open
py -m pbip_assistant.excel_addin_server

py tools/run_checks.py fast
py tools/run_checks.py runtime
py -m unittest discover -s tests -v

$env:PQPC_LIVE_CODEX = "1"
py tools/run_checks.py codex
Remove-Item Env:PQPC_LIVE_CODEX

dotnet restore .\tools\tmdl_bridge\TmdlBridge.csproj --locked-mode
dotnet build .\tools\tmdl_bridge\TmdlBridge.csproj -c Release --no-restore
```

Runtime Excel chạy tuần tự; không chạy nhiều COM journey tranh nhau tài nguyên/cửa sổ. `tests/live/README.md` mô tả harness synthetic và ranh giới planner deterministic so với live Codex. Không hạ TTL/approval hoặc dùng fixture cá nhân để vượt gate.

## 8. Thứ tự tiếp tục đề nghị

1. Đọc hướng dẫn và snapshot Git; giữ nguyên thay đổi local, xác định caller trước mỗi di chuyển/xoá.
2. Đóng gate Typed/cache/recovery còn thiếu trên UI thật: root/child, cache-hit không chạy lại runner, source stale -> staging -> Cancel giữ kết quả cũ, session expiry không replay, explicit recovery và failure sau write không promote cache.
3. Dọn quan hệ `examples`/test support theo dependency, từng lát có focused checks. Không xoá cả `tests` hoặc license bên thứ ba.
4. Tách orchestration lớn theo trách nhiệm thực tế; mỗi file một owner. Dùng Protocol/service nhỏ và composition; giữ authority/lock tập trung. Không thêm lớp/pattern chỉ để tăng số file.
5. Profile workload đại diện, kiểm tra trước/sau với cùng fixture và revision; đo compiler riêng, Excel/Codex riêng. Báo time/dimensions/fingerprint, không raw cells.
6. Chạy full regression và các gate live cần thiết trên code cuối. Chỉ sau khi đủ điều kiện mới đồng bộ app/npm/HTTP 1.2.0 và Office manifest 1.2.0.0. Hiện metadata app/npm là 0.1.0, manifest là 1.1.0.0; API/schema/spec versions độc lập.

Đầu ra mỗi lát: thay đổi cụ thể, lý do, command/revision, pass/fail/skip/thời gian và giới hạn chưa kiểm chứng. Không tuyên bố “100% clean/optimized/released” khi còn gate mở.

## 9. Prompt dùng để mở phiên DeepSeek

> Bạn tiếp quản source trong workspace này. Đọc AGENTS.md và docs/current/DEEPSEEK_HANDOFF.md, sau đó đối chiếu Git và code hiện tại. Mục tiêu là hoàn thiện cấu trúc theo feature/domain, tăng khả năng bảo trì và tối ưu có đo, bảo toàn hành vi và test. Advanced M đang tạm hoãn; các trường metadata đã huỷ phạm vi vẫn giữ null để tương thích. Không khôi phục báo cáo cũ, không xoá dữ liệu người dùng, không ghi đè thay đổi local hoặc tự nâng version. Bắt đầu bằng kiểm tra thực trạng và các gate Typed/cache/recovery còn mở; thực hiện từng lát nhỏ, báo rõ kết quả và phần chưa xác minh.
