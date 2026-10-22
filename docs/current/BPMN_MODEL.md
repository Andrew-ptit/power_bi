# BPMN — Luồng Excel/CSV + PBIP

| Thuộc tính | Giá trị |
|---|---|
| Nguồn | [SPEC.md](SPEC.md) v0.5 và [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) |
| Figma | File `Demo_Figma`, trang `Page 1` |
| Phiên bản | BPMN v0.5, cập nhật 03/10/2026 |
| Trạng thái | Đã vẽ native BPMN, đồng bộ inventory và kiểm tra cấu trúc/hình học |
| Giới hạn bằng chứng | Đây là mô hình quy trình và kiểm tra tĩnh trên Figma; không phải bằng chứng Power BI Desktop runtime |

## Cách tổ chức sơ đồ

Luồng được tách thành một frame tổng quan end-to-end và bốn frame chi tiết W-01. Việc tách frame giữ nguyên quyết định nghiệp vụ nhưng tránh một sơ đồ duy nhất có quá nhiều nhánh và đường quay lại. Trạng thái cuối của frame trước là trạng thái vào của frame kế tiếp; không dùng sequence flow xuyên frame.

Mỗi sơ đồ dùng một pool. Lane `BI Analyst` sở hữu lựa chọn, phản biện, xác nhận rủi ro và phê duyệt. Lane `Ứng dụng cục bộ` sở hữu đọc/profile, tư vấn AI, hard gate, sinh/kiểm patch, backup/apply/restore. Lane `Power BI Desktop` chỉ xuất hiện trong frame tổng quan cho refresh/runtime validation. Vì các lane cùng thuộc một pool nên không có message flow.

## Frame trên Figma

| Frame | Node ID | Vị trí | Vai trò |
|---|---|---|---|
| Excel/CSV + PBIP · Luồng tổng quan v0.5 | `89:572` | x=9000, y=1500 | Toàn luồng từ chọn nguồn đến Desktop validation/restore |
| W-01A · Tiếp nhận quyết định đề xuất | `91:235` | x=9000, y=2400 | Duyệt, phản biện hoặc dừng; hard gate cho phương án duyệt |
| W-01B · AI đánh giá phản biện | `91:295` | x=11650, y=2400 | Phân loại đủ/chưa đủ căn cứ và trả verdict có reason/risk |
| W-01C · Khi AI khuyên “không nên làm” | `91:347` | x=9000, y=3200 | Sửa/dừng hoặc giữ nguyên phương án người dùng |
| W-01D · Xác nhận rủi ro và phê duyệt | `91:384` | x=11100, y=3200 | Risk acknowledgement riêng, approval riêng, hard gate kiểm lại |

## Luồng quyết định W-01

| Bước | Trạng thái vào | Hành động/kết quả | Trạng thái ra |
|---|---|---|---|
| W-01A | `proposed` | Người dùng review fields, loại chart, page và vị trí; chọn duyệt, phản biện hoặc dừng | `approved_for_preview`, `assessing_revision`, `not_applied` hoặc `blocked` |
| W-01B | `assessing_revision` | AI đánh giá bằng chứng/rủi ro/tối ưu; nếu thiếu căn cứ thì nêu đúng dữ liệu/câu hỏi còn thiếu | `awaiting_user_decision`, `needs_clarification` hoặc revision mới |
| W-01C | AI verdict `không nên làm` | Người dùng sửa/dừng hoặc giữ đúng phương án; hệ thống không tự thay bằng tối ưu | revision mới, `not_applied` hoặc `awaiting_risk_ack` |
| W-01D | `awaiting_risk_ack` | Kiểm hard gate → xác nhận rủi ro → phê duyệt đúng phương án → kiểm binding/hard gate lần cuối | `approved_for_preview` hoặc `blocked` |

Các quy tắc bắt buộc:

- AI chỉ tư vấn; verdict `nên làm` không tạo approval.
- Mọi sửa đổi/chọn tối ưu tạo revision mới; approval và risk acknowledgement cũ không được kế thừa.
- Risk acknowledgement và approval là hai user task riêng, gắn `revisionId`, `snapshotId`, operation IDs và actor.
- Nếu AI khuyên `không nên làm` nhưng không có hard block, người dùng được tiếp tục đúng phương án đã chọn.
- Hard block phải hiện mã lỗi, target, nguyên nhân và cách sửa; không có nhánh override.
- Không có đường từ phản biện/risk acknowledgement đi thẳng tới generator mà bỏ qua approval và hard gate.
- Fields, loại chart, trang và vị trí được review trước khi sinh PBIR.

## Kết quả kiểm tra

| Frame | Pool / lane / task / event / gateway / flow / boundary | Model warnings | Render findings | Reflow | Layout audit |
|---|---:|---:|---:|---:|---:|
| Excel/CSV + PBIP · Luồng tổng quan v0.5 | 1 / 3 / 14 / 8 / 3 / 25 / 4 | 0 | 0 | 25 routed; missing 0 | 0 issue; 0 style hint |
| W-01A · Tiếp nhận quyết định đề xuất | 1 / 2 / 3 / 5 / 2 / 9 / 0 | 0 | 0 | 9 routed; missing 0 | 0 issue; 0 style hint |
| W-01B · AI đánh giá phản biện | 1 / 2 / 5 / 3 / 1 / 8 / 0 | 0 | 0 | 8 routed; missing 0 | 0 issue; 0 style hint |
| W-01C · Khi AI khuyên “không nên làm” | 1 / 2 / 2 / 3 / 1 / 5 / 0 | 0 | 0 | 5 routed; missing 0 | 0 issue; 0 style hint |
| W-01D · Xác nhận rủi ro và phê duyệt | 1 / 2 / 6 / 4 / 2 / 11 / 0 | 0 | 0 | 11 routed; missing 0 | 0 issue; 0 style hint |

Kiểm tra nhất quán cuối cùng không còn `id-drift`: các frame dùng chung ID lane `LN-USER` và `LN-APP`. Start event không có incoming, end event không có outgoing, mọi XOR split có default, task trong lane có owner, và toàn bộ sequence flow nằm trong pool tương ứng. Ký hiệu và nghiệp vụ đã được rà thủ công với DT-001/AC-019…025; công cụ chỉ chứng minh cấu trúc và hình học, không chứng minh số liệu nghiệp vụ hoặc runtime Power BI.

## Model JSON tái tạo

Các block dưới đây là projection từ chính frame Figma sau lần cập nhật cuối.

### Excel/CSV + PBIP · Luồng tổng quan v0.5 (`89:572`)

```diagram-model
{
  "type": "bpmn",
  "title": "Excel/CSV + PBIP · Luồng tổng quan v0.5",
  "subtitle": "SPEC v0.5 · xem các frame W-01 cho vòng AI–người dùng · chỉ sửa bản copy",
  "pools": [
    {
      "id": "POOL-BI",
      "label": "Quy trình xây báo cáo Power BI",
      "blackBox": false
    }
  ],
  "lanes": [
    {
      "id": "LN-USER",
      "pool": "POOL-BI",
      "label": "BI Analyst"
    },
    {
      "id": "LN-APP",
      "pool": "POOL-BI",
      "label": "Ứng dụng cục bộ"
    },
    {
      "id": "LN-PBI",
      "pool": "POOL-BI",
      "label": "Power BI Desktop"
    }
  ],
  "nodes": [
    {
      "id": "N-001",
      "pool": "POOL-BI",
      "lane": "LN-USER",
      "type": "event",
      "subtype": "start",
      "label": "Cần phân tích",
      "col": 0,
      "eventRole": "start"
    },
    {
      "id": "N-002",
      "pool": "POOL-BI",
      "lane": "LN-USER",
      "type": "task",
      "subtype": "user",
      "label": "Chọn XLSX/CSV, PBIP; nêu insight",
      "owner": "BI Analyst",
      "col": 1
    },
    {
      "id": "N-003",
      "pool": "POOL-BI",
      "lane": "LN-APP",
      "type": "task",
      "subtype": "service",
      "label": "Đọc dữ liệu và model",
      "owner": "Ứng dụng cục bộ",
      "col": 2
    },
    {
      "id": "N-006",
      "pool": "POOL-BI",
      "lane": "LN-APP",
      "type": "task",
      "subtype": "service",
      "label": "Đề xuất KPI và biểu đồ",
      "owner": "Ứng dụng cục bộ",
      "col": 3
    },
    {
      "id": "N-007",
      "pool": "POOL-BI",
      "lane": "LN-USER",
      "type": "task",
      "subtype": "user",
      "label": "Duyệt / phản biện / xác nhận rủi ro (W-01)",
      "owner": "BI Analyst",
      "col": 4
    },
    {
      "id": "N-008",
      "pool": "POOL-BI",
      "lane": "LN-APP",
      "type": "task",
      "subtype": "service",
      "label": "Sinh M, DAX, TMDL, PBIR",
      "owner": "Ứng dụng cục bộ",
      "col": 5
    },
    {
      "id": "N-009",
      "pool": "POOL-BI",
      "lane": "LN-APP",
      "type": "task",
      "subtype": "service",
      "label": "Kiểm tra và preview",
      "owner": "Ứng dụng cục bộ",
      "col": 6
    },
    {
      "id": "N-011",
      "pool": "POOL-BI",
      "lane": "LN-APP",
      "type": "event",
      "subtype": "end-error",
      "label": "Cần sửa patch",
      "col": 7,
      "visualClass": "warning",
      "eventRole": "end"
    },
    {
      "id": "N-012",
      "pool": "POOL-BI",
      "lane": "LN-USER",
      "type": "task",
      "subtype": "user",
      "label": "Duyệt diff và vị trí chart",
      "owner": "BI Analyst",
      "col": 7
    },
    {
      "id": "N-013",
      "pool": "POOL-BI",
      "lane": "LN-USER",
      "type": "gateway",
      "subtype": "xor",
      "label": "Duyệt apply?",
      "col": 8
    },
    {
      "id": "N-014",
      "pool": "POOL-BI",
      "lane": "LN-USER",
      "type": "event",
      "subtype": "end",
      "label": "Không áp dụng",
      "col": 9,
      "visualClass": "warning",
      "eventRole": "end"
    },
    {
      "id": "N-015",
      "pool": "POOL-BI",
      "lane": "LN-APP",
      "type": "task",
      "subtype": "service",
      "label": "So hash, tạo copy, backup",
      "owner": "Ứng dụng cục bộ",
      "col": 9
    },
    {
      "id": "N-018",
      "pool": "POOL-BI",
      "lane": "LN-APP",
      "type": "task",
      "subtype": "service",
      "label": "Apply vào bản copy",
      "owner": "Ứng dụng cục bộ",
      "col": 10
    },
    {
      "id": "N-019",
      "pool": "POOL-BI",
      "lane": "LN-APP",
      "type": "task",
      "subtype": "service",
      "label": "Khôi phục bản copy",
      "owner": "Ứng dụng cục bộ",
      "col": 11,
      "visualClass": "exception"
    },
    {
      "id": "N-020",
      "pool": "POOL-BI",
      "lane": "LN-APP",
      "type": "event",
      "subtype": "end-error",
      "label": "Apply lỗi",
      "col": 12,
      "visualClass": "exception",
      "eventRole": "end"
    },
    {
      "id": "N-021",
      "pool": "POOL-BI",
      "lane": "LN-USER",
      "type": "task",
      "subtype": "user",
      "label": "Mở copy trong Desktop",
      "owner": "BI Analyst",
      "col": 11
    },
    {
      "id": "N-022",
      "pool": "POOL-BI",
      "lane": "LN-PBI",
      "type": "task",
      "subtype": "service",
      "label": "Refresh và hiển thị",
      "owner": "Power BI Desktop",
      "col": 12
    },
    {
      "id": "N-023",
      "pool": "POOL-BI",
      "lane": "LN-PBI",
      "type": "gateway",
      "subtype": "xor",
      "label": "Runtime đạt?",
      "col": 13
    },
    {
      "id": "N-024",
      "pool": "POOL-BI",
      "lane": "LN-PBI",
      "type": "event",
      "subtype": "end",
      "label": "Đã xác minh",
      "col": 14,
      "visualClass": "success",
      "eventRole": "end"
    },
    {
      "id": "N-025",
      "pool": "POOL-BI",
      "lane": "LN-USER",
      "type": "task",
      "subtype": "user",
      "label": "Xem lỗi, chọn cách xử lý",
      "owner": "BI Analyst",
      "col": 14,
      "visualClass": "warning"
    },
    {
      "id": "N-005",
      "pool": "POOL-BI",
      "lane": "LN-USER",
      "type": "event",
      "subtype": "end-error",
      "label": "Cần sửa đầu vào",
      "col": 3,
      "visualClass": "warning",
      "eventRole": "end"
    },
    {
      "id": "N-029",
      "pool": "POOL-BI",
      "lane": "LN-USER",
      "type": "gateway",
      "subtype": "xor",
      "label": "Khôi phục?",
      "col": 15
    },
    {
      "id": "N-030",
      "pool": "POOL-BI",
      "lane": "LN-USER",
      "type": "event",
      "subtype": "end",
      "label": "Giữ bản copy để sửa",
      "col": 16,
      "visualClass": "warning",
      "eventRole": "end"
    },
    {
      "id": "N-031",
      "pool": "POOL-BI",
      "lane": "LN-APP",
      "type": "task",
      "subtype": "service",
      "label": "Khôi phục bản copy",
      "owner": "Ứng dụng cục bộ",
      "col": 16,
      "visualClass": "warning"
    },
    {
      "id": "N-032",
      "pool": "POOL-BI",
      "lane": "LN-APP",
      "type": "event",
      "subtype": "end",
      "label": "Đã khôi phục",
      "col": 17,
      "visualClass": "warning",
      "eventRole": "end"
    }
  ],
  "sequenceFlows": [
    {
      "id": "SF-001",
      "from": "N-001",
      "to": "N-002"
    },
    {
      "id": "SF-002",
      "from": "N-002",
      "to": "N-003"
    },
    {
      "id": "SF-003",
      "from": "N-003",
      "to": "N-006"
    },
    {
      "id": "SF-004",
      "from": "N-006",
      "to": "N-007"
    },
    {
      "id": "SF-005",
      "from": "N-007",
      "to": "N-008"
    },
    {
      "id": "SF-006",
      "from": "N-008",
      "to": "N-009"
    },
    {
      "id": "SF-007",
      "from": "BE-002",
      "to": "N-011",
      "visualClass": "warning"
    },
    {
      "id": "SF-008",
      "from": "N-009",
      "to": "N-012"
    },
    {
      "id": "SF-009",
      "from": "N-012",
      "to": "N-013"
    },
    {
      "id": "SF-010",
      "from": "N-013",
      "to": "N-014",
      "condition": "không",
      "default": true,
      "visualClass": "warning"
    },
    {
      "id": "SF-011",
      "from": "N-013",
      "to": "N-015",
      "condition": "có"
    },
    {
      "id": "SF-012",
      "from": "N-015",
      "to": "N-018"
    },
    {
      "id": "SF-013",
      "from": "BE-001",
      "to": "N-019",
      "visualClass": "exception"
    },
    {
      "id": "SF-014",
      "from": "N-019",
      "to": "N-020",
      "visualClass": "exception"
    },
    {
      "id": "SF-015",
      "from": "N-018",
      "to": "N-021"
    },
    {
      "id": "SF-016",
      "from": "N-021",
      "to": "N-022"
    },
    {
      "id": "SF-017",
      "from": "N-022",
      "to": "N-023"
    },
    {
      "id": "SF-018",
      "from": "N-023",
      "to": "N-024",
      "condition": "đạt"
    },
    {
      "id": "SF-019",
      "from": "N-023",
      "to": "N-025",
      "condition": "không",
      "default": true,
      "visualClass": "warning"
    },
    {
      "id": "SF-020",
      "from": "BE-003",
      "to": "N-014",
      "visualClass": "warning"
    },
    {
      "id": "SF-021",
      "from": "BE-004",
      "to": "N-005",
      "visualClass": "warning"
    },
    {
      "id": "SF-023",
      "from": "N-025",
      "to": "N-029"
    },
    {
      "id": "SF-024",
      "from": "N-029",
      "to": "N-030",
      "condition": "giữ để sửa",
      "default": true,
      "visualClass": "warning"
    },
    {
      "id": "SF-025",
      "from": "N-029",
      "to": "N-031",
      "condition": "khôi phục",
      "visualClass": "warning"
    },
    {
      "id": "SF-026",
      "from": "N-031",
      "to": "N-032",
      "visualClass": "warning"
    }
  ],
  "messageFlows": [],
  "boundaryEvents": [
    {
      "id": "BE-001",
      "attachedTo": "N-018",
      "trigger": "error",
      "interrupting": true,
      "to": "N-019",
      "visualClass": "exception"
    },
    {
      "id": "BE-002",
      "attachedTo": "N-009",
      "trigger": "error",
      "interrupting": true,
      "to": "N-011",
      "visualClass": "warning"
    },
    {
      "id": "BE-003",
      "attachedTo": "N-015",
      "trigger": "error",
      "interrupting": true,
      "to": "N-014",
      "visualClass": "warning"
    },
    {
      "id": "BE-004",
      "attachedTo": "N-003",
      "trigger": "error",
      "interrupting": true,
      "to": "N-005",
      "visualClass": "warning"
    }
  ],
  "rules": [
    {
      "id": "BR-002",
      "statement": "KPI chưa có định nghĩa về grain, ngày và các khoản cộng/trừ liên quan được đánh dấu Needs clarification; không được apply measure phát sinh từ KPI đó.",
      "governs": "N-007"
    },
    {
      "id": "BR-005",
      "statement": "Preview chỉ có hiệu lực với snapshot nguồn tương ứng; hash thay đổi làm hết hiệu lực phê duyệt cũ.",
      "governs": "N-015"
    },
    {
      "id": "BR-006",
      "statement": "Bản copy và backup phải hoàn tất, kiểm tra được trước apply. Restore chỉ tác động bản copy, là hành động tường minh, có preview và nhật ký.",
      "governs": "N-015"
    },
    {
      "id": "BR-007",
      "statement": "Mọi kết quả kiểm tra ghi phương pháp, input, thời điểm và trạng thái; not run không được hiển thị như pass.",
      "governs": "N-023"
    },
    {
      "id": "BR-008",
      "statement": "Yêu cầu biểu đồ của người dùng là ưu tiên đầu tiên; nếu dữ liệu không phù hợp với loại biểu đồ yêu cầu, hệ thống phải nêu nguyên nhân và đưa phương án thay thế để người dùng quyết định.",
      "governs": "N-006"
    },
    {
      "id": "BR-009",
      "statement": "Visual mới chỉ được sinh khi measure/dimension/filter tham chiếu đã tồn tại hoặc nằm trong cùng patch, và trang đích/vị trí đã được duyệt.",
      "governs": "N-012"
    },
    {
      "id": "BR-010",
      "statement": "AI chỉ tư vấn; người dùng phải phê duyệt tường minh đúng revision/snapshot/operations.",
      "governs": "N-007"
    },
    {
      "id": "BR-011",
      "statement": "Nếu AI khuyên không nên và không có hard block, risk acknowledgement và approval là hai hành động riêng.",
      "governs": "N-007"
    },
    {
      "id": "BR-012",
      "statement": "Hard block thắng mọi lời khuyên và quyết định; phải hiện lỗi hành động được và không cho override.",
      "governs": "N-007"
    }
  ],
  "options": {
    "liveRoute": true,
    "rankdir": "LR"
  }
}
```

### W-01A · Tiếp nhận quyết định đề xuất (`91:235`)

```diagram-model
{
  "type": "bpmn",
  "title": "W-01A · Tiếp nhận quyết định đề xuất",
  "subtitle": "Duyệt, phản biện hoặc dừng · approval không do AI cấp",
  "pools": [
    {
      "id": "POOL-W01",
      "label": "Quyết định đề xuất",
      "blackBox": false
    }
  ],
  "lanes": [
    {
      "id": "LN-USER",
      "pool": "POOL-W01",
      "label": "BI Analyst"
    },
    {
      "id": "LN-APP",
      "pool": "POOL-W01",
      "label": "Ứng dụng cục bộ"
    }
  ],
  "nodes": [
    {
      "id": "N-101",
      "pool": "POOL-W01",
      "lane": "LN-USER",
      "type": "event",
      "subtype": "start",
      "label": "Có đề xuất",
      "col": 0,
      "eventRole": "start"
    },
    {
      "id": "N-102",
      "pool": "POOL-W01",
      "lane": "LN-USER",
      "type": "task",
      "subtype": "user",
      "label": "Review fields, chart, page, vị trí",
      "owner": "BI Analyst",
      "col": 1
    },
    {
      "id": "N-103",
      "pool": "POOL-W01",
      "lane": "LN-USER",
      "type": "gateway",
      "subtype": "xor",
      "label": "Quyết định?",
      "col": 2
    },
    {
      "id": "N-104",
      "pool": "POOL-W01",
      "lane": "LN-USER",
      "type": "event",
      "subtype": "end",
      "label": "not_applied",
      "col": 3,
      "visualClass": "warning",
      "eventRole": "end"
    },
    {
      "id": "N-105",
      "pool": "POOL-W01",
      "lane": "LN-USER",
      "type": "event",
      "subtype": "end",
      "label": "assessing_revision → W-01B",
      "col": 3,
      "eventRole": "end"
    },
    {
      "id": "N-106",
      "pool": "POOL-W01",
      "lane": "LN-APP",
      "type": "task",
      "subtype": "business-rule",
      "label": "Kiểm revision, snapshot, operations và hard gate",
      "owner": "Ứng dụng cục bộ",
      "col": 3
    },
    {
      "id": "N-107",
      "pool": "POOL-W01",
      "lane": "LN-APP",
      "type": "gateway",
      "subtype": "xor",
      "label": "Hard block?",
      "col": 4
    },
    {
      "id": "N-108",
      "pool": "POOL-W01",
      "lane": "LN-APP",
      "type": "task",
      "subtype": "service",
      "label": "Hiện mã lỗi, target, nguyên nhân, cách sửa",
      "owner": "Ứng dụng cục bộ",
      "col": 5,
      "visualClass": "exception"
    },
    {
      "id": "N-109",
      "pool": "POOL-W01",
      "lane": "LN-USER",
      "type": "event",
      "subtype": "end-error",
      "label": "blocked",
      "col": 6,
      "visualClass": "exception",
      "eventRole": "end"
    },
    {
      "id": "N-110",
      "pool": "POOL-W01",
      "lane": "LN-USER",
      "type": "event",
      "subtype": "end",
      "label": "approved_for_preview",
      "col": 5,
      "visualClass": "success",
      "eventRole": "end"
    }
  ],
  "sequenceFlows": [
    {
      "id": "SF-101",
      "from": "N-101",
      "to": "N-102"
    },
    {
      "id": "SF-102",
      "from": "N-102",
      "to": "N-103"
    },
    {
      "id": "SF-103",
      "from": "N-103",
      "to": "N-106",
      "condition": "duyệt"
    },
    {
      "id": "SF-104",
      "from": "N-103",
      "to": "N-105",
      "condition": "phản biện"
    },
    {
      "id": "SF-105",
      "from": "N-103",
      "to": "N-104",
      "condition": "dừng",
      "default": true,
      "visualClass": "warning"
    },
    {
      "id": "SF-106",
      "from": "N-106",
      "to": "N-107"
    },
    {
      "id": "SF-107",
      "from": "N-107",
      "to": "N-108",
      "condition": "có",
      "default": true,
      "visualClass": "exception"
    },
    {
      "id": "SF-108",
      "from": "N-108",
      "to": "N-109",
      "visualClass": "exception"
    },
    {
      "id": "SF-109",
      "from": "N-107",
      "to": "N-110",
      "condition": "không"
    }
  ],
  "messageFlows": [],
  "boundaryEvents": [],
  "rules": [
    {
      "id": "BR-101",
      "statement": "AI không phê duyệt; người dùng chọn rõ duyệt, phản biện hoặc dừng.",
      "governs": "N-103"
    },
    {
      "id": "BR-102",
      "statement": "Hard block hiển thị lỗi hành động được và không có override.",
      "governs": "N-107"
    }
  ],
  "options": {
    "liveRoute": true,
    "rankdir": "LR"
  }
}
```

### W-01B · AI đánh giá phản biện (`91:295`)

```diagram-model
{
  "type": "bpmn",
  "title": "W-01B · AI đánh giá phản biện",
  "subtitle": "Đủ căn cứ → verdict nên/không nên · thiếu căn cứ → hỏi bổ sung · mọi sửa đổi tạo revision mới",
  "pools": [
    {
      "id": "POOL-W01",
      "label": "Quyết định đề xuất",
      "blackBox": false
    }
  ],
  "lanes": [
    {
      "id": "LN-USER",
      "pool": "POOL-W01",
      "label": "BI Analyst"
    },
    {
      "id": "LN-APP",
      "pool": "POOL-W01",
      "label": "Ứng dụng cục bộ"
    }
  ],
  "nodes": [
    {
      "id": "N-201",
      "pool": "POOL-W01",
      "lane": "LN-USER",
      "type": "event",
      "subtype": "start",
      "label": "Có phản biện / revision",
      "col": 0,
      "eventRole": "start"
    },
    {
      "id": "N-202",
      "pool": "POOL-W01",
      "lane": "LN-APP",
      "type": "task",
      "subtype": "business-rule",
      "label": "AI đánh giá rủi ro và cách tối ưu",
      "owner": "Ứng dụng cục bộ",
      "col": 1
    },
    {
      "id": "N-203",
      "pool": "POOL-W01",
      "lane": "LN-APP",
      "type": "gateway",
      "subtype": "xor",
      "label": "Đủ căn cứ?",
      "col": 2
    },
    {
      "id": "N-204",
      "pool": "POOL-W01",
      "lane": "LN-APP",
      "type": "task",
      "subtype": "service",
      "label": "Nêu dữ liệu hoặc câu hỏi còn thiếu",
      "owner": "Ứng dụng cục bộ",
      "col": 3,
      "visualClass": "warning"
    },
    {
      "id": "N-205",
      "pool": "POOL-W01",
      "lane": "LN-USER",
      "type": "task",
      "subtype": "user",
      "label": "Bổ sung dữ liệu hoặc quy tắc",
      "owner": "BI Analyst",
      "col": 4
    },
    {
      "id": "N-206",
      "pool": "POOL-W01",
      "lane": "LN-USER",
      "type": "event",
      "subtype": "end",
      "label": "Revision mới → đánh giá lại",
      "col": 5,
      "eventRole": "end"
    },
    {
      "id": "N-207",
      "pool": "POOL-W01",
      "lane": "LN-APP",
      "type": "task",
      "subtype": "business-rule",
      "label": "Trả verdict nên làm / không nên làm",
      "owner": "Ứng dụng cục bộ",
      "col": 3
    },
    {
      "id": "N-208",
      "pool": "POOL-W01",
      "lane": "LN-USER",
      "type": "task",
      "subtype": "user",
      "label": "Review bằng chứng, reason, risk, tối ưu",
      "owner": "BI Analyst",
      "col": 4
    },
    {
      "id": "N-209",
      "pool": "POOL-W01",
      "lane": "LN-USER",
      "type": "event",
      "subtype": "end",
      "label": "Nên → W-01A · Không nên → W-01C",
      "col": 5,
      "eventRole": "end"
    }
  ],
  "sequenceFlows": [
    {
      "id": "SF-201",
      "from": "N-201",
      "to": "N-202"
    },
    {
      "id": "SF-202",
      "from": "N-202",
      "to": "N-203"
    },
    {
      "id": "SF-203",
      "from": "N-203",
      "to": "N-204",
      "condition": "không",
      "default": true,
      "visualClass": "warning"
    },
    {
      "id": "SF-204",
      "from": "N-204",
      "to": "N-205"
    },
    {
      "id": "SF-205",
      "from": "N-205",
      "to": "N-206"
    },
    {
      "id": "SF-206",
      "from": "N-203",
      "to": "N-207",
      "condition": "có"
    },
    {
      "id": "SF-207",
      "from": "N-207",
      "to": "N-208"
    },
    {
      "id": "SF-208",
      "from": "N-208",
      "to": "N-209"
    }
  ],
  "messageFlows": [],
  "boundaryEvents": [],
  "rules": [
    {
      "id": "BR-201",
      "statement": "AI trả đúng một verdict: nên làm, không nên làm hoặc chưa đủ căn cứ; luôn kèm bằng chứng/lý do phù hợp.",
      "governs": "N-203"
    },
    {
      "id": "BR-202",
      "statement": "Bổ sung hoặc sửa phương án tạo revision mới; approval và risk acknowledgement cũ hết hiệu lực.",
      "governs": "N-206"
    }
  ],
  "options": {
    "liveRoute": true,
    "rankdir": "LR"
  }
}
```

### W-01C · Khi AI khuyên “không nên làm” (`91:347`)

```diagram-model
{
  "type": "bpmn",
  "title": "W-01C · Khi AI khuyên “không nên làm”",
  "subtitle": "Không hard block: người dùng được sửa/dừng hoặc giữ nguyên phương án để sang risk acknowledgement",
  "pools": [
    {
      "id": "POOL-W01",
      "label": "Quyết định đề xuất",
      "blackBox": false
    }
  ],
  "lanes": [
    {
      "id": "LN-USER",
      "pool": "POOL-W01",
      "label": "BI Analyst"
    },
    {
      "id": "LN-APP",
      "pool": "POOL-W01",
      "label": "Ứng dụng cục bộ"
    }
  ],
  "nodes": [
    {
      "id": "N-301",
      "pool": "POOL-W01",
      "lane": "LN-APP",
      "type": "event",
      "subtype": "start",
      "label": "AI: không nên làm",
      "col": 0,
      "eventRole": "start"
    },
    {
      "id": "N-302",
      "pool": "POOL-W01",
      "lane": "LN-APP",
      "type": "task",
      "subtype": "service",
      "label": "Hiện reason, rủi ro, phương án khác",
      "owner": "Ứng dụng cục bộ",
      "col": 1,
      "visualClass": "warning"
    },
    {
      "id": "N-303",
      "pool": "POOL-W01",
      "lane": "LN-USER",
      "type": "task",
      "subtype": "user",
      "label": "Chọn sửa/dừng hoặc giữ phương án",
      "owner": "BI Analyst",
      "col": 2
    },
    {
      "id": "N-304",
      "pool": "POOL-W01",
      "lane": "LN-USER",
      "type": "gateway",
      "subtype": "xor",
      "label": "Giữ phương án?",
      "col": 3
    },
    {
      "id": "N-305",
      "pool": "POOL-W01",
      "lane": "LN-USER",
      "type": "event",
      "subtype": "end",
      "label": "Sửa → revision · Dừng → not_applied",
      "col": 4,
      "eventRole": "end"
    },
    {
      "id": "N-306",
      "pool": "POOL-W01",
      "lane": "LN-USER",
      "type": "event",
      "subtype": "end",
      "label": "Giữ → awaiting_risk_ack · W-01D",
      "col": 4,
      "visualClass": "warning",
      "eventRole": "end"
    }
  ],
  "sequenceFlows": [
    {
      "id": "SF-301",
      "from": "N-301",
      "to": "N-302"
    },
    {
      "id": "SF-302",
      "from": "N-302",
      "to": "N-303"
    },
    {
      "id": "SF-303",
      "from": "N-303",
      "to": "N-304"
    },
    {
      "id": "SF-304",
      "from": "N-304",
      "to": "N-305",
      "condition": "không",
      "default": true
    },
    {
      "id": "SF-305",
      "from": "N-304",
      "to": "N-306",
      "condition": "có",
      "visualClass": "warning"
    }
  ],
  "messageFlows": [],
  "boundaryEvents": [],
  "rules": [
    {
      "id": "BR-301",
      "statement": "Không có hard block thì người dùng được giữ đúng phương án bị AI cảnh báo; không tự thay bằng tối ưu.",
      "governs": "N-304"
    }
  ],
  "options": {
    "liveRoute": true,
    "rankdir": "LR"
  }
}
```

### W-01D · Xác nhận rủi ro và phê duyệt (`91:384`)

```diagram-model
{
  "type": "bpmn",
  "title": "W-01D · Xác nhận rủi ro và phê duyệt",
  "subtitle": "Risk acknowledgement tách khỏi approval · hard block được kiểm lại và không thể override",
  "pools": [
    {
      "id": "POOL-W01",
      "label": "Quyết định đề xuất",
      "blackBox": false
    }
  ],
  "lanes": [
    {
      "id": "LN-USER",
      "pool": "POOL-W01",
      "label": "BI Analyst"
    },
    {
      "id": "LN-APP",
      "pool": "POOL-W01",
      "label": "Ứng dụng cục bộ"
    }
  ],
  "nodes": [
    {
      "id": "N-401",
      "pool": "POOL-W01",
      "lane": "LN-USER",
      "type": "event",
      "subtype": "start",
      "label": "awaiting_risk_ack",
      "col": 0,
      "eventRole": "start"
    },
    {
      "id": "N-402",
      "pool": "POOL-W01",
      "lane": "LN-APP",
      "type": "task",
      "subtype": "business-rule",
      "label": "Kiểm hard gate trước risk ack",
      "owner": "Ứng dụng cục bộ",
      "col": 1
    },
    {
      "id": "N-403",
      "pool": "POOL-W01",
      "lane": "LN-APP",
      "type": "gateway",
      "subtype": "xor",
      "label": "Hard block?",
      "col": 2
    },
    {
      "id": "N-404",
      "pool": "POOL-W01",
      "lane": "LN-APP",
      "type": "task",
      "subtype": "service",
      "label": "Hiện mã lỗi, target, nguyên nhân, cách sửa",
      "owner": "Ứng dụng cục bộ",
      "col": 3,
      "visualClass": "exception"
    },
    {
      "id": "N-405",
      "pool": "POOL-W01",
      "lane": "LN-APP",
      "type": "event",
      "subtype": "end-error",
      "label": "blocked",
      "col": 4,
      "visualClass": "exception",
      "eventRole": "end"
    },
    {
      "id": "N-406",
      "pool": "POOL-W01",
      "lane": "LN-USER",
      "type": "task",
      "subtype": "user",
      "label": "Xác nhận đã hiểu rủi ro",
      "owner": "BI Analyst",
      "col": 3,
      "visualClass": "warning"
    },
    {
      "id": "N-407",
      "pool": "POOL-W01",
      "lane": "LN-USER",
      "type": "task",
      "subtype": "user",
      "label": "Duyệt đúng phương án đã chọn",
      "owner": "BI Analyst",
      "col": 4
    },
    {
      "id": "N-408",
      "pool": "POOL-W01",
      "lane": "LN-APP",
      "type": "task",
      "subtype": "business-rule",
      "label": "Kiểm lại hard gate và binding",
      "owner": "Ứng dụng cục bộ",
      "col": 5
    },
    {
      "id": "N-409",
      "pool": "POOL-W01",
      "lane": "LN-APP",
      "type": "gateway",
      "subtype": "xor",
      "label": "Được phép?",
      "col": 6
    },
    {
      "id": "N-410",
      "pool": "POOL-W01",
      "lane": "LN-APP",
      "type": "task",
      "subtype": "service",
      "label": "Hiện lỗi chặn; không override",
      "owner": "Ứng dụng cục bộ",
      "col": 7,
      "visualClass": "exception"
    },
    {
      "id": "N-411",
      "pool": "POOL-W01",
      "lane": "LN-APP",
      "type": "event",
      "subtype": "end-error",
      "label": "blocked",
      "col": 8,
      "visualClass": "exception",
      "eventRole": "end"
    },
    {
      "id": "N-412",
      "pool": "POOL-W01",
      "lane": "LN-USER",
      "type": "event",
      "subtype": "end",
      "label": "approved_for_preview",
      "col": 7,
      "visualClass": "success",
      "eventRole": "end"
    }
  ],
  "sequenceFlows": [
    {
      "id": "SF-401",
      "from": "N-401",
      "to": "N-402"
    },
    {
      "id": "SF-402",
      "from": "N-402",
      "to": "N-403"
    },
    {
      "id": "SF-403",
      "from": "N-403",
      "to": "N-404",
      "condition": "có",
      "default": true,
      "visualClass": "exception"
    },
    {
      "id": "SF-404",
      "from": "N-404",
      "to": "N-405",
      "visualClass": "exception"
    },
    {
      "id": "SF-405",
      "from": "N-403",
      "to": "N-406",
      "condition": "không"
    },
    {
      "id": "SF-406",
      "from": "N-406",
      "to": "N-407"
    },
    {
      "id": "SF-407",
      "from": "N-407",
      "to": "N-408"
    },
    {
      "id": "SF-408",
      "from": "N-408",
      "to": "N-409"
    },
    {
      "id": "SF-409",
      "from": "N-409",
      "to": "N-410",
      "condition": "bị chặn",
      "default": true,
      "visualClass": "exception"
    },
    {
      "id": "SF-410",
      "from": "N-410",
      "to": "N-411",
      "visualClass": "exception"
    },
    {
      "id": "SF-411",
      "from": "N-409",
      "to": "N-412",
      "condition": "hợp lệ"
    }
  ],
  "messageFlows": [],
  "boundaryEvents": [],
  "rules": [
    {
      "id": "BR-401",
      "statement": "Risk acknowledgement và approval là hai hành động riêng, gắn revisionId/snapshotId/operation IDs/actor.",
      "governs": "N-406"
    },
    {
      "id": "BR-402",
      "statement": "Hard block thắng mọi lời khuyên và quyết định; không có override.",
      "governs": "N-409"
    }
  ],
  "options": {
    "liveRoute": true,
    "rankdir": "LR"
  }
}
```

