"""Industry & market analyst agent: TAM/SAM/SOM, CAGR, competitors, trends."""
import json
import re
import time

import anthropic

_client = anthropic.Anthropic()
_MODEL = "claude-opus-4-7"
_EFFORT = "medium"


def analyze_industry(financials: dict) -> dict:
    company = financials.get("company") or {}
    name = company.get("name") or "(Unknown)"
    industry_hint = company.get("industry") or ""

    is_cur = (financials.get("income_statement") or {}).get("current") or {}
    revenue = is_cur.get("net_revenue") or is_cur.get("revenue")
    unit = financials.get("unit") or "đồng"

    user_prompt = f"""Bạn là chuyên gia phân tích ngành & thị trường Việt Nam (sell-side equity research).

THÔNG TIN DOANH NGHIỆP:
- Tên: {name}
- Ngành (gợi ý từ BCTC): {industry_hint or '(chưa rõ — hãy suy đoán từ tên DN và cơ cấu doanh thu/COGS)'}
- Doanh thu thuần kỳ gần nhất: {revenue} ({unit})
- Sản phẩm/COGS gợi ý từ BCTC: {is_cur.get('cogs')}

NHIỆM VỤ: phân tích NGÀNH HOẠT ĐỘNG ĐỘNG của DN này theo chuẩn báo cáo định giá SME.
Sử dụng kiến thức của bạn về thị trường Việt Nam đến hiện tại. Nếu không chắc số cụ thể, đưa ước lượng + ghi rõ giả định.

TRẢ VỀ CHÍNH XÁC JSON (không markdown, không giải thích):
{{
  "industry_name": "<tên ngành cụ thể, vd: 'Bán lẻ điện máy', 'Sản xuất bao bì nhựa', 'F&B chuỗi'>",
  "industry_classification_basis": "<lý do chọn ngành này, dẫn chiếu BCTC>",
  "industry_overview": "<2-3 câu mô tả tổng quan ngành ở VN>",
  "market_size": {{
    "tam_vnd_billion": <số hoặc null, total addressable market ở VN, tỷ đồng>,
    "sam_vnd_billion": <số hoặc null, serviceable addressable>,
    "som_vnd_billion": <số hoặc null, serviceable obtainable>,
    "assumptions": "<giải thích cách ước lượng>",
    "company_market_share_pct": <số 0-100 hoặc null, ước lượng thị phần>
  }},
  "industry_cagr_5y_pct": <số (vd 8 cho 8%/năm) hoặc null>,
  "industry_growth_drivers": ["<3-5 driver tăng trưởng>"],
  "industry_trends": ["<3-5 xu hướng nổi bật>"],
  "key_competitors": [
    {{
      "name": "<tên đối thủ>",
      "estimated_revenue_vnd_billion": <số hoặc null>,
      "market_share_pct": <số 0-100 hoặc null>,
      "note": "<điểm khác biệt / vị thế>"
    }}
  ],
  "competitive_landscape": "<2-3 câu mô tả mức độ cạnh tranh, fragmented vs concentrated, có người dẫn đầu rõ ràng?>",
  "industry_risks": ["<3-5 rủi ro ngành>"],
  "regulatory_environment": "<thuế, giấy phép, các quy định ảnh hưởng>",
  "barriers_to_entry": ["<rào cản gia nhập ngành>"],
  "industry_outlook_3y": "<bull / neutral / bear + lý do>"
}}

QUY TẮC:
- Số liệu phải hợp lý — nếu Anh không biết chính xác hãy ghi null + ghi rõ trong assumptions.
- 3-5 đối thủ cạnh tranh quen thuộc của ngành tại VN.
- Tiếng Việt chuyên nghiệp.
"""

    # opus-4-7 deprecated `temperature` param entirely. Industry agent dùng default
    # sampling, KHÔNG bật extended thinking để giảm variance ở TAM/SAM/SOM.
    # Đánh đổi: thinking giúp reasoning sâu hơn, nhưng cho TAM/SAM (essentially
    # estimation từ training data) consistency > nuance reasoning.
    t0 = time.time()
    message = _client.messages.create(
        model=_MODEL,
        max_tokens=8000,
        messages=[{"role": "user", "content": user_prompt}],
    )
    elapsed = time.time() - t0

    thinking_text, raw_response, parsed = _parse(message)

    return {
        "model": _MODEL,
        "elapsed_sec": round(elapsed, 2),
        "thinking": thinking_text,
        "raw_response": raw_response,
        "industry": parsed,
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
            raise ValueError(f"Industry analyst did not return JSON: {cleaned[:300]!r}")
        parsed = json.loads(match.group(0))
    return thinking_text, raw_response, parsed
