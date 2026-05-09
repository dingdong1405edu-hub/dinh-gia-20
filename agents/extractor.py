"""Agent 1: Vietnamese financial report (PDF/image) -> structured JSON."""
import base64
import json
import re
import time
from pathlib import Path

import anthropic

_client = anthropic.Anthropic()
_MODEL = "claude-opus-4-7"
_EFFORT = "medium"

_IMAGE_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}

_PROMPT = """You are a meticulous financial data extraction agent for Vietnamese business financial reports \
("Báo cáo tài chính" / BCTC).

The document may include:
- Bảng cân đối kế toán (Balance Sheet)
- Báo cáo kết quả hoạt động kinh doanh (Income Statement)
- Báo cáo lưu chuyển tiền tệ (Cash Flow Statement)
- Thuyết minh báo cáo tài chính (Notes)

Extract all available financial figures EXACTLY. Numbers in Vietnamese reports use:
- "." as thousand separator: "1.234.567" means 1234567
- "," as decimal separator: "1.234,56" means 1234.56
- Parentheses or minus sign for negatives: "(1.234)" or "-1.234" means -1234
- Empty cells / "-" mean null (NOT zero)

Return ONLY this JSON shape (no markdown fences, no explanation):

{
  "company": {
    "name": "<exact company name as printed>",
    "tax_code": "<MST nếu có, else null>",
    "address": "<địa chỉ nếu có, else null>",
    "industry": "<ngành nếu nêu, else null>",
    "report_type": "<e.g. 'Báo cáo tài chính năm 2023', 'Quý 4/2023'>"
  },
  "period": {
    "current": {"label": "<e.g. '31/12/2023', 'Năm 2023', 'Quý 4 năm 2023'>"},
    "previous": {"label": "<comparable period if present, else null>"}
  },
  "currency": "<VND | USD | ...>",
  "unit": "<exact unit from header: đồng | nghìn đồng | triệu đồng | tỷ đồng | đồng VN>",
  "balance_sheet": {
    "current": {
      "assets": {
        "cash_and_equivalents": <number or null>,
        "short_term_investments": <number or null>,
        "short_term_receivables": <number or null>,
        "inventory": <number or null>,
        "other_current_assets": <number or null>,
        "current_assets_total": <number or null>,
        "long_term_receivables": <number or null>,
        "fixed_assets": <number or null>,
        "investment_properties": <number or null>,
        "long_term_investments": <number or null>,
        "other_non_current_assets": <number or null>,
        "non_current_assets_total": <number or null>,
        "total_assets": <number or null>
      },
      "liabilities": {
        "short_term_debt": <number or null>,
        "accounts_payable": <number or null>,
        "other_current_liabilities": <number or null>,
        "current_liabilities_total": <number or null>,
        "long_term_debt": <number or null>,
        "other_non_current_liabilities": <number or null>,
        "non_current_liabilities_total": <number or null>,
        "total_liabilities": <number or null>
      },
      "equity": {
        "share_capital": <number or null>,
        "retained_earnings": <number or null>,
        "other_equity": <number or null>,
        "total_equity": <number or null>
      }
    },
    "previous": "<same shape if comparable period present, else null>"
  },
  "income_statement": {
    "current": {
      "revenue": <number or null>,
      "revenue_deductions": <number or null>,
      "net_revenue": <number or null>,
      "cogs": <number or null>,
      "gross_profit": <number or null>,
      "financial_income": <number or null>,
      "financial_expense": <number or null>,
      "interest_expense": <number or null>,
      "selling_expense": <number or null>,
      "admin_expense": <number or null>,
      "operating_profit": <number or null>,
      "other_income": <number or null>,
      "other_expense": <number or null>,
      "profit_before_tax": <number or null>,
      "current_tax": <number or null>,
      "deferred_tax": <number or null>,
      "net_profit_after_tax": <number or null>,
      "eps": <number or null>
    },
    "previous": "<same shape if available, else null>"
  },
  "cash_flow": {
    "current": {
      "cf_operating": <number or null>,
      "cf_investing": <number or null>,
      "cf_financing": <number or null>,
      "net_cf": <number or null>,
      "ending_cash": <number or null>
    },
    "previous": "<same shape if available, else null>"
  },
  "raw_transcription": "<verbatim line-by-line extract of the key tables. Include section headers in Vietnamese exactly as printed. Use \\n for line breaks. This is the ground-truth raw read.>",
  "notes": "<any concerns: ambiguous numbers, missing sections, unclear units, illegible cells, etc.>"
}

CRITICAL RULES:
- Use null (not 0) for absent / unreadable values.
- Keep values in the unit shown by the report — do NOT convert. If unit is "triệu đồng" and the cell shows "1.234", value = 1234.
- For Balance Sheet: total_assets MUST equal total_liabilities + total_equity. If not, set "notes" to flag the imbalance.
- Negative values: report as negative numbers (e.g. -1234), NOT as parentheses or strings.
- raw_transcription is mandatory — copy the printed tables verbatim line by line for audit.
"""


def extract(file_path: str) -> dict:
    raw = Path(file_path).read_bytes()
    suffix = Path(file_path).suffix.lower()
    data_b64 = base64.standard_b64encode(raw).decode("utf-8")

    if suffix in _IMAGE_TYPES:
        source_block = {
            "type": "image",
            "source": {"type": "base64", "media_type": _IMAGE_TYPES[suffix], "data": data_b64},
        }
    else:
        source_block = {
            "type": "document",
            "source": {"type": "base64", "media_type": "application/pdf", "data": data_b64},
        }

    t0 = time.time()
    message = _client.messages.create(
        model=_MODEL,
        max_tokens=16000,
        # API yêu cầu temperature=1 khi thinking bật. Trích xuất BCTC ít variance
        # vì Claude đọc cùng numbers từ cùng image → output gần như identical.
        thinking={"type": "adaptive"},
        output_config={"effort": _EFFORT},
        messages=[
            {"role": "user", "content": [source_block, {"type": "text", "text": _PROMPT}]},
        ],
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
            raise ValueError(f"Extractor did not return JSON: {cleaned[:300]!r}")
        parsed = json.loads(match.group(0))

    return {
        "model": _MODEL,
        "elapsed_sec": round(elapsed, 2),
        "input_file": Path(file_path).name,
        "input_size_bytes": len(raw),
        "input_type": suffix,
        "thinking": thinking_text,
        "raw_response": raw_response,
        "financials": parsed,
        "usage": {
            "input_tokens": getattr(message.usage, "input_tokens", None),
            "output_tokens": getattr(message.usage, "output_tokens", None),
        },
    }
