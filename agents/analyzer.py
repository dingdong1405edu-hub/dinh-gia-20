"""Agent 2: Compute financial ratios deterministically + Claude qualitative analysis."""
import json
import re
import time

import anthropic

_client = anthropic.Anthropic()
_MODEL = "claude-opus-4-7"
_EFFORT = "high"


# --------------------- Public ---------------------

def analyze(extractor_payload: dict) -> dict:
    financials = extractor_payload.get("financials") or {}

    ratios = _compute_all_ratios(financials)

    t0 = time.time()
    insights, thinking_text, raw_response, usage = _claude_qualitative(financials, ratios)
    elapsed = time.time() - t0

    return {
        "model": _MODEL,
        "elapsed_sec": round(elapsed, 2),
        "input_financials": financials,
        "ratios": ratios,
        "insights": insights,
        "thinking": thinking_text,
        "raw_response": raw_response,
        "usage": usage,
    }


# --------------------- Ratios ---------------------

def _safe_div(a, b):
    if a is None or b is None:
        return None
    try:
        b = float(b)
        if b == 0:
            return None
        return float(a) / b
    except (TypeError, ValueError):
        return None


def _get(d, *path):
    cur = d
    for k in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    return cur


_THRESHOLDS = {
    # higher_is_better, [poor_below, warning_below, good_below_or_above_logic]
    "current_ratio": ("higher", 1.0, 2.0),
    "quick_ratio": ("higher", 0.5, 1.0),
    "cash_ratio": ("higher", 0.1, 0.3),
    "debt_ratio": ("lower", 0.7, 0.5),
    "debt_to_equity": ("lower", 2.0, 1.0),
    "equity_multiplier": ("lower", 3.0, 2.0),
    "gross_margin": ("higher", 0.10, 0.25),
    "operating_margin": ("higher", 0.05, 0.15),
    "net_margin": ("higher", 0.03, 0.10),
    "roa": ("higher", 0.03, 0.08),
    "roe": ("higher", 0.08, 0.15),
    "asset_turnover": ("higher", 0.5, 1.0),
    "inventory_turnover": ("higher", 4.0, 8.0),
    "receivables_turnover": ("higher", 4.0, 10.0),
}


def _rate(name: str, value):
    if value is None:
        return "n/a"
    spec = _THRESHOLDS.get(name)
    if not spec:
        return "n/a"
    direction, t_warn, t_good = spec
    if direction == "higher":
        if value >= t_good:
            return "good"
        if value >= t_warn:
            return "warning"
        return "poor"
    # lower is better
    if value <= t_good:
        return "good"
    if value <= t_warn:
        return "warning"
    return "poor"


def _compute_period_ratios(period: dict) -> dict:
    if not isinstance(period, dict):
        return {}

    bs = period if False else period
    assets = _get(bs, "balance_sheet", "assets")
    liab = _get(bs, "balance_sheet", "liabilities")
    equity = _get(bs, "balance_sheet", "equity")
    is_ = bs.get("income_statement") if isinstance(bs, dict) else None

    cash = _get(assets, "cash_and_equivalents")
    short_inv = _get(assets, "short_term_investments")
    receivables = _get(assets, "short_term_receivables")
    inventory = _get(assets, "inventory")
    current_assets = _get(assets, "current_assets_total")
    total_assets = _get(assets, "total_assets")
    current_liab = _get(liab, "current_liabilities_total")
    total_liab = _get(liab, "total_liabilities")
    total_equity = _get(equity, "total_equity")

    revenue = _get(is_, "net_revenue") or _get(is_, "revenue")
    cogs = _get(is_, "cogs")
    gross_profit = _get(is_, "gross_profit")
    operating_profit = _get(is_, "operating_profit")
    net_income = _get(is_, "net_profit_after_tax")

    cash_like = None
    if cash is not None or short_inv is not None:
        cash_like = (cash or 0) + (short_inv or 0)

    quick_assets = None
    if current_assets is not None and inventory is not None:
        quick_assets = current_assets - inventory

    raw = {
        "liquidity": {
            "current_ratio": _safe_div(current_assets, current_liab),
            "quick_ratio": _safe_div(quick_assets, current_liab),
            "cash_ratio": _safe_div(cash_like, current_liab),
        },
        "leverage": {
            "debt_ratio": _safe_div(total_liab, total_assets),
            "debt_to_equity": _safe_div(total_liab, total_equity),
            "equity_multiplier": _safe_div(total_assets, total_equity),
        },
        "profitability": {
            "gross_margin": _safe_div(gross_profit, revenue),
            "operating_margin": _safe_div(operating_profit, revenue),
            "net_margin": _safe_div(net_income, revenue),
            "roa": _safe_div(net_income, total_assets),
            "roe": _safe_div(net_income, total_equity),
        },
        "efficiency": {
            "asset_turnover": _safe_div(revenue, total_assets),
            "inventory_turnover": _safe_div(cogs, inventory),
            "receivables_turnover": _safe_div(revenue, receivables),
        },
    }

    rated: dict = {}
    for cat, items in raw.items():
        rated[cat] = {}
        for name, value in items.items():
            rated[cat][name] = {
                "value": value,
                "rating": _rate(name, value),
            }
    return rated


def _flatten_period(financials: dict, which: str) -> dict:
    """Build a 'period' dict combining BS + IS + CF for the given side ('current'/'previous')."""
    out = {}
    bs = _get(financials, "balance_sheet", which) or {}
    out["balance_sheet"] = bs
    is_ = _get(financials, "income_statement", which) or {}
    out["income_statement"] = is_
    cf = _get(financials, "cash_flow", which) or {}
    out["cash_flow"] = cf
    return out


def _compute_all_ratios(financials: dict) -> dict:
    cur_period = _flatten_period(financials, "current")
    prev_period_raw = _get(financials, "balance_sheet", "previous")

    cur = _compute_period_ratios(cur_period)
    prev = None
    if isinstance(prev_period_raw, dict):
        prev_period = _flatten_period(financials, "previous")
        prev = _compute_period_ratios(prev_period)

    changes: dict = {}
    if prev is not None:
        for cat, items in cur.items():
            changes[cat] = {}
            for name, payload in items.items():
                cv = payload.get("value")
                pv = (prev.get(cat, {}).get(name, {}) or {}).get("value")
                if cv is None or pv is None:
                    changes[cat][name] = None
                else:
                    changes[cat][name] = round(cv - pv, 4)

    return {
        "current": cur,
        "previous": prev,
        "changes": changes if prev is not None else None,
    }


# --------------------- Claude qualitative ---------------------

def _claude_qualitative(financials: dict, ratios: dict) -> tuple:
    user_prompt = f"""Bạn là chuyên gia phân tích báo cáo tài chính doanh nghiệp Việt Nam (CFA-level).

DỮ LIỆU TÀI CHÍNH (đã trích từ BCTC):
{json.dumps(financials, ensure_ascii=False, indent=2)}

TỶ SỐ TÀI CHÍNH ĐÃ TÍNH SẴN (Python tính, không sai số):
{json.dumps(ratios, ensure_ascii=False, indent=2)}

Hãy phân tích và trả về CHÍNH XÁC JSON sau (không markdown, không giải thích thêm):

{{
  "executive_summary": "<3-5 câu tiếng Việt mô tả tình hình tổng quát của doanh nghiệp, dẫn chiếu các con số nổi bật>",
  "health_score": <số nguyên 0-100, đánh giá tổng thể>,
  "health_grade": "<A | B | C | D | F>",
  "key_insights": ["<5-7 điểm nổi bật, mỗi điểm 1 câu, có dẫn số liệu cụ thể>"],
  "strengths": ["<3-5 điểm mạnh, dẫn chiếu tỷ số/giá trị>"],
  "weaknesses": ["<3-5 điểm yếu, dẫn chiếu tỷ số/giá trị>"],
  "red_flags": ["<các cảnh báo rủi ro nghiêm trọng (nếu có), VD: âm vốn chủ, mất cân đối, thanh khoản thấp...>"],
  "trends": ["<so sánh kỳ này vs kỳ trước nếu có dữ liệu, mỗi câu nêu chỉ tiêu + biến động + ý nghĩa. Để mảng rỗng [] nếu không có kỳ trước.>"],
  "recommendations": ["<3-5 khuyến nghị hành động cho ban lãnh đạo, cụ thể>"],
  "ratio_comments": {{
    "liquidity": "<1-2 câu nhận xét về khả năng thanh toán>",
    "leverage": "<1-2 câu nhận xét về cơ cấu vốn / đòn bẩy>",
    "profitability": "<1-2 câu nhận xét về sinh lời>",
    "efficiency": "<1-2 câu nhận xét về hiệu quả sử dụng tài sản>"
  }}
}}

QUY TẮC:
- Chỉ dùng số liệu trong dữ liệu được cung cấp. KHÔNG bịa.
- Mọi nhận xét phải dẫn chiếu chỉ tiêu/tỷ số cụ thể.
- Nếu thiếu dữ liệu (null), nêu rõ trong red_flags hoặc weaknesses.
- Đánh giá theo chuẩn doanh nghiệp Việt Nam phổ thông (không nói tới ngành cụ thể trừ khi field 'industry' có).
- Tiếng Việt chuyên nghiệp, súc tích, có giá trị thực tế cho ban lãnh đạo.
"""

    message = _client.messages.create(
        model=_MODEL,
        max_tokens=16000,
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
        insights = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            raise ValueError(f"Analyzer did not return JSON: {cleaned[:300]!r}")
        insights = json.loads(match.group(0))

    usage = {
        "input_tokens": getattr(message.usage, "input_tokens", None),
        "output_tokens": getattr(message.usage, "output_tokens", None),
    }
    return insights, thinking_text, raw_response, usage
