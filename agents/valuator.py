"""Valuator: DCF (FCFF) + Multiples + Sensitivity. Python compute + Claude WACC/multiples assumptions."""
import json
import re
import time

import anthropic

_client = anthropic.Anthropic()
_MODEL = "claude-opus-4-7"
_EFFORT = "medium"


def value(financials: dict, ratios: dict, industry: dict, projection: dict) -> dict:
    t0 = time.time()
    assumptions, thinking_text, raw_response, usage = _claude_assumptions(financials, industry, projection)

    proj = (projection or {}).get("projection") or {}
    fcff_list = [p.get("fcff") for p in (proj.get("projections") or [])]
    ebitda_y1 = (proj.get("projections") or [{}])[0].get("ebitda") if proj.get("projections") else None

    is_cur = (financials.get("income_statement") or {}).get("current") or {}
    bs_cur = (financials.get("balance_sheet") or {}).get("current") or {}

    cur_ebitda = is_cur.get("operating_profit")
    cur_ebit = is_cur.get("operating_profit")
    cur_net_income = is_cur.get("net_profit_after_tax")
    total_equity_book = (bs_cur.get("equity") or {}).get("total_equity")
    total_debt_book = (bs_cur.get("liabilities") or {}).get("total_liabilities")

    wacc = (assumptions.get("wacc_pct") or 14.0) / 100.0
    terminal_growth = (assumptions.get("terminal_growth_pct") or 4.0) / 100.0
    ev_ebitda_multiple = assumptions.get("ev_ebitda_multiple") or 7.0
    pe_multiple = assumptions.get("pe_multiple") or 10.0
    pb_multiple = assumptions.get("pb_multiple") or 1.5

    dcf = _dcf_valuation(fcff_list, wacc, terminal_growth, total_debt_book)

    multiples = _multiples_valuation(
        ebitda=ebitda_y1 or cur_ebitda,
        net_income=cur_net_income,
        book_value=total_equity_book,
        debt=total_debt_book or 0,
        ev_ebitda=ev_ebitda_multiple,
        pe=pe_multiple,
        pb=pb_multiple,
    )

    sensitivity = _sensitivity(fcff_list, wacc, terminal_growth, total_debt_book)

    summary = _build_summary(dcf, multiples, assumptions)

    return {
        "model": _MODEL,
        "elapsed_sec": round(time.time() - t0, 2),
        "thinking": thinking_text,
        "raw_response": raw_response,
        "assumptions": assumptions,
        "dcf": dcf,
        "multiples": multiples,
        "sensitivity": sensitivity,
        "summary": summary,
        "usage": usage,
    }


# --------------------- Claude assumptions ---------------------

def _claude_assumptions(financials, industry, projection):
    industry_name = (industry or {}).get("industry_name") or "(unknown)"
    industry_outlook = (industry or {}).get("industry_outlook_3y") or ""
    revenue_size = (industry or {}).get("market_size") or {}
    proj_summary = ((projection or {}).get("projection") or {}).get("summary_5y") or {}

    user_prompt = f"""Bạn là chuyên gia định giá DN Việt Nam. Đề xuất các giả định định giá.

NGÀNH: {industry_name}
Triển vọng 3 năm: {industry_outlook}
CAGR doanh thu dự phóng 5Y: {proj_summary.get('revenue_cagr_pct')}%
EBITDA CAGR: {proj_summary.get('ebitda_cagr_pct')}%
Quy mô doanh nghiệp (SME) tại VN.

NHIỆM VỤ: đề xuất các tham số định giá.

TRẢ VỀ JSON (không markdown):
{{
  "wacc_pct": <số, vd 14, là chi phí vốn bình quân tại VN cho SME ngành này. Thường 12-18%>,
  "wacc_breakdown": {{
    "risk_free_rate_pct": <số, lãi suất phi rủi ro VN, vd 4-5%>,
    "equity_risk_premium_pct": <số, vd 7-9% cho thị trường VN>,
    "beta": <số, vd 1.0-1.5 cho SME>,
    "cost_of_equity_pct": <số>,
    "cost_of_debt_pct": <số, vd 8-10%>,
    "tax_rate_pct": 20,
    "debt_weight_pct": <số 0-100>,
    "equity_weight_pct": <số 0-100>,
    "rationale": "<2-3 câu lý giải>"
  }},
  "terminal_growth_pct": <số, vd 3-4. = inflation + chút>,
  "terminal_growth_rationale": "<lý do>",
  "ev_ebitda_multiple": <số, vd 6-10. Multiples ngành tại VN>,
  "ev_ebitda_rationale": "<lý do, dẫn chiếu DN niêm yết tương đương>",
  "pe_multiple": <số, vd 8-15>,
  "pe_rationale": "<lý do>",
  "pb_multiple": <số, vd 1.0-2.5>,
  "pb_rationale": "<lý do>",
  "comparable_companies": [
    {{"name": "<DN niêm yết VN tương đương>", "ev_ebitda": <số hoặc null>, "pe": <số hoặc null>, "pb": <số hoặc null>, "note": "..."}}
  ],
  "valuation_method_recommendation": "<DCF / Multiples / SOTP — và lý do>",
  "minority_discount_pct": <số 0-30, áp dụng cho SME chưa niêm yết>,
  "minority_discount_rationale": "..."
}}

QUY TẮC:
- Số phải hợp lý cho SME VN.
- 3-5 DN niêm yết tương đương trên HOSE/HNX nếu có.
- Tiếng Việt cho rationale.
"""

    message = _client.messages.create(
        model=_MODEL,
        max_tokens=8000,
        # API yêu cầu temperature=1 khi thinking bật. WACC/multiples assumptions
        # vẫn có variance nhỏ — kế toán có thể override trong INPUTS block của
        # sheet "Định giá" (ô vàng) nếu muốn rerun với assumption cố định.
        thinking={"type": "adaptive"},
        output_config={"effort": _EFFORT},
        messages=[{"role": "user", "content": user_prompt}],
    )

    thinking_text = ""
    final_text = ""
    for block in message.content:
        btype = getattr(block, "type", None)
        if btype == "thinking":
            thinking_text = getattr(block, "thinking", "") or ""
        elif btype == "text":
            final_text = getattr(block, "text", "") or ""

    raw_response = final_text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", raw_response)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            raise ValueError(f"Valuator assumptions: did not return JSON: {cleaned[:300]!r}")
        parsed = json.loads(match.group(0))

    usage = {
        "input_tokens": getattr(message.usage, "input_tokens", None),
        "output_tokens": getattr(message.usage, "output_tokens", None),
    }
    return parsed, thinking_text, raw_response, usage


# --------------------- DCF ---------------------

def _dcf_valuation(fcff_list, wacc, terminal_growth, total_debt):
    """Discount FCFF, add terminal value, return enterprise + equity value."""
    fcff_clean = [float(x) if isinstance(x, (int, float)) else None for x in (fcff_list or [])]
    if not fcff_clean or any(x is None for x in fcff_clean):
        return {
            "enterprise_value": None,
            "equity_value": None,
            "pv_explicit_fcff": None,
            "terminal_value": None,
            "pv_terminal": None,
            "wacc_pct": wacc * 100,
            "terminal_growth_pct": terminal_growth * 100,
            "note": "Không đủ FCFF để chiết khấu.",
        }

    pv_sum = 0.0
    pv_breakdown = []
    for i, fcff in enumerate(fcff_clean, 1):
        df = (1 + wacc) ** i
        pv = fcff / df if df else None
        pv_sum += pv or 0
        pv_breakdown.append({"year": i, "fcff": fcff, "discount_factor": round(df, 4), "pv": round(pv or 0, 2)})

    terminal_fcff = fcff_clean[-1] * (1 + terminal_growth)
    if wacc > terminal_growth:
        terminal_value = terminal_fcff / (wacc - terminal_growth)
        pv_terminal = terminal_value / ((1 + wacc) ** len(fcff_clean))
    else:
        terminal_value = None
        pv_terminal = None

    enterprise_value = pv_sum + (pv_terminal or 0)
    equity_value = enterprise_value - (total_debt or 0)

    return {
        "wacc_pct": round(wacc * 100, 2),
        "terminal_growth_pct": round(terminal_growth * 100, 2),
        "pv_breakdown": pv_breakdown,
        "pv_explicit_fcff": round(pv_sum, 2),
        "terminal_value": round(terminal_value, 2) if terminal_value else None,
        "pv_terminal": round(pv_terminal, 2) if pv_terminal else None,
        "enterprise_value": round(enterprise_value, 2),
        "equity_value": round(equity_value, 2),
        "debt_subtracted": total_debt,
    }


# --------------------- Multiples ---------------------

def _multiples_valuation(ebitda, net_income, book_value, debt, ev_ebitda, pe, pb):
    out = {}
    if ebitda is not None:
        ev = ebitda * ev_ebitda
        equity = ev - (debt or 0)
        out["ev_ebitda"] = {
            "multiple": ev_ebitda,
            "ebitda_input": ebitda,
            "enterprise_value": round(ev, 2),
            "equity_value": round(equity, 2),
        }
    else:
        out["ev_ebitda"] = {"multiple": ev_ebitda, "note": "Thiếu EBITDA."}
    if net_income is not None:
        out["pe"] = {
            "multiple": pe,
            "net_income_input": net_income,
            "equity_value": round(net_income * pe, 2),
        }
    else:
        out["pe"] = {"multiple": pe, "note": "Thiếu LNST."}
    if book_value is not None:
        out["pb"] = {
            "multiple": pb,
            "book_value_input": book_value,
            "equity_value": round(book_value * pb, 2),
        }
    else:
        out["pb"] = {"multiple": pb, "note": "Thiếu vốn chủ sở hữu."}
    return out


# --------------------- Sensitivity ---------------------

def _sensitivity(fcff_list, base_wacc, base_g, total_debt):
    wacc_steps = [base_wacc - 0.02, base_wacc - 0.01, base_wacc, base_wacc + 0.01, base_wacc + 0.02]
    g_steps = [base_g - 0.02, base_g - 0.01, base_g, base_g + 0.01, base_g + 0.02]

    matrix = []
    for w in wacc_steps:
        row = {"wacc_pct": round(w * 100, 2), "values": []}
        for g in g_steps:
            res = _dcf_valuation(fcff_list, w, g, total_debt)
            row["values"].append({
                "terminal_growth_pct": round(g * 100, 2),
                "equity_value": res.get("equity_value"),
            })
        matrix.append(row)

    return {
        "matrix": matrix,
        "wacc_axis_pct": [round(w * 100, 2) for w in wacc_steps],
        "growth_axis_pct": [round(g * 100, 2) for g in g_steps],
        "base_wacc_pct": round(base_wacc * 100, 2),
        "base_growth_pct": round(base_g * 100, 2),
    }


# --------------------- Summary ---------------------

def _build_summary(dcf, multiples, assumptions):
    candidates = []
    if dcf.get("equity_value") is not None:
        candidates.append(("DCF (FCFF)", dcf["equity_value"]))
    for k in ("ev_ebitda", "pe", "pb"):
        m = multiples.get(k) or {}
        if m.get("equity_value") is not None:
            label = {"ev_ebitda": "EV/EBITDA", "pe": "P/E", "pb": "P/B"}[k]
            candidates.append((label, m["equity_value"]))

    if not candidates:
        return {
            "method_values": [],
            "fair_value_low": None,
            "fair_value_mid": None,
            "fair_value_high": None,
            "fair_value_after_minority_discount": None,
            "minority_discount_pct": assumptions.get("minority_discount_pct"),
        }

    values_only = [v for _, v in candidates]
    low = min(values_only)
    high = max(values_only)
    mid = sum(values_only) / len(values_only)

    discount_pct = assumptions.get("minority_discount_pct") or 0
    discount_factor = 1 - (discount_pct / 100.0)
    fair_value_disc = mid * discount_factor

    return {
        "method_values": [{"method": k, "equity_value": v} for k, v in candidates],
        "fair_value_low": round(low, 2),
        "fair_value_mid": round(mid, 2),
        "fair_value_high": round(high, 2),
        "minority_discount_pct": discount_pct,
        "fair_value_after_minority_discount": round(fair_value_disc, 2),
    }
