"""Investment thesis writer: bull case, catalysts, risks, recommendations, executive summary."""
import json
import re
import time

import anthropic

_client = anthropic.Anthropic()
_MODEL = "claude-opus-4-7"
_EFFORT = "high"


def write(financials: dict, ratios: dict, industry: dict, business: dict,
          projection: dict, valuation: dict) -> dict:
    company = financials.get("company") or {}
    is_cur = (financials.get("income_statement") or {}).get("current") or {}
    summary_5y = ((projection or {}).get("projection") or {}).get("summary_5y") or {}
    val_summary = (valuation or {}).get("summary") or {}

    ctx = {
        "company": company,
        "period": (financials.get("period") or {}),
        "unit": financials.get("unit"),
        "current_revenue": is_cur.get("net_revenue") or is_cur.get("revenue"),
        "current_ebit": is_cur.get("operating_profit"),
        "current_net_income": is_cur.get("net_profit_after_tax"),
        "industry_summary": {
            "name": industry.get("industry_name"),
            "cagr_pct": industry.get("industry_cagr_5y_pct"),
            "outlook": industry.get("industry_outlook_3y"),
            "drivers": industry.get("industry_growth_drivers"),
            "risks": industry.get("industry_risks"),
            "competitors": industry.get("key_competitors"),
        },
        "business_summary": {
            "model": (business.get("business_model") or {}),
            "value_chain": (business.get("value_chain") or {}),
            "competitive_position": business.get("competitive_position"),
            "growth_stage": business.get("growth_stage"),
        },
        "ratios_current": ((ratios.get("ratios") or {}).get("current") or {}),
        "growth": ratios.get("growth"),
        "projection_summary": summary_5y,
        "valuation_summary": val_summary,
        "valuation_methods": (valuation.get("dcf"), valuation.get("multiples")),
    }

    user_prompt = f"""Bạn là Director of Equity Research, viết Executive Summary + Investment Thesis cho báo cáo định giá SME.

CONTEXT:
{json.dumps(ctx, ensure_ascii=False, indent=2)}

NHIỆM VỤ: tổng hợp tất cả dữ liệu trên thành 1 luận điểm đầu tư mạch lạc.

TRẢ VỀ JSON (không markdown):
{{
  "executive_summary": {{
    "headline": "<1 câu mô tả DN + giá trị định giá. Vd: 'CTCP X — DN bán lẻ điện máy quy mô vừa, định giá fair value 50-70 tỷ VND, upside 15% so với book value'>",
    "company_brief": "<1 câu mô tả ngắn DN>",
    "industry_brief": "<1 câu mô tả ngành>",
    "scale_brief": "<1 câu nêu doanh thu, EBITDA, lợi nhuận quy mô>",
    "valuation_result": "<1-2 câu kết quả định giá range, dẫn chiếu phương pháp>",
    "recommendation": "<1-2 câu khuyến nghị: gọi vốn / hold / scale / restructure>",
    "key_drivers": ["<3-5 driver chính của giá trị>"]
  }},
  "investment_thesis": {{
    "thesis_points": [
      {{
        "title": "<tên luận điểm>",
        "thesis": "<2-3 câu phát triển luận điểm>",
        "evidence": "<dẫn chiếu số liệu/tỷ số/dữ liệu ngành>"
      }}
      // 3-5 luận điểm
    ],
    "catalysts": [
      {{"type": "<expansion / fundraise / IPO / M&A / product launch>", "description": "<...>", "horizon": "<short / medium / long>"}}
    ],
    "risks": [
      {{"type": "<financial / market / operational / regulatory>", "description": "<...>", "severity": "<low / medium / high>", "mitigation": "<...>"}}
    ]
  }},
  "operations_analysis": {{
    "revenue_drivers": "<phân tích volume/price/mix dựa trên dữ liệu>",
    "margin_analysis": "<gross margin, EBITDA margin so sánh ngành>",
    "channel_breakdown": "<nếu suy được, hoặc 'Không xác định từ BCTC'>",
    "key_metrics_observations": ["<3-5 quan sát quan trọng>"]
  }},
  "financial_analysis_commentary": {{
    "balance_sheet_health": "<2-3 câu>",
    "income_statement_quality": "<2-3 câu>",
    "cash_flow_quality": "<2-3 câu>",
    "leverage_view": "<2-3 câu>"
  }},
  "valuation_commentary": {{
    "method_comparison": "<so sánh kết quả DCF vs multiples — chênh nhau bao nhiêu, lý do>",
    "fair_value_view": "<bias về DCF hay multiples? lý do>",
    "key_sensitivities": ["<2-3 biến số ảnh hưởng nhất tới giá trị>"]
  }},
  "deal_recommendation": {{
    "primary_objective": "<gọi vốn từ NĐT thiểu số / quản trị chiến lược / chuẩn bị IPO / M&A>",
    "fair_value_range_text": "<vd 'fair value 50-70 tỷ, anchor 60 tỷ'>",
    "entry_price_recommendation": "<nếu là gọi vốn: % cổ phần phát hành thêm, post-money valuation>",
    "deal_structure": "<equity / convertible / SAFE / debt — và lý do>",
    "post_deal_governance": ["<board seat, veto rights, info rights nếu áp dụng>"],
    "next_steps": ["<3-5 hành động ngay>"]
  }}
}}

QUY TẮC:
- Mọi nhận định DẪN CHIẾU CỤ THỂ số liệu/tỷ số/CAGR ngành.
- Không bịa, không generic.
- Viết theo phong cách sell-side equity research VN, súc tích, có giá trị thực tế cho Chủ DN.
- Tiếng Việt chuyên nghiệp.
"""

    t0 = time.time()
    message = _client.messages.create(
        model=_MODEL,
        max_tokens=12000,
        # API yêu cầu temperature=1 khi thinking bật.
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
            raise ValueError(f"Thesis writer did not return JSON: {cleaned[:300]!r}")
        parsed = json.loads(match.group(0))

    return {
        "model": _MODEL,
        "elapsed_sec": round(elapsed, 2),
        "thinking": thinking_text,
        "raw_response": raw_response,
        "thesis": parsed,
        "usage": {
            "input_tokens": getattr(message.usage, "input_tokens", None),
            "output_tokens": getattr(message.usage, "output_tokens", None),
        },
    }
