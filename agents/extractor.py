"""Agent 1: Worksheet (PDF/image) -> list of problems."""
import base64
import json
import re
from pathlib import Path

import anthropic

_client = anthropic.Anthropic()
_MODEL = "claude-sonnet-4-6"

_IMAGE_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}

_PROMPT = """This is a math worksheet ("phiếu bài tập toán"), most likely in Vietnamese. \
Extract EVERY exercise/problem in order, top-to-bottom and left-to-right.

Return ONLY a JSON array — no markdown fences, no explanation, no extra text.

Each entry MUST be:
{
  "number": "<the problem's label as a string, e.g. \\"1\\", \\"2a\\", \\"Bài 3\\", \\"Câu 5b\\". Keep the original label verbatim.>",
  "statement_text": "<the problem statement as plain Vietnamese text. For inline math, wrap the LaTeX in $...$. Do NOT include the leading number/label (it's already in 'number'). Keep all sub-questions a), b), c) inside the same string with line breaks if they share a common stem; otherwise split into separate entries.>",
  "statement_math": "<if the entire problem is a single math expression to evaluate/simplify/solve, put just the LaTeX here without $ delimiters; otherwise empty string \\"\\">"
}

Rules:
- Capture EVERY problem you can read, even if handwriting is messy. If unsure, do your best guess and keep going.
- Preserve math exactly: \\frac{a}{b}, x^2, \\sqrt{}, \\int, \\sum, etc.
- Do NOT put Vietnamese text inside \\text{} — keep Vietnamese outside math.
- Strings inside the JSON must escape backslashes properly (\\\\frac, \\\\int).
- Process all pages.
"""


def extract_problems(file_path: str) -> list[dict]:
    raw = Path(file_path).read_bytes()
    suffix = Path(file_path).suffix.lower()
    data_b64 = base64.standard_b64encode(raw).decode("utf-8")

    if suffix in _IMAGE_TYPES:
        source_block = {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": _IMAGE_TYPES[suffix],
                "data": data_b64,
            },
        }
    else:
        source_block = {
            "type": "document",
            "source": {
                "type": "base64",
                "media_type": "application/pdf",
                "data": data_b64,
            },
        }

    message = _client.messages.create(
        model=_MODEL,
        max_tokens=8192,
        messages=[
            {
                "role": "user",
                "content": [source_block, {"type": "text", "text": _PROMPT}],
            }
        ],
    )

    text = message.content[0].text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\[.*\]", text, re.DOTALL)
        if not match:
            raise ValueError(f"Extractor did not return JSON: {text[:300]!r}")
        data = json.loads(match.group(0))

    if not isinstance(data, list):
        raise ValueError(f"Extractor returned non-list: {type(data)}")

    cleaned = []
    for i, p in enumerate(data, 1):
        if not isinstance(p, dict):
            continue
        cleaned.append(
            {
                "number": str(p.get("number") or i),
                "statement_text": (p.get("statement_text") or "").strip(),
                "statement_math": (p.get("statement_math") or "").strip(),
            }
        )
    return cleaned
