"""Business profile agent: company overview, business model, value chain."""
import json
import re
import time

import anthropic

_client = anthropic.Anthropic()
_MODEL = "claude-opus-4-7"
_EFFORT = "low"


def analyze_business(financials: dict, industry: dict) -> dict:
    company = financials.get("company") or {}
    bs_cur = (financials.get("balance_sheet") or {}).get("current") or {}
    is_cur = (financials.get("income_statement") or {}).get("current") or {}

    user_prompt = f"""Bạn là analyst SME, viết phần "Tổng quan doanh nghiệp" trong báo cáo định giá.

THÔNG TIN DN:
{json.dumps(company, ensure_ascii=False, indent=2)}

NGÀNH:
{json.dumps(industry, ensure_ascii=False, indent=2)}

DỮ LIỆU TÀI CHÍNH KỲ HIỆN TẠI:
- Doanh thu thuần: {is_cur.get('net_revenue')}
- Giá vốn: {is_cur.get('cogs')}
- LN gộp: {is_cur.get('gross_profit')}
- Chi phí bán hàng: {is_cur.get('selling_expense')}
- Chi phí QLDN: {is_cur.get('admin_expense')}
- Vốn góp CSH: {(bs_cur.get('equity') or {}).get('share_capital')}
- TSCĐ: {(bs_cur.get('assets') or {}).get('fixed_assets')}
- Hàng tồn kho: {(bs_cur.get('assets') or {}).get('inventory')}
- Phải thu: {(bs_cur.get('assets') or {}).get('short_term_receivables')}
- Đơn vị: {financials.get('unit')}

NHIỆM VỤ: Suy luận và phác thảo TỔNG QUAN DN dựa trên dữ liệu có sẵn + bối cảnh ngành.
Cái gì BCTC không cho biết thì ghi rõ "Không xác định từ BCTC". Không bịa.

TRẢ VỀ JSON (không markdown):
{{
  "history_inferred": "<vài câu suy luận từ vốn góp/tên/ngành — vd 'Theo quy mô vốn X tỷ và doanh thu Y tỷ, DN có quy mô vừa, ước hoạt động 5-10 năm'. Hoặc 'Không xác định từ BCTC'.>",
  "ownership_summary": "<vốn góp X (đơn vị từ BCTC). Loại hình DN suy luận từ tên (TNHH/CP/...).>",
  "management": "<'Không xác định từ BCTC' nếu không có thuyết minh>",
  "business_model": {{
    "summary": "<2-3 câu mô tả mô hình KD dựa vào tỷ lệ COGS/SG&A và ngành>",
    "revenue_model": "<B2C / B2B / B2B2C / mix — suy đoán>",
    "products_services": ["<sản phẩm/dịch vụ chính suy đoán từ ngành>"],
    "customer_segments": ["<phân khúc KH chính>"]
  }},
  "unit_economics": {{
    "gross_margin_pct": <% biên lợi nhuận gộp đã tính, hoặc null>,
    "operating_margin_pct": <% biên LN HĐKD, hoặc null>,
    "comments": "<so sánh với mặt bằng ngành>"
  }},
  "value_chain": {{
    "input": "<đầu vào chính>",
    "production": "<hoạt động sản xuất/vận hành>",
    "distribution": "<kênh phân phối suy đoán>",
    "customer": "<đối tượng khách hàng>"
  }},
  "scale_indicators": {{
    "revenue_size_class": "<micro <10 tỷ | small 10-100 | medium 100-1000 | large >1000 — VND>",
    "employee_estimate": "<ước lượng số NV nếu đoán được, vd '20-50 người', else null>",
    "asset_intensity": "<asset-light | balanced | asset-heavy>"
  }},
  "competitive_position": "<vị thế suy đoán: leader / challenger / niche / follower + lý do>",
  "growth_stage": "<startup | early-growth | scale-up | mature | turnaround>"
}}

QUY TẮC:
- KHÔNG bịa lịch sử cụ thể, ban lãnh đạo cụ thể nếu BCTC không nêu.
- Mọi suy luận có evidence (số liệu hoặc ngành).
- Tiếng Việt.
"""

    t0 = time.time()
    message = _client.messages.create(
        model=_MODEL,
        max_tokens=6000,
        thinking={"type": "adaptive"},
        output_config={"effort": _EFFORT},
        messages=[{"role": "user", "content": user_prompt}],
    )
    elapsed = time.time() - t0

    thinking_text, raw_response, parsed = _parse(message)

    return {
        "model": _MODEL,
        "elapsed_sec": round(elapsed, 2),
        "thinking": thinking_text,
        "raw_response": raw_response,
        "business": parsed,
        "usage": {
            "input_tokens": getattr(message.usage, "input_tokens", None),
            "output_tokens": getattr(message.usage, "output_tokens", None),
        },
    }


def _parse(message):
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
            raise ValueError(f"Business profile did not return JSON: {cleaned[:300]!r}")
        parsed = json.loads(match.group(0))
    return thinking_text, raw_response, parsed
