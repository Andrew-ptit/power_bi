"""Oracle Decimal và builder synthetic TP-FIN/TP-UNKNOWN, không gọi runtime."""

from __future__ import annotations

from collections import Counter, defaultdict
import csv
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
from pathlib import Path


PERIOD = "2026-09"
ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "assistant"
SOURCE = ROOT / "tp-fin" / "source"
ZERO = Decimal(0)
PLAN_RATES = {"USD": Decimal("25180"), "VND": Decimal(1)}
PREFIX_MAP = {"511150": "511100", "632150": "632100", "641950": "641100"}
STAMP = "2026-10-26T09:00:00Z"
LABELS = ["assumed", "unverified"]


def dec(value: str) -> Decimal:
    return Decimal(value.strip()) if value.strip() else ZERO


def number(value: Decimal | int) -> str:
    result = format(value, "f")
    return result.rstrip("0").rstrip(".") if "." in result else result


def pct(part: Decimal, whole: Decimal) -> Decimal:
    return (part / whole * 100).quantize(Decimal("0.01"), ROUND_HALF_UP) if whole else ZERO


def read(name: str) -> list[dict[str, str]]:
    with (SOURCE / (name + ".csv")).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def canonical_hash(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def identity(prefix: str, value: object, size: int = 12) -> str:
    return prefix + canonical_hash(value).split(":")[1][:size]


def artifact(fields: dict, hash_key: str) -> dict:
    result = {"schemaVersion": "1.0", **fields, "variantOf": None, "variantReason": None}
    result["hashBasis"] = list(fields) + ["variantOf", "variantReason"]
    result[hash_key] = canonical_hash({key: result[key] for key in result["hashBasis"]})
    return result


def evidence(kind: str, *, value: object = None, ref: str | None = None, formula: str | None = None) -> dict:
    return {"kind": kind, "value": None if value is None else str(value), "ref": ref, "formulaId": formula}


def compute() -> tuple[dict, dict]:
    tables = {path.stem: read(path.stem) for path in sorted(SOURCE.glob("*.csv"))}
    gl = tables["GL_Actuals_2026-09"]
    coa = {row["AccountCode"]: row for row in tables["CoA"]}
    cc = {row["CostCenter"]: row for row in tables["CostCenter"]}
    fx = {(r["CurrencyCode"], r["Month"], r["RateType"]): dec(r["Rate"]) for r in tables["FX_Rates_2026"]}
    budget = [r for r in tables["Budget_2026"] if r["Month"] == PERIOD]
    kept = []
    seen = set()
    for row in gl:
        key = tuple(row.values())
        if key not in seen:
            seen.add(key)
            kept.append(row)
    doc_keys = Counter(tuple(row[k] for k in ("EntityCode", "Ledger", "DocNo", "LineNo")) for row in kept)

    def signed(row: dict) -> Decimal:
        return dec(row["Amount"]) * (1 if row["DebitCredit"] == "C" else -1)

    def vnd(row: dict) -> Decimal:
        rate = fx.get((row["Currency"], PERIOD, "average"))
        if rate is None:
            raise SystemExit("Thiếu average rate cho tiền tệ phát sinh; không dựng fixture.")
        return signed(row) * rate

    def mapped(row: dict) -> str:
        return PREFIX_MAP.get(row["AccountCode"], row["AccountCode"])

    def info(row: dict) -> dict:
        return coa[mapped(row)]

    pnl = [r for r in kept if not r["PartnerEntity"].strip()]
    ic = [r for r in kept if r["PartnerEntity"].strip()]
    gross = sum((vnd(r) for r in pnl if info(r)["PnlGroup"] == "NetRevenue" and info(r)["AccountType"] != "ContraRevenue"), ZERO)
    rebate = sum((vnd(r) for r in pnl if info(r)["AccountType"] == "ContraRevenue"), ZERO)
    actual = {group: sum((vnd(r) for r in pnl if info(r)["PnlGroup"] == group), ZERO) for group in ("NetRevenue", "COGS", "Opex")}
    planned = defaultdict(lambda: ZERO)
    budget_ccy = defaultdict(lambda: ZERO)
    for row in budget:
        account = coa[row["AccountCode"]]
        sign = -1 if account["AccountType"] in ("ContraRevenue", "COGS", "Opex") else 1
        amount = dec(row["Amount"]) * sign
        planned[account["PnlGroup"]] += amount * PLAN_RATES[row["Currency"]]
        if account["PnlGroup"] == "NetRevenue":
            budget_ccy[row["Currency"]] += amount
    actual_ccy = defaultdict(lambda: ZERO)
    for row in pnl:
        if info(row)["PnlGroup"] == "NetRevenue":
            actual_ccy[row["Currency"]] += signed(row)
    op = sum(((actual_ccy[c] - budget_ccy[c]) * PLAN_RATES[c] for c in PLAN_RATES), ZERO)
    fx_effect = sum((actual_ccy[c] * (fx[(c, PERIOD, "average")] - PLAN_RATES[c]) for c in PLAN_RATES), ZERO)
    total = op + fx_effect
    variance = actual["NetRevenue"] - planned["NetRevenue"]
    gp = actual["NetRevenue"] + actual["COGS"]
    gp_budget = planned["NetRevenue"] + planned["COGS"]
    grouped = defaultdict(lambda: ZERO)
    for row in kept:
        line = "IntercompanyReconciliation" if row["PartnerEntity"].strip() else info(row)["PnlGroup"]
        grouped[(line, mapped(row), row["CostCenter"], row["EntityCode"])] += vnd(row)
    # Tổng hợp Budget trước khi nối: một số tiền mỗi grain, tránh nhân dòng.
    budget_grouped = defaultdict(lambda: ZERO)
    for row in budget:
        account = coa[row["AccountCode"]]
        sign = -1 if account["AccountType"] in ("ContraRevenue", "COGS", "Opex") else 1
        entity = cc.get(row["CostCenter"], {}).get("EntityCode", "UNKNOWN")
        key = (account["PnlGroup"], row["AccountCode"], row["CostCenter"], entity)
        budget_grouped[key] += dec(row["Amount"]) * sign * PLAN_RATES[row["Currency"]]
    result_keys = sorted(set(grouped) | set(budget_grouped))
    result = [(*key, grouped[key], budget_grouped[key], grouped[key] - budget_grouped[key], PERIOD, "VND") for key in result_keys]
    direct_rows = sum(max(1, sum(b["AccountCode"] == r["AccountCode"] and b["CostCenter"] == r["CostCenter"] and b["Month"] == PERIOD for b in budget)) for r in kept)
    control = sum((vnd(r) for r in kept), ZERO)
    control_result = sum((row[4] for row in result), ZERO)
    checks = {"bridge_closes": total == variance, "control_total_deduped": control == control_result}
    if not all(checks.values()):
        raise SystemExit("FAIL: identity FIN không đóng; giữ nguyên anchor.")
    anchors = {
        "rows_raw": len(gl), "exact_duplicates": len(gl) - len(kept), "rows_deduped": len(kept),
        "key_collisions": sum(n > 1 for n in doc_keys.values()), "key_collision_rows": sum(n for n in doc_keys.values() if n > 1),
        "unmapped_accounts": sorted({r["AccountCode"] for r in kept} - set(coa)),
        "orphan_cost_centers": sorted({r["CostCenter"] for r in kept} - set(cc)),
        "intercompany_rows": len(ic), "intercompany_net_vnd": sum((vnd(r) for r in ic), ZERO),
        "control_total_raw": sum((vnd(r) for r in gl), ZERO), "control_total_deduped": control,
        "gross_actual": gross, "rebate_actual": rebate, "net_revenue_actual": actual["NetRevenue"],
        "net_revenue_budget": planned["NetRevenue"], "variance": variance, "variance_pct": pct(variance, planned["NetRevenue"]),
        "cogs_actual": actual["COGS"], "cogs_budget": planned["COGS"], "opex_actual": actual["Opex"], "opex_budget": planned["Opex"],
        "gross_profit_actual": gp, "gross_profit_budget": gp_budget,
        "gross_margin_actual_pct": pct(gp, actual["NetRevenue"]), "gross_margin_budget_pct": pct(gp_budget, planned["NetRevenue"]),
        "gross_margin_delta_pp": pct(gp, actual["NetRevenue"]) - pct(gp_budget, planned["NetRevenue"]),
        "actual_usd": actual_ccy["USD"], "actual_vnd": actual_ccy["VND"],
        "budget_usd": budget_ccy["USD"], "budget_vnd": budget_ccy["VND"],
        "rate_actual_usd_average": fx[("USD", PERIOD, "average")], "rate_budget_usd": PLAN_RATES["USD"],
        "op": op, "fx": fx_effect, "bridge_total": total, "fx_share_pct": pct(fx_effect, total),
        "ic_excluded_effect_gross_profit": -sum((vnd(r) for r in ic), ZERO), "checks": checks,
    }
    return anchors, {"tables": tables, "kept": kept, "result": result, "direct_rows": direct_rows, "control_result": control_result,
                     "collision_smaller": sum((min(vnd(r) for r in kept if tuple(r[k] for k in ("EntityCode", "Ledger", "DocNo", "LineNo")) == key) for key, count in doc_keys.items() if count > 1), ZERO),
                     "unmapped_vnd": sum((vnd(r) for r in kept if r["AccountCode"] not in coa), ZERO)}


ANCHORS, _ = compute()


FORMULA_EXPRESSIONS = {
    "net_revenue_actual": "sum(amount_vnd where mapped_account.PnlGroup == NetRevenue and PartnerEntity is empty)",
    "variance_pct": "round_half_up((net_revenue_actual - net_revenue_budget) / net_revenue_budget * 100, 2)",
    "gross_profit_actual": "net_revenue_actual + cogs_actual",
    "gross_margin_delta_pp": "round_half_up(gross_profit_actual / net_revenue_actual * 100, 2) - round_half_up(gross_profit_budget / net_revenue_budget * 100, 2)",
    "fx": "sum(actual_signed_currency * (average_rate - budget_rate))",
    "op": "sum((actual_signed_currency - budget_signed_currency) * budget_rate)",
    "bridge_total": "op + fx",
    "fx_zero": "fx - fx",
    "op_policy_b": "net_revenue_actual - net_revenue_budget",
    "scenario_ab_delta": "abs(scenario_A.FX - scenario_B.FX)",
    "signed_amount": "Decimal(Amount) * (1 if DebitCredit == C else -1)",
    "amount_vnd": "signed_amount * FX[Currency, Month, average]",
    "sp1_option_b_delta": "abs(sum(amount_vnd where AccountType == ContraRevenue and not intercompany))",
    "sp2_option_b_delta": "abs(sum(actual_signed_currency * (average_rate - budget_rate)))",
    "sp3_option_b_delta": "abs(sum(amount_vnd where PartnerEntity is not empty))",
    "sp4_option_b_delta": "sum(raw_signed_vnd) - sum(exact_deduped_signed_vnd)",
    "sp5_option_b_delta": "abs(sum(amount_vnd where raw AccountCode not in CoA))",
    "sp6_option_b_delta": "sum(amount_vnd with unresolved flag) - sum(amount_vnd with CC-UNALLOC label)",
    "sp8_option_b_delta": "sum(amount_vnd) - sum(amount_vnd where required average rate exists)",
    "sp9_option_b_delta": "abs(sum(min(signed_vnd) for collision key groups))",
    "rows_raw": "len(GL_source_rows)",
    "rows_deduped": "len(unique(full_row_tuple for GL_source_rows))",
    "key_collision_rows": "sum(multiplicity for document_keys where multiplicity > 1)",
    "intercompany_rows": "count(deduped_GL where PartnerEntity is not empty)",
    "intercompany_net_vnd": "sum(amount_vnd where PartnerEntity is not empty)",
    "control_total_raw": "sum(signed_amount * average_rate for raw_GL_rows)",
    "control_total_deduped": "sum(signed_amount * average_rate for exact_deduped_GL_rows)",
    "gross_actual": "sum(amount_vnd where PnlGroup == NetRevenue and AccountType != ContraRevenue and not intercompany)",
    "rebate_actual": "sum(amount_vnd where AccountType == ContraRevenue and not intercompany)",
    "net_revenue_budget": "sum(budget_signed_amount * budget_rate where PnlGroup == NetRevenue)",
    "variance": "net_revenue_actual - net_revenue_budget",
    "cogs_actual": "sum(amount_vnd where PnlGroup == COGS and not intercompany)",
    "cogs_budget": "sum(budget_signed_amount * budget_rate where PnlGroup == COGS)",
    "opex_actual": "sum(amount_vnd where PnlGroup == Opex and not intercompany)",
    "opex_budget": "sum(budget_signed_amount * budget_rate where PnlGroup == Opex)",
    "gross_profit_budget": "net_revenue_budget + cogs_budget",
    "gross_margin_actual_pct": "round_half_up(gross_profit_actual / net_revenue_actual * 100, 2)",
    "gross_margin_budget_pct": "round_half_up(gross_profit_budget / net_revenue_budget * 100, 2)",
    "actual_usd": "sum(signed_amount where Currency == USD and PnlGroup == NetRevenue and not intercompany)",
    "actual_vnd": "sum(signed_amount where Currency == VND and PnlGroup == NetRevenue and not intercompany)",
    "budget_usd": "sum(budget_signed_amount where Currency == USD and PnlGroup == NetRevenue)",
    "budget_vnd": "sum(budget_signed_amount where Currency == VND and PnlGroup == NetRevenue)",
    "rate_actual_usd_average": "FX_Rates[USD, period, average].Rate",
    "rate_budget_usd": "frozen_pack_policy.budget_rate.USD",
    "fx_share_pct": "round_half_up(fx / bridge_total * 100, 2)",
    "ic_excluded_effect_gross_profit": "-sum(amount_vnd where PartnerEntity is not empty)",
}


def build_fixtures() -> dict[str, str]:
    a, data = compute()
    tables = data["tables"]
    tids = {name: identity("tbl_", name) for name in tables}
    sids = {name: identity("src_", name) for name in tables}
    formula_inputs = [tids[n] for n in ("GL_Actuals_2026-09", "CoA", "FX_Rates_2026", "Budget_2026")]
    formulas = {}

    def formula(name: str, expression: str, unit: str = "VND") -> str:
        fid = "fm_" + name
        expression = FORMULA_EXPRESSIONS.get(name, expression)
        formulas[fid] = {"formulaId": fid, "expression": expression, "basis": "engine-decimal", "unit": unit, "inputs": formula_inputs}
        return fid

    def value(name: str, amount: Decimal | int, unit: str = "VND", expression: str | None = None) -> dict:
        return {"formulaId": formula(name, expression or name, unit), "value": number(amount), "unit": unit}

    sources = []
    snapshots = []
    for name, rows in tables.items():
        header = list(rows[0])
        sample = [[row[key] for key in header] for row in rows[:20]]
        sources.append({"id": sids[name], "name": name + ".csv", "type": "csv", "origin": "source/" + name + ".csv",
                        "hash": canonical_hash((SOURCE / (name + ".csv")).read_bytes().hex()), "addedAt": STAMP})
        columns = []
        for key in header:
            values = [row[key] for row in rows]
            role = None if key == "Segment2" else "amount" if key in ("Amount", "Rate") else "date" if key in ("PostingDate", "Month") else "currency" if "Currency" in key else "key" if key in ("DocNo", "AccountCode", "CostCenter", "EntityCode", "CurrencyCode", "PartnerEntity", "LineNo") else "text"
            kind = "decimal" if role == "amount" else "integer" if key in ("LineNo", "DecimalPlaces") else "date" if key == "PostingDate" else "text"
            distinct_count = len({item for item in values if item != ""})
            ratio = (Decimal(distinct_count) / Decimal(len(values))).quantize(Decimal("0.001"), ROUND_HALF_UP)
            null_rate = (Decimal(sum(v == "" for v in values)) / Decimal(len(values))).quantize(Decimal("0.001"), ROUND_HALF_UP)
            columns.append({"name": key, "type": kind, "nullRate": float(null_rate), "distinctCount": distinct_count,
                            "distinctRatio": float(ratio), "sample": values[:20], "role": role,
                            "roleStatus": "unknown" if role is None else "inferred",
                            "evidence": [evidence("distinct_ratio", value=number(ratio), formula=formula("profile_distinct_ratio", "distinct_count(column) / row_count(table)", "ratio"))]})
        snapshots.append({"id": tids[name], "sourceId": sids[name], "name": name,
                          "locator": {"kind": "file", "sheet": None, "range": None, "path": "source/" + name + ".csv", "fileCount": 1},
                          "rowCount": len(rows), "columnCount": len(header), "headerHash": canonical_hash(header), "sampleHash": canonical_hash(sample),
                          "fingerprint": canonical_hash({"name": name, "header": header, "sample": sample}), "columns": columns})
    snapshot = artifact({"snapshot": {"snapshotId": identity("snap_", sources, 24), "createdAt": STAMP,
                                     "sessionId": identity("sess_", sources), "sourceCount": len(sources), "tableCount": len(snapshots)},
                         "sources": sources, "tables": snapshots}, "snapshotHash")
    roles = []
    for name, rows in tables.items():
        structural = "fact" if name == "GL_Actuals_2026-09" else "lookup" if name == "FX_Rates_2026" else "dim"
        roles.append({"tableId": tids[name], "structural": structural, "domainLabel": "Bảng " + name,
                      "confidence": 1.0, "evidence": [evidence("row_count", value=len(rows), formula=formula("row_count", "len(source_rows)", "rows"))]})

    def relation(source: str, target: str, fcols: list[str], tcols: list[str], *, fanout: bool = False) -> dict:
        left = data["kept"] if source == "GL_Actuals_2026-09" else tables[source]
        right = tables[target]
        def key(row: dict, keys: list[str]) -> tuple:
            return tuple(PERIOD if col == "Month" and col not in row else row[col] for col in keys)
        candidates = {key(row, tcols) for row in right if target != "FX_Rates_2026" or row["RateType"] == "average"}
        orphan = sum(key(row, fcols) not in candidates for row in left)
        overlap = float((Decimal(len(left) - orphan) / len(left)).quantize(Decimal("0.001"), ROUND_HALF_UP))
        return {"id": identity("rel_", [source, target, fcols, tcols]), "fromTable": tids[source], "toTable": tids[target],
                "fromColumns": fcols, "toColumns": tcols, "cardinality": "N:N" if fanout else "N:1", "score": overlap,
                "evidence": {"name": float(Decimal(sum(x == y for x, y in zip(fcols, tcols))) / len(fcols)), "type": 1.0, "overlap": overlap, "orphan": orphan},
                "status": "needs_confirm" if fanout else "auto", "fanOutRisk": "high" if fanout else "none",
                "fanOutEvidence": {"rowsBefore": len(left), "rowsAfter": data["direct_rows"], "inflationFactor": float((Decimal(data["direct_rows"]) / len(left)).quantize(Decimal("0.001"), ROUND_HALF_UP)), "blockedBy": "AF_FANOUT_RISK"} if fanout else None}

    relationships = [relation("GL_Actuals_2026-09", target, [field], [target_field]) for target, field, target_field in
                     (("CoA", "AccountCode", "AccountCode"), ("CostCenter", "CostCenter", "CostCenter"), ("Entity", "EntityCode", "EntityCode"), ("Currency", "Currency", "CurrencyCode"))]
    relationships += [relation("CostCenter", "Entity", ["EntityCode"], ["EntityCode"]),
                      relation("GL_Actuals_2026-09", "FX_Rates_2026", ["Currency", "Month"], ["CurrencyCode", "Month"]),
                      relation("GL_Actuals_2026-09", "Budget_2026", ["AccountCode", "CostCenter", "Month"], ["AccountCode", "CostCenter", "Month"], fanout=True)]
    assumptions = []
    assumption_specs = [
        ("period", "Kỳ báo cáo lấy từ ngày hạch toán của nguồn.", "data", "low"),
        ("net", "Doanh thu thuần bao gồm tài khoản giảm trừ.", "pack", "high"),
        ("average", "Báo cáo P&L sử dụng tỷ giá bình quân theo tiền tệ từng dòng.", "pack", "high"),
        ("ic", "Loại cả hai vế nội bộ khỏi P&L; giữ bucket đối soát.", "pack", "high"),
        ("history", "Policy trước đó chỉ là ngữ cảnh synthetic, cần người dùng chốt lại.", "history", "medium"),
        ("user", "Người dùng xác nhận chỉ ghi giá trị vào sheet mới.", "user", "low"),
        ("llm", "Tỷ giá có thể giải thích phần lớn chênh lệch doanh thu; đây là suy luận.", "llm", "high"),
        ("prefix", "Ánh xạ prefix tài khoản là đề xuất, chưa phải policy đã kiểm toán.", "data", "medium"),
    ]
    for name, statement, source, risk in assumption_specs:
        assumptions.append({"id": identity("asm_", name), "statement": statement, "source": source, "confidence": 0.5 if source == "llm" else 1.0,
                            "risk": risk, "evidence": [evidence("source", ref=tids["GL_Actuals_2026-09"])]})
    warnings = [{"code": "AF_MISSING_DATA", "severity": "warning", "message": message} for message in
                ("Thiếu EUR average T9 nhưng không có phát sinh EUR nên không ảnh hưởng.", "Thiếu USD closing T8; P&L chỉ dùng average nên không ảnh hưởng.")]
    understand = artifact({"snapshotHash": snapshot["snapshotHash"], "pack": {"id": "fin-pl-v1", "version": "1.0", "genericMode": False, "notice": None},
                           "roles": roles, "relationships": relationships, "assumptions": assumptions, "warnings": warnings}, "understandHash")
    specs = [
        ("Net revenue có trừ rebate?", "assumed", "pack", "Trừ rebate", "Không trừ rebate", abs(a["rebate_actual"])),
        ("FX dùng average hay budget rate?", "assumed", "pack", "Dùng average", "Dùng budget rate", abs(a["fx"])),
        ("Intercompany: loại hay giữ?", "assumed", "pack", "Loại cả hai vế, giữ bucket đối soát", "Giữ cả hai vế và gắn cờ", abs(a["intercompany_net_vnd"])),
        ("Dedupe và chuẩn hoá dấu theo luật dữ liệu?", "verified", "data", "Dedupe exact và chuẩn hoá dấu", "Không dedupe", a["control_total_raw"] - a["control_total_deduped"]),
        ("Tài khoản chưa map xử lý sao?", "inferred", "data", "Ánh xạ theo prefix", "Giữ bucket Unmapped", abs(data["unmapped_vnd"])),
        ("Cost center lạc xử lý sao?", "inferred", "data", "Giữ và gắn cờ cc_unresolved", "Gán CC-UNALLOC", ZERO),
        ("So cùng kỳ năm trước (LY)?", "missing_data", "data", "Báo cáo không LY, ngoài phạm vi", "Chặn tới khi có nguồn", None),
        ("Rate thiếu có ảnh hưởng kỳ báo cáo?", "inferred", "data", "Tiếp tục với warning cho rate không dùng", "Chặn tới khi bổ sung", ZERO),
        ("Cặp trùng khoá khác số tiền xử lý sao?", "conflict", "data", "Giữ cả hai và gắn cờ", "Bỏ dòng nhỏ hơn", abs(data["collision_smaller"])),
        ("Tách price/volume/mix cho gross margin?", "missing_data", "data", "Chỉ báo GM, ngoài phạm vi", "Yêu cầu file Sales_Detail", None),
    ]
    subproblems = []
    for index, (question, status, provenance, label_a, label_b, delta_amount) in enumerate(specs, 1):
        fid = "sp" + str(index) + "_option_b_delta"
        measured = value(fid, delta_amount) if delta_amount is not None else None
        options = [{"id": option_id, "label": label, "recommended": option_id == "A",
                    "consequence": {"statement": "Ngoài phạm vi vì chưa có nguồn; không suy đoán số." if measured is None else "Chênh lệch tuyệt đối giữa hai lựa chọn theo oracle; giữ nguyên tổng nguồn để đối soát.", "value": measured}} for option_id, label in (("A", label_a), ("B", label_b))]
        sp_evidence = [evidence("engine", value=number(delta_amount), formula=measured["formulaId"])] if measured else [evidence("missing_source", ref="LY" if index == 7 else "Sales_Detail")]
        if index == 4:
            sp_evidence += [evidence("exact_duplicates", value=a["exact_duplicates"], formula=formula("exact_duplicates", "raw_count - deduped_count", "rows")), evidence("key_collisions", value=a["key_collisions"], formula=formula("key_collisions", "count(keys with multiplicity > 1)", "groups"))]
        subproblems.append({"id": "SP-" + str(index), "question": question, "whyItMatters": "Lựa chọn quyết định cách trình bày và phạm vi kết quả.",
                            "status": status, "provenance": provenance, "evidence": sp_evidence, "options": options, "proposedOptionId": "A", "chosenOptionId": None,
                            "blocker": index in (1, 2, 3, 9), "consequenceOfChoice": None, "labels": ["out_of_scope"] if measured is None else []})
    findings = []
    for name, unit, statement in (("net_revenue_actual", "VND", "Doanh thu thuần thực tế theo các policy đề xuất."), ("variance_pct", "percent", "Chênh lệch doanh thu thuần so với ngân sách."),
                                  ("gross_profit_actual", "VND", "Lợi nhuận gộp thực tế theo policy đề xuất."), ("gross_margin_delta_pp", "percentage_points", "Chênh lệch tỷ suất lợi nhuận gộp."), ("fx", "VND", "Ảnh hưởng tỷ giá trong cầu nối doanh thu thuần.")):
        measured = value(name, a[name], unit)
        findings.append({"id": identity("fd_", name), "statement": statement, "value": measured,
                         "evidence": [evidence("engine", value=measured["value"], formula=measured["formulaId"]), evidence("source", ref=tids["GL_Actuals_2026-09"])], "status": "inferred", "provenance": "data"})
    existing_findings = {item["id"] for item in findings}
    for name, amount in a.items():
        if not isinstance(amount, (Decimal, int)) or identity("fd_", name) in existing_findings:
            continue
        unit = "rows" if name in ("rows_raw", "rows_deduped", "exact_duplicates", "key_collision_rows", "intercompany_rows") else "groups" if name == "key_collisions" else "percent" if name.endswith("_pct") else "percentage_points" if name.endswith("_pp") else "USD" if name in ("actual_usd", "budget_usd") else "VND_per_USD" if name.startswith("rate_") else "VND"
        measured = value(name, amount, unit)
        findings.append({"id": identity("fd_", name), "statement": "Chỉ tiêu đối soát do oracle tính, chưa xác nhận đúng nghiệp vụ.", "value": measured,
                         "evidence": [evidence("engine", value=measured["value"], formula=measured["formulaId"]), evidence("source", ref=tids["GL_Actuals_2026-09"])], "status": "inferred", "provenance": "data"})
    scenarios = [{"id": "A", "label": "Tỷ giá bình quân", "values": [{"name": "FX", **value("fx", a["fx"])}, {"name": "Op", **value("op", a["op"])}]},
                 {"id": "B", "label": "Tỷ giá ngân sách cố định", "values": [{"name": "FX", **value("fx_zero", a["fx"] - a["fx"])}, {"name": "Op", **value("op_policy_b", a["variance"])}]}]
    prompt = "Doanh thu thuần & lợi nhuận gộp T9 giảm do giá/chủng loại hay tỷ giá? Làm P&L theo cost center, quy VND, tách FX."
    brief = artifact({"snapshotHash": snapshot["snapshotHash"], "understandHash": understand["understandHash"], "prompt": prompt,
                      "outputContract": {"grain": ["pnlLine", "accountCode", "costCenter", "entityCode"], "measures": [{"name": "NetRevenue", "formulaId": formula("net_revenue", "sum(signed_amount_vnd where PnlGroup == NetRevenue and not intercompany)")}, {"name": "GrossProfit", "formulaId": formula("gross_profit", "net_revenue + cogs")}],
                                         "filters": [{"field": "period", "operator": "between", "value": [PERIOD + "-01", PERIOD + "-30"]}], "period": {"from": PERIOD + "-01", "to": PERIOD + "-30", "label": "T9/2026"}, "currency": "VND"},
                      "findings": findings, "insightCases": [{"id": identity("ic_", kind), "kind": kind, "statement": statement,
                                                            "evidence": [evidence("measure", ref="fm_fx", formula="fm_fx")], "status": "inferred", "provenance": "data"} for kind, statement in (("hypothesis", "Giả thuyết: tỷ giá giải thích phần lớn chênh lệch doanh thu; chưa chứng minh nguyên nhân giá bán."), ("slice", "Xem lát cắt các dòng USD theo cost center để kiểm tra phần ảnh hưởng tỷ giá."))],
                      "subProblems": subproblems, "scenarios": scenarios, "delta": value("scenario_ab_delta", abs(a["fx"])), "assumptions": assumptions, "labels": LABELS}, "briefHash")
    decisions = [{"subProblemId": sp["id"], "optionId": "A", "decidedBy": "user", "decidedAt": "2026-10-26T09:30:00Z", "rationale": "Chấp nhận lựa chọn đề xuất trong tình huống synthetic."} for sp in subproblems if sp["status"] != "missing_data"]
    acknowledgements = [{"subProblemId": sp["id"], "acknowledged": "out_of_scope", "note": "Chưa có nguồn, ngoài phạm vi; không bịa số."} for sp in subproblems if sp["status"] == "missing_data"]
    review = artifact({"snapshotHash": snapshot["snapshotHash"], "understandHash": understand["understandHash"], "briefHash": brief["briefHash"], "decisions": decisions, "acknowledgements": acknowledgements, "freezeBlocked": False}, "decisionsHash")
    step_specs = [
        ("recipe", "Nạp GL từ nguồn chỉ đọc", "load", [], "GL_Actuals_2026-09", None),
        ("recipe", "Loại dòng trùng tuyệt đối", "dedupe", ["SP-4"], None, None),
        ("calc", "Chuẩn hoá dấu theo DebitCredit", "normalize_sign", ["SP-4"], None, "signed_amount"),
        ("lookup", "Ánh xạ tài khoản theo prefix", "map_account", ["SP-5"], "CoA", None),
        ("join", "Nối danh mục tài khoản", "join_coa", [], "CoA", None),
        ("join", "Nối cost center và giữ cờ lạc", "join_cost_center", ["SP-6"], "CostCenter", None),
        ("join", "Nối pháp nhân", "join_entity", [], "Entity", None),
        ("lookup", "Tra average rate theo tiền tệ từng dòng và tháng", "lookup_fx", ["SP-2", "SP-8"], "FX_Rates_2026", "amount_vnd"),
        ("recipe", "Giữ cặp xung đột và gắn cờ", "retain_key_collision", ["SP-9"], None, None),
        ("recipe", "Tách cả hai vế nội bộ vào bucket đối soát", "separate_intercompany", ["SP-3"], None, None),
        ("group", "Tổng hợp trước khi nối ngân sách", "group", [], None, None),
        ("join", "Nối Budget đã tổng hợp cùng grain", "join_budget", [], "Budget_2026", None),
        ("calc", "Tính net revenue, variance và cầu nối", "variance_bridge", ["SP-1"], None, "bridge_total"),
        ("output", "Xuất giá trị kèm nhãn độ tin cậy", "output", [], None, None),
    ]
    steps = []
    for index, (kind, label, operation, refs, table, formula_name) in enumerate(step_specs, 1):
        previous = "st_" + str(index - 1).zfill(2)
        steps.append({"id": "st_" + str(index).zfill(2), "kind": kind, "label": label, "decisionRefs": refs,
                      "inputs": [] if index == 1 else ["q_" + str(index - 1).zfill(2)] + ([tids[table]] if table else []),
                      "params": {"operation": operation, "tableId": tids[table] if table else None,
                                 "columns": ["pnlLine", "accountCode", "costCenter", "entityCode"] if kind == "group" else None,
                                 "formulaId": formula(formula_name, formula_name) if formula_name else None},
                      "output": "q_" + str(index).zfill(2), "dependsOn": [] if index == 1 else [previous], "status": "ok", "guard": None})
    spec = artifact({"id": identity("spec_", review["decisionsHash"], 24), "snapshotHash": snapshot["snapshotHash"], "decisionsHash": review["decisionsHash"], "briefHash": brief["briefHash"],
                     "steps": steps, "labels": LABELS, "unverifiedAssumptions": [row["id"] for row in assumptions], "createdAt": "2026-10-26T09:40:00Z", "stale": False}, "fingerprint")
    source_hash = canonical_hash([s["hash"] for s in sources])
    counts_in = {"rows": a["rows_raw"], "cols": len(tables["GL_Actuals_2026-09"][0])}
    counts_out = {"rows": len(data["result"]), "cols": len(data["result"][0])}
    preview = artifact({"specFingerprint": spec["fingerprint"], "target": {"workbook": "temp_copy", "sheet": "PnL_Preview", "mode": "values_only", "marker": "LOCAL_DATA_COPILOT|PnL_Preview|spec=" + spec["fingerprint"] + "|labels=" + ",".join(LABELS)},
                        "counts": {"formulaCount": 0, "queryCount": 0, "connectionCount": 0}, "source": {"before": source_hash, "after": source_hash, "unchanged": True}, "sheets": {"before": counts_in, "after": counts_out}}, "previewHash")
    bridge = {"applicable": True, "scope": "NetRevenue", **{field: number(a[anchor]) for field, anchor in (("actualUsd", "actual_usd"), ("actualVnd", "actual_vnd"), ("budgetUsd", "budget_usd"), ("budgetVnd", "budget_vnd"), ("rateActual", "rate_actual_usd_average"), ("rateBudget", "rate_budget_usd"), ("op", "op"), ("fx", "fx"), ("total", "bridge_total"), ("variance", "variance"))}, "passed": a["checks"]["bridge_closes"]}
    reconciliation = artifact({"specFingerprint": spec["fingerprint"], "previewHash": preview["previewHash"], "rowsIn": a["rows_raw"], "rowsInDeduped": a["rows_deduped"], "rowsOut": counts_out["rows"], "colsIn": counts_in["cols"], "colsOut": counts_out["cols"],
                               "controlTotalRawSource": number(a["control_total_raw"]), "droppedByDedupe": number(a["control_total_raw"] - a["control_total_deduped"]), "controlTotalSource": number(a["control_total_deduped"]), "controlTotalResult": number(data["control_result"]), "controlTotalTolerance": "0.01", "controlTotalPassed": a["checks"]["control_total_deduped"],
                               "bridge": bridge, "checks": [{"id": key, "passed": True, "detail": detail} for key, detail in (("row_count", str(a["rows_raw"]) + " → " + str(a["rows_deduped"]) + " → " + str(counts_out["rows"])), ("control_total", "Tổng nguồn sau dedupe bằng tổng kết quả gồm bucket nội bộ."), ("bridge_identity", "op + fx = total = variance"))], "blockers": [], "warnings": warnings, "labels": LABELS, "passed": all(a["checks"].values())}, "reconcileHash")
    applied = artifact({"specFingerprint": spec["fingerprint"], "previewHash": preview["previewHash"],
                        "approval": {"approvalId": identity("apr_", preview["previewHash"]), "approvedBy": "user", "approvedAt": "2026-10-26T10:00:00Z", "boundTo": {"specFingerprint": spec["fingerprint"], "previewHash": preview["previewHash"]}, "consumed": True, "singleUse": True},
                        "target": {"workbook": "current", "sheet": "PnL_Result", "mode": "values_only", "marker": "LOCAL_DATA_COPILOT|PnL_Result|spec=" + spec["fingerprint"] + "|preview=" + preview["previewHash"] + "|labels=" + ",".join(LABELS), "writeMode": "new_sheet_only"}, "written": {"rowCount": counts_out["rows"], "columnCount": counts_out["cols"]},
                        "source": {"before": source_hash, "after": source_hash, "unchanged": True, "sheetsWritten": []}, "workbookSaved": False, "labels": LABELS, "appliedAt": "2026-10-26T10:01:00Z"}, "hash")
    record = artifact({"id": identity("rec_", spec["fingerprint"], 24), "createdAt": "2026-10-26T10:05:00Z", "snapshot": {"snapshotHash": snapshot["snapshotHash"], "sourceFingerprint": source_hash}, "brief": {"briefHash": brief["briefHash"], "prompt": prompt},
                       "decisions": decisions, "assumptions": assumptions, "steps": steps, "reconciliations": [reconciliation],
                       "delta": {"rowsIn": a["rows_raw"], "rowsOut": counts_out["rows"], "nullsBefore": {"PartnerEntity": sum(not r["PartnerEntity"] for r in tables["GL_Actuals_2026-09"])}, "nullsAfter": {"PartnerEntity": 0}, "duplicatesBefore": a["exact_duplicates"], "duplicatesAfter": len(data["result"]) - len({row[:4] for row in data["result"]}), "changedColumns": ["DebitCredit→amountSigned", "AccountCode→accountMapped", "Amount→amountVnd"]}, "labels": LABELS, "stale": False}, "hash")
    unknown_brief = json.loads(json.dumps(brief, ensure_ascii=False))
    unknown_brief.pop("briefHash")
    unknown_brief.pop("hashBasis")
    unknown_brief.pop("schemaVersion")
    unknown_brief.pop("variantOf")
    unknown_brief.pop("variantReason")
    unknown_brief["prompt"] = prompt + " Tôi không chắc các policy; cần hỏi lại người sở hữu nghiệp vụ."
    unknown_brief = artifact(unknown_brief, "briefHash")
    unknown_review = artifact({"snapshotHash": snapshot["snapshotHash"], "understandHash": understand["understandHash"], "briefHash": unknown_brief["briefHash"], "decisions": [], "acknowledgements": [], "freezeBlocked": True,
                               "blockers": [{"code": "AF_MISSING_DATA", "severity": "warning", "message": "Người dùng chưa chốt 3 policy; hệ thống không chọn hộ."}],
                               "checklist": ["Tài khoản rebate có được trừ khỏi doanh thu thuần trong policy đã duyệt?", "Báo cáo kỳ này dùng tỷ giá bình quân hay tỷ giá ngân sách?", "Hai vế nội bộ có được loại đồng thời khỏi P&L? Rà soát cờ PartnerEntity."]}, "decisionsHash")
    formulas_artifact = artifact({"formulas": [formulas[key] for key in sorted(formulas)]}, "hash")
    payloads = {"tp-fin/" + name + ".json": obj for name, obj in (("wl1_snapshot", snapshot), ("wl2_understand", understand), ("wl3_brief", brief), ("wl3_decisions", review), ("wl4_execution_spec", spec), ("wl5_preview", preview), ("wl5_reconciliation", reconciliation), ("wl6_apply", applied), ("wl7_decision_record", record), ("formulas", formulas_artifact))}
    payloads.update({"tp-unknown/wl3_brief_unresolved.json": unknown_brief, "tp-unknown/wl3_decisions_unresolved.json": unknown_review})
    return {name: json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n" for name, obj in sorted(payloads.items())}


def generate(root: Path = ROOT) -> None:
    """Ghi artifact từ bộ CSV tự chứa; không sao chép hoặc sửa nguồn."""
    for name, payload in build_fixtures().items():
        target = Path(root) / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(payload, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    generate()
    print("TP-FIN/TP-UNKNOWN: generated", len(build_fixtures()), "JSON artifacts.")
