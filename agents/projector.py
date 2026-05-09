"""Financial projector: 5-year revenue/EBITDA/FCF projection driven by Claude assumptions."""
import json
import re
import time

import anthropic

_client = anthropic.Anthropic()
_MODEL = "claude-opus-4-7"
_EFFORT = "high"


def project(financials: dict, ratios: dict, industry: dict) -> dict:
    is_cur = (financials.get("income_statement") or {}).get("current") or {}
    is_prev = (financials.get("income_statement") or {}).get("previous") or {}
    bs_cur = (financials.get("balance_sheet") or {}).get("current") or {}
    period_label = (financials.get("period") or {}).get("current", {}).get("label") or ""

    cur_revenue = is_cur.get("net_revenue") or is_cur.get("revenue")
    prev_revenue = is_prev.get("net_revenue") or is_prev.get("revenue")
    industry_cagr = industry.get("industry_cagr_5y_pct")

    revenue_yoy = (ratios.get("growth") or {}).get("revenue_yoy")

    user_prompt = f"""Bạn là analyst tài chính, lập DỰ PHÓNG 5 NĂM cho doanh nghiệp.

DỮ LIỆU LỊCH SỬ:
- Kỳ hiện tại ({period_label}):
  Doanh thu thuần: {cur_revenue}
  Giá vốn: {is_cur.get('cogs')}
  LN gộp: {is_cur.get('gross_profit')}
  Chi phí BH: {is_cur.get('selling_expense')}
  Chi phí QLDN: {is_cur.get('admin_expense')}
  EBIT: {is_cur.get('operating_profit')}
  Lãi vay: {is_cur.get('interest_expense')}
  Thuế: {is_cur.get('current_tax')}
  LNST: {is_cur.get('net_profit_after_tax')}
  TSCĐ: {(bs_cur.get('assets') or {}).get('fixed_assets')}
  Tổng TS: {(bs_cur.get('assets') or {}).get('total_assets')}
  HTK: {(bs_cur.get('assets') or {}).get('inventory')}
  Phải thu: {(bs_cur.get('assets') or {}).get('short_term_receivables')}

- Kỳ trước:
  Doanh thu: {prev_revenue}
  LNST: {is_prev.get('net_profit_after_tax')}

- Tăng trưởng YoY doanh thu (đã tính): {revenue_yoy}

- CAGR ngành 5 năm: {industry_cagr}%

- Đơn vị: {financials.get('unit')}

NHIỆM VỤ:
1. Lập giả định tăng trưởng 5 năm (Y1-Y5) hợp lý dựa trên ngành + lịch sử + quy mô DN.
2. Dự phóng KQKD đầy đủ.
3. Dự phóng FCFF (FCF cho doanh nghiệp) — dùng cho định giá DCF.

TRẢ VỀ JSON (không markdown):
{{
  "base_year_label": "<vd 'FY2023' hoặc 'Năm gần nhất'>",
  "assumptions": {{
    "revenue_growth_pct": [<Y1>, <Y2>, <Y3>, <Y4>, <Y5>],
    "growth_rationale": "<2-3 câu lý giải. Tham chiếu CAGR ngành, S-curve, base effect.>",
    "gross_margin_pct": [<Y1..Y5>],
    "operating_expense_pct_revenue": [<Y1..Y5>],
    "tax_rate_pct": <số (vd 20)>,
    "depreciation_pct_revenue": <số>,
    "capex_pct_revenue": [<Y1..Y5>],
    "working_capital_days": <số ngày, vd 60>,
    "rationale_capex": "<lý do giả định CAPEX>",
    "rationale_wc": "<lý do giả định WC>"
  }},
  "projections": [
    {{
      "year_index": 1,
      "year_label": "Y1",
      "revenue": <số>,
      "growth_pct": <số>,
      "cogs": <số>,
      "gross_profit": <số>,
      "operating_expense": <số>,
      "ebit": <số>,
      "depreciation": <số>,
      "ebitda": <số>,
      "interest_expense": <số>,
      "profit_before_tax": <số>,
      "tax": <số>,
      "net_income": <số>,
      "capex": <số>,
      "change_in_wc": <số>,
      "fcff": <số>,
      "ebitda_margin_pct": <số>,
      "net_margin_pct": <số>
    }},
    ... 5 năm
  ],
  "summary_5y": {{
    "revenue_cagr_pct": <số>,
    "ebitda_cagr_pct": <số>,
    "fcff_cumulative": <số>,
    "comments": "<1-2 câu nhận xét quỹ đạo>"
  }}
}}

QUY TẮC:
- Tất cả số dương trừ khi thực sự âm (lỗ).
- Đơn vị dự phóng GIỮ NGUYÊN đơn vị BCTC (vd nếu BCTC là 'triệu đồng', dự phóng cũng là 'triệu đồng').
- Tăng trưởng giảm dần theo thời gian (Y1 cao nhất, Y5 thấp nhất, hội tụ về CAGR ngành) — quy luật S-curve.
- CAPEX = D&A khi DN bão hòa; cao hơn khi đang tăng trưởng.
- FCFF = EBIT × (1-tax%) + D&A − CAPEX − ΔWC.
- Mọi giả định phải có lý do.
- Nếu thiếu base data, ghi rõ trong rationale.
"""

    t0 = time.time()
    message = _client.messages.create(
        model=_MODEL,
        max_tokens=10000,
        temperature=0,  # determinism: dự phóng 5Y phải ổn định giữa các lần chạy
        thinking={"type": "adaptive"},
        output_config={"effort": _EFFORT},
        messages=[{"role": "user", "content": user_prompt}],
    )
    elapsed = time.time() - t0

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
            raise ValueError(f"Projector did not return JSON: {cleaned[:300]!r}")
        parsed = json.loads(match.group(0))

    return {
        "model": _MODEL,
        "elapsed_sec": round(elapsed, 2),
        "thinking": thinking_text,
        "raw_response": raw_response,
        "projection": parsed,
        "usage": {
            "input_tokens": getattr(message.usage, "input_tokens", None),
            "output_tokens": getattr(message.usage, "output_tokens", None),
        },
    }
