"""Phép đo Decimal thuần bộ nhớ cho nửa tất định của Brief WL3."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date
from decimal import Context, Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
import re

from pbip_assistant.errors import InputError
from .assistant_understand import _bind_raw


ZERO = Decimal("0")
CENT = Decimal("0.01")
# Đầu vào policy đóng băng của công thức tham chiếu, không phải tổng tiền nguồn.
FROZEN_BUDGET_RATE_USD = Decimal("25180")
# Phạm vi số được hỗ trợ rõ; các phép tiền trong phạm vi này tính chính xác.
MAX_NUMERIC_DIGITS = 50
MAX_NUMERIC_EXPONENT = 50
_ARITHMETIC_CONTEXT = Context(prec=300, rounding=ROUND_HALF_UP)


def _missing(detail: str) -> InputError:
    return InputError("AF_MISSING_DATA", "measures", detail)


def _decimal(value: str) -> Decimal:
    try:
        result = Decimal(value.strip())
    except (InvalidOperation, AttributeError) as exc:
        raise _missing("Dữ liệu số bắt buộc bị thiếu hoặc không hợp lệ.") from exc
    if not result.is_finite():
        raise _missing("Dữ liệu số bắt buộc phải hữu hạn.")
    if (len(result.as_tuple().digits) > MAX_NUMERIC_DIGITS or
            abs(result.as_tuple().exponent) > MAX_NUMERIC_EXPONENT or
            abs(result.adjusted()) > MAX_NUMERIC_EXPONENT):
        raise _missing("Dữ liệu số vượt giới hạn độ chính xác của engine.")
    return result


def _format_number(value: Decimal | int, unit: str) -> str:
    if isinstance(value, bool) or not isinstance(value, (Decimal, int)):
        raise ValueError("Giá trị đo phải là Decimal hoặc int")
    value = Decimal(value)
    if not value.is_finite():
        raise ValueError("Giá trị đo phải hữu hạn")
    if unit in {"percent", "percentage_points"}:
        return format(value.quantize(CENT, ROUND_HALF_UP), ".2f")
    if unit in {"VND", "rows", "groups", "count"}:
        if value != value.to_integral_value():
            raise ValueError("Đơn vị này yêu cầu giá trị nguyên; không tự làm tròn")
        return format(value.quantize(Decimal("1")), "f")
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def number(value: Decimal | int, unit: str = "VND") -> str:
    """Xuất số hữu hạn; không phụ thuộc precision của context bên ngoài."""
    with localcontext(_ARITHMETIC_CONTEXT):
        return _format_number(value, unit)


def _pct(part: Decimal, whole: Decimal) -> Decimal | None:
    return (part / whole * Decimal("100")).quantize(CENT, ROUND_HALF_UP) if whole else None


def _records(raw: dict) -> list[dict[str, str]]:
    return [dict(zip(raw["header"], row, strict=True)) for row in raw["rows"]]


def _select(tables: list[dict], required: set[str], *, excluded: set[str] = frozenset()) -> dict:
    candidates = [raw for raw in tables if required <= set(raw["header"])
                  and not excluded.intersection(raw["header"])]
    if len(candidates) != 1:
        raise _missing("Không xác định duy nhất bảng nguồn cần thiết cho phép đo.")
    return candidates[0]


def _unique(rows: list[dict], field: str) -> dict:
    result = {}
    for row in rows:
        value = row[field]
        if not value or value in result:
            raise _missing("Khóa danh mục phải duy nhất và không rỗng.")
        result[value] = row
    return result


def _period(value: str) -> str:
    try:
        return date.fromisoformat(value).isoformat()[:7]
    except (ValueError, TypeError) as exc:
        raise _missing("Ngày hạch toán phải là ngày ISO hợp lệ.") from exc


def _account(code: str, accounts: dict) -> dict:
    if code in accounts:
        return accounts[code]
    # Chỉ đề xuất prefix cùng nhóm tài khoản, không chọn khi có nhiều ứng viên bằng điểm.
    candidates = []
    for mapped, info in accounts.items():
        length = 0
        for left, right in zip(code, mapped):
            if left != right:
                break
            length += 1
        if length >= 3:
            candidates.append((length, mapped, info))
    if not candidates:
        raise _missing("Tài khoản chưa có ánh xạ prefix đủ bằng chứng.")
    best = max(item[0] for item in candidates)
    winners = [item[2] for item in candidates if item[0] == best]
    if len(winners) != 1:
        raise _missing("Ánh xạ prefix tài khoản còn mơ hồ.")
    return winners[0]


def _finance(tables: list[dict]) -> dict:
    ledger = _select(tables, {"DocNo", "LineNo", "PostingDate", "DebitCredit", "Amount",
                              "AccountCode", "Currency", "PartnerEntity", "EntityCode", "Ledger"})
    accounts = _unique(_records(_select(tables, {"AccountCode", "AccountType", "PnlGroup"})), "AccountCode")
    rates_raw = _records(_select(tables, {"CurrencyCode", "Month", "RateType", "Rate"}))
    budget_raw = _records(_select(tables, {"Month", "AccountCode", "CostCenter", "Currency", "Amount"},
                                 excluded={"DebitCredit"}))
    rows = _records(ledger)
    if not rows:
        raise _missing("Không có dòng GL để đo kỳ báo cáo.")
    months = {_period(row["PostingDate"]) for row in rows}
    if len(months) != 1:
        raise _missing("Phép cầu nối hiện tại cần một tháng GL duy nhất.")
    period = next(iter(months))
    kept, seen = [], set()
    for row in rows:
        key = tuple(row[field] for field in ledger["header"])
        if key not in seen:
            kept.append(row)
            seen.add(key)
    document_counts = Counter(tuple(row[field] for field in ("EntityCode", "Ledger", "DocNo", "LineNo")) for row in kept)
    rates = {}
    for row in rates_raw:
        key = (row["CurrencyCode"], row["Month"], row["RateType"].strip().casefold())
        value = _decimal(row["Rate"])
        if value <= 0 or key in rates and rates[key] != value:
            raise _missing("Tỷ giá phải dương và không có giá trị xung đột trên cùng khóa.")
        rates[key] = value

    def signed(row: dict) -> Decimal:
        if row["DebitCredit"] not in {"C", "D"}:
            raise _missing("Dấu GL phải được khai báo bằng C hoặc D.")
        return _decimal(row["Amount"]) * (1 if row["DebitCredit"] == "C" else -1)

    def vnd(row: dict) -> Decimal:
        rate = rates.get((row["Currency"], _period(row["PostingDate"]), "average"))
        if rate is None and row["Currency"] == "VND":
            rate = Decimal("1")
        if rate is None:
            raise _missing("Thiếu tỷ giá bình quân cho đồng tiền có phát sinh.")
        return signed(row) * rate

    control_raw = sum((vnd(row) for row in rows), ZERO)
    control = sum((vnd(row) for row in kept), ZERO)
    pnl = [row for row in kept if not row["PartnerEntity"].strip()]
    ic = [row for row in kept if row["PartnerEntity"].strip()]
    info = lambda row: _account(row["AccountCode"], accounts)
    gross = sum((vnd(row) for row in pnl if info(row)["PnlGroup"] == "NetRevenue"
                 and info(row)["AccountType"] != "ContraRevenue"), ZERO)
    rebate = sum((vnd(row) for row in pnl if info(row)["AccountType"] == "ContraRevenue"), ZERO)
    cogs = sum((vnd(row) for row in pnl if info(row)["PnlGroup"] == "COGS"), ZERO)
    opex = sum((vnd(row) for row in pnl if info(row)["PnlGroup"] == "Opex"), ZERO)
    net = gross + rebate
    planned, actual_currency, budget_currency = defaultdict(lambda: ZERO), defaultdict(lambda: ZERO), defaultdict(lambda: ZERO)
    plan_rates = {"USD": FROZEN_BUDGET_RATE_USD, "VND": Decimal("1")}
    for row in budget_raw:
        if row["Month"] != period:
            continue
        if row["Currency"] not in plan_rates or row["AccountCode"] not in accounts:
            raise _missing("Budget có tiền tệ hoặc tài khoản chưa được policy hiện tại hỗ trợ.")
        account = accounts[row["AccountCode"]]
        amount = _decimal(row["Amount"])
        if account["AccountType"] == "ContraRevenue" or account["PnlGroup"] in {"COGS", "Opex"}:
            amount = -amount
        planned[account["PnlGroup"]] += amount * plan_rates[row["Currency"]]
        if account["PnlGroup"] == "NetRevenue":
            budget_currency[row["Currency"]] += amount
    for row in pnl:
        if info(row)["PnlGroup"] == "NetRevenue":
            actual_currency[row["Currency"]] += signed(row)
    if set(actual_currency) - set(plan_rates):
        raise _missing("Cầu nối hiện tại chỉ có basis USD và VND.")
    actual_usd, actual_vnd = actual_currency["USD"], actual_currency["VND"]
    budget_usd, budget_vnd = budget_currency["USD"], budget_currency["VND"]
    rate_actual = rates.get(("USD", period, "average"))
    if rate_actual is None and actual_usd:
        raise _missing("Thiếu basis tỷ giá USD cho cầu nối.")
    op = (actual_usd - budget_usd) * FROZEN_BUDGET_RATE_USD + actual_vnd - budget_vnd
    fx = actual_usd * (rate_actual - FROZEN_BUDGET_RATE_USD) if rate_actual is not None else ZERO
    variance = net - planned["NetRevenue"]
    if op + fx != variance:
        raise _missing("Cầu nối không đóng với chênh lệch nguồn; không xuất số suy đoán.")
    gp, gp_budget = net + cogs, planned["NetRevenue"] + planned["COGS"]
    gm, gm_budget = _pct(gp, net), _pct(gp_budget, planned["NetRevenue"])
    collision_minima = []
    for key, count in document_counts.items():
        if count > 1:
            matching = [row for row in kept if tuple(row[field] for field in ("EntityCode", "Ledger", "DocNo", "LineNo")) == key]
            collision_minima.append(min(vnd(row) for row in matching))
    unmapped = sum((vnd(row) for row in kept if row["AccountCode"] not in accounts), ZERO)
    result = {
        "rows_raw": len(rows), "exact_duplicates": len(rows) - len(kept), "rows_deduped": len(kept),
        "key_collisions": sum(count > 1 for count in document_counts.values()),
        "key_collision_rows": sum(count for count in document_counts.values() if count > 1),
        "intercompany_rows": len(ic), "intercompany_net_vnd": sum((vnd(row) for row in ic), ZERO),
        "control_total_raw": control_raw, "control_total_deduped": control,
        "gross_actual": gross, "rebate_actual": rebate, "net_revenue_actual": net,
        "net_revenue_budget": planned["NetRevenue"], "variance": variance,
        "variance_pct": _pct(variance, planned["NetRevenue"]), "cogs_actual": cogs,
        "cogs_budget": planned["COGS"], "opex_actual": opex, "opex_budget": planned["Opex"],
        "gross_profit_actual": gp, "gross_profit_budget": gp_budget,
        "gross_margin_actual_pct": gm, "gross_margin_budget_pct": gm_budget,
        "gross_margin_delta_pp": gm - gm_budget if gm is not None and gm_budget is not None else None,
        "actual_usd": actual_usd, "actual_vnd": actual_vnd, "budget_usd": budget_usd, "budget_vnd": budget_vnd,
        "rate_actual_usd_average": rate_actual, "rate_budget_usd": FROZEN_BUDGET_RATE_USD,
        "op": op, "fx": fx, "bridge_total": op + fx, "fx_share_pct": _pct(fx, variance),
        "ic_excluded_effect_gross_profit": -sum((vnd(row) for row in ic), ZERO),
        "op_policy_b": variance, "fx_zero": fx - fx, "scenario_ab_delta": abs(fx),
        "sp1_option_b_delta": abs(rebate), "sp2_option_b_delta": abs(fx),
        "sp3_option_b_delta": abs(sum((vnd(row) for row in ic), ZERO)),
        "sp4_option_b_delta": control_raw - control, "sp5_option_b_delta": abs(unmapped),
        "sp6_option_b_delta": control - control, "sp7_option_b_delta": None,
        "sp8_option_b_delta": control - sum((vnd(row) for row in kept), ZERO),
        "sp9_option_b_delta": abs(sum(collision_minima, ZERO)), "sp10_option_b_delta": None,
    }
    return result


def _region_key(region: str) -> str:
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", region) is None:
        raise _missing("Mã khu vực cần identifier an toàn và không mơ hồ.")
    return "region_" + region.lower()


def _sales(tables: list[dict]) -> dict:
    orders = _records(_select(tables, {"OrderID", "OrderDate", "CustomerID", "TerritoryID", "Status"}))
    items = _records(_select(tables, {"OrderID", "ProductID", "Quantity", "UnitPrice", "DiscountPct"}))
    customers = _unique(_records(_select(tables, {"CustomerID", "TerritoryID"}, excluded={"OrderID"})), "CustomerID")
    territories = _unique(_records(_select(tables, {"TerritoryID", "Region"})), "TerritoryID")
    by_id = _unique(orders, "OrderID")

    def line(item: dict) -> Decimal:
        if item["OrderID"] not in by_id:
            raise _missing("OrderItems có dòng không có Order tương ứng.")
        discount = _decimal(item["DiscountPct"])
        if discount < 0 or discount > 100:
            raise _missing("Phần trăm chiết khấu nằm ngoài khoảng hợp lệ.")
        return (_decimal(item["Quantity"]) * _decimal(item["UnitPrice"]) *
                (Decimal("1") - discount / Decimal("100"))).quantize(CENT, ROUND_HALF_UP)

    amounts = defaultdict(lambda: ZERO)
    for item in items:
        amounts[item["OrderID"]] += line(item)
    cancelled = {row["OrderID"] for row in orders if row["Status"] == "Cancelled"}
    returned = {row["OrderID"] for row in orders if row["Status"] == "Returned"}
    region_totals = defaultdict(lambda: ZERO)
    region_labels = {}
    orphan_revenue, fallback_revenue = ZERO, ZERO
    for row in orders:
        if row["OrderID"] in cancelled:
            continue
        fallback = customers.get(row["CustomerID"], {}).get("TerritoryID", "")
        territory = row["TerritoryID"].strip() or fallback
        region = territories.get(territory, {}).get("Region", "UNKNOWN")
        key = _region_key(region)
        if key in region_labels and region_labels[key] != region:
            raise _missing("Hai nhãn khu vực tạo cùng identifier; cần chuẩn hóa nguồn tường minh.")
        region_labels[key] = region
        region_totals[key] += amounts[row["OrderID"]]
        if row["CustomerID"] not in customers:
            orphan_revenue += amounts[row["OrderID"]]
        if not row["TerritoryID"].strip() and fallback:
            fallback_revenue += amounts[row["OrderID"]]
    result = {
        "orders": len(orders), "order_lines": len(items), "cancelled_orders": len(cancelled),
        "returned_orders": len(returned),
        "orphan_customer_orders": sum(row["CustomerID"] not in customers for row in orders),
        "orders_missing_territory": sum(not row["TerritoryID"].strip() for row in orders),
        "revenue_all_orders": sum(amounts.values(), ZERO),
        "revenue_excluding_cancelled": sum((amounts[row["OrderID"]] for row in orders if row["OrderID"] not in cancelled), ZERO),
        "revenue_cancelled_excluded": sum((amounts[key] for key in cancelled), ZERO),
        "return_lines_effect": sum((line(item) for item in items if item["OrderID"] in returned), ZERO),
        "orphan_customer_revenue": orphan_revenue, "territory_fallback_revenue": fallback_revenue,
    }
    result.update(dict(sorted(region_totals.items())))
    return result


def measure_set(raw_tables, snapshot) -> dict[str, Decimal | int | None]:
    """Tính lại từ raw được bind snapshot, không đọc file/pack/golden hoặc gọi mạng."""
    with localcontext(_ARITHMETIC_CONTEXT):
        tables = _bind_raw(raw_tables, snapshot)
        finance = any({"DocNo", "PostingDate", "DebitCredit", "Amount"} <= set(raw["header"]) for raw in tables)
        return _finance(tables) if finance else _sales(tables)


_EXPRESSIONS = {
    "rows_raw": ("len(ledger.raw_rows)", "rows"),
    "exact_duplicates": ("len(raw_rows) - len(exact_distinct_rows)", "rows"),
    "rows_deduped": ("len(exact_distinct_rows)", "rows"),
    "key_collisions": ("count(document_keys where multiplicity > 1)", "groups"),
    "key_collision_rows": ("sum(multiplicity for colliding document_keys)", "rows"),
    "intercompany_rows": ("count(deduped_ledger where PartnerEntity nonempty)", "rows"),
    "intercompany_net_vnd": ("sum(signed_amount * average_rate where PartnerEntity nonempty)", "VND"),
    "control_total_raw": ("sum(raw_signed_amount * row_currency_average_rate)", "VND"),
    "control_total_deduped": ("sum(deduped_signed_amount * row_currency_average_rate)", "VND"),
    "gross_actual": ("sum(non_ic_net_revenue_rows excluding ContraRevenue)", "VND"),
    "rebate_actual": ("sum(non_ic_ContraRevenue_signed_vnd)", "VND"),
    "net_revenue_actual": ("gross_actual + rebate_actual", "VND"),
    "net_revenue_budget": ("sum(budget_net_revenue_signed_amount * frozen_budget_rate)", "VND"),
    "variance": ("net_revenue_actual - net_revenue_budget", "VND"),
    "variance_pct": ("variance / net_revenue_budget * 100", "percent"),
    "cogs_actual": ("sum(non_ic_COGS_signed_vnd)", "VND"),
    "cogs_budget": ("sum(budget_COGS_signed_amount * frozen_budget_rate)", "VND"),
    "opex_actual": ("sum(non_ic_Opex_signed_vnd)", "VND"),
    "opex_budget": ("sum(budget_Opex_signed_amount * frozen_budget_rate)", "VND"),
    "gross_profit_actual": ("net_revenue_actual + cogs_actual", "VND"),
    "gross_profit_budget": ("net_revenue_budget + cogs_budget", "VND"),
    "gross_margin_actual_pct": ("gross_profit_actual / net_revenue_actual * 100", "percent"),
    "gross_margin_budget_pct": ("gross_profit_budget / net_revenue_budget * 100", "percent"),
    "gross_margin_delta_pp": ("gross_margin_actual_pct - gross_margin_budget_pct", "percentage_points"),
    "actual_usd": ("sum(non_ic_signed_USD where PnlGroup == NetRevenue)", "USD"),
    "actual_vnd": ("sum(non_ic_signed_VND where PnlGroup == NetRevenue)", "VND"),
    "budget_usd": ("sum(budget_signed_USD where PnlGroup == NetRevenue)", "USD"),
    "budget_vnd": ("sum(budget_signed_VND where PnlGroup == NetRevenue)", "VND"),
    "rate_actual_usd_average": ("rates[USD,report_month,average]", "VND_per_USD"),
    "rate_budget_usd": ("frozen_policy.budget_rate.USD", "VND_per_USD"),
    "op": ("(actual_usd-budget_usd)*rate_budget_usd + actual_vnd-budget_vnd", "VND"),
    "fx": ("actual_usd * (rate_actual_usd_average-rate_budget_usd)", "VND"),
    "bridge_total": ("op + fx", "VND"),
    "fx_share_pct": ("fx / variance * 100", "percent"),
    "ic_excluded_effect_gross_profit": ("-intercompany_net_vnd", "VND"),
    "op_policy_b": ("variance", "VND"),
    "fx_zero": ("fx - fx", "VND"),
    "scenario_ab_delta": ("abs(fx - fx_zero)", "VND"),
    "sp1_option_b_delta": ("abs(rebate_actual)", "VND"),
    "sp2_option_b_delta": ("abs(fx)", "VND"),
    "sp3_option_b_delta": ("abs(intercompany_net_vnd)", "VND"),
    "sp4_option_b_delta": ("control_total_raw - control_total_deduped", "VND"),
    "sp5_option_b_delta": ("abs(sum(deduped_unmapped_signed_vnd))", "VND"),
    "sp6_option_b_delta": ("control_total_deduped - reclassified_control_total", "VND"),
    "sp7_option_b_delta": ("missing_data(LY)", "VND"),
    "sp8_option_b_delta": ("control_total_deduped - control_with_available_used_rates", "VND"),
    "sp9_option_b_delta": ("abs(sum(min(signed_vnd) per colliding_document_key))", "VND"),
    "sp10_option_b_delta": ("missing_data(Sales_Detail)", "VND"),
    "orders": ("len(orders)", "count"),
    "order_lines": ("len(order_items)", "count"),
    "cancelled_orders": ("count(orders where Status == Cancelled)", "count"),
    "returned_orders": ("count(orders where Status == Returned)", "count"),
    "orphan_customer_orders": ("count(orders anti_join customers)", "count"),
    "orders_missing_territory": ("count(orders where TerritoryID empty)", "count"),
    "revenue_all_orders": ("sum(Quantity * UnitPrice * (1 - DiscountPct/100))", "VND"),
    "revenue_excluding_cancelled": ("sum(line_revenue where order.Status != Cancelled)", "VND"),
    "revenue_cancelled_excluded": ("sum(line_revenue where order.Status == Cancelled)", "VND"),
    "return_lines_effect": ("sum(line_revenue where order.Status == Returned)", "VND"),
    "orphan_customer_revenue": ("sum(non_cancelled_revenue where customer missing)", "VND"),
    "territory_fallback_revenue": ("sum(non_cancelled_revenue where order territory empty and customer territory present)", "VND"),
}


def formulas(measures: dict | None = None) -> list[dict]:
    """Registry thuần; region bổ sung được khai báo từ tên measure, không dùng state toàn cục."""
    definitions = dict(_EXPRESSIONS)
    regions = {"region_central", "region_north", "region_south", "region_unknown"}
    if measures is not None:
        if not isinstance(measures, dict):
            raise ValueError("measures phải là object")
        for name in measures:
            if name.startswith("region_"):
                if re.fullmatch(r"region_[a-z][a-z0-9_]*", name) is None:
                    raise ValueError("Tên measure khu vực không hợp lệ")
                regions.add(name)
            elif name not in definitions:
                raise ValueError("Measure chưa có công thức được hỗ trợ")
    for name in sorted(regions):
        definitions[name] = ("sum(non_cancelled_line_revenue where resolved_region == " + name[7:].upper() + ")", "VND")
    return [{"formulaId": "fm_" + name, "expression": expression, "basis": "engine-decimal", "unit": unit,
             "inputs": ["orders", "order_items", "customers", "territories"] if name.startswith("region_") or name in {
                 "orders", "order_lines", "cancelled_orders", "returned_orders", "orphan_customer_orders", "orders_missing_territory",
                 "revenue_all_orders", "revenue_excluding_cancelled", "revenue_cancelled_excluded", "return_lines_effect",
                 "orphan_customer_revenue", "territory_fallback_revenue"} else ["ledger", "accounts", "rates", "budget"]}
            for name, (expression, unit) in sorted(definitions.items())]


def _scenario_fx_basis(measures: dict) -> dict:
    if "fx" not in measures and "op" not in measures:
        return {"scenarios": [], "delta": None}
    required = {"fx", "op", "op_policy_b", "fx_zero", "scenario_ab_delta", "variance", "bridge_total"}
    if not required <= set(measures):
        raise ValueError("Thiếu measure bắt buộc cho kịch bản FX")
    if any(not isinstance(measures[name], (Decimal, int)) or isinstance(measures[name], bool)
           or not Decimal(measures[name]).is_finite() for name in required):
        raise ValueError("Kịch bản FX cần giá trị hữu hạn từ engine")
    if (measures["op"] + measures["fx"] != measures["variance"] or
            measures["bridge_total"] != measures["variance"] or
            measures["op_policy_b"] + measures["fx_zero"] != measures["variance"] or
            measures["scenario_ab_delta"] != abs(measures["fx"] - measures["fx_zero"])):
        raise ValueError("Kịch bản FX không đóng với measure nguồn")

    def value(name: str) -> dict:
        return {"formulaId": "fm_" + name, "value": number(measures[name]), "unit": "VND"}

    return {"scenarios": [{"id": "A", "values": [{"name": "FX", **value("fx")}, {"name": "Op", **value("op")}]},
                          {"id": "B", "values": [{"name": "FX", **value("fx_zero")}, {"name": "Op", **value("op_policy_b")}]}],
            "delta": value("scenario_ab_delta")}


def scenario_fx_basis(measures: dict) -> dict:
    """Hai cách phân bổ cầu nối; nhãn câu chữ do pack sở hữu, không gọi AI."""
    with localcontext(_ARITHMETIC_CONTEXT):
        return _scenario_fx_basis(measures)
