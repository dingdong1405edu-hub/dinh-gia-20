"""Agent 1: Worksheet (PDF/image) -> verbatim transcription + structured problem list."""
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

_PROMPT = """You are a meticulous OCR + structuring agent for Vietnamese math worksheets ("phiếu bài tập toán").

Your task has TWO outputs in one JSON response.

(A) "transcription": A complete VERBATIM transcription of every text and math element on the page(s), \
top-to-bottom and left-to-right. Read EVERY character carefully. For math, write exact LaTeX. \
Do NOT skip, summarize, or paraphrase. This is the ground-truth raw read.

(B) "problems": A structured list of every exercise/problem.

Return ONLY this JSON shape (no markdown fences, no commentary):
{
  "transcription": "<the full literal transcription. Use \\n for line breaks. Math wrapped in $...$. \
Vietnamese diacritics preserved exactly.>",
  "problems": [
    {
      "number": "<the original label as a string: '1', '2a', 'Bài 3', 'Câu 5b', etc.>",
      "statement_text": "<the problem statement as Vietnamese text. Inline math wrapped in $...$. \
NO leading number/label. Sub-questions a/b/c sharing a stem stay in this string with \\n separators.>",
      "statement_math": "<if the problem is purely a single math expression to compute/simplify/solve, \
put just the LaTeX (no $); otherwise empty string \\"\\">"
    }
  ]
}

CRITICAL RULES:
- Read carefully. Distinguish: 0/O, 1/l/I, 5/S, x/×, − vs -, ² vs 2.
- Preserve fractions as \\\\frac{a}{b}, exponents as ^{n}, roots as \\\\sqrt{...}, integrals \\\\int, sums \\\\sum.
- Do NOT put Vietnamese inside \\\\text{}; keep Vietnamese OUTSIDE math.
- If you cannot read part of a problem, transcribe what you can and mark the gap with [?] in transcription.
- Capture EVERY numbered problem you can see, even if there are 20+. Process every page.
- For multi-part problems with shared stem, keep them as ONE entry; for clearly separate problems, split.
- Strings in JSON must escape backslashes: \\\\frac, \\\\sqrt, \\\\n.
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

    transcription = (parsed.get("transcription") or "").strip()
    problems_raw = parsed.get("problems") or []
    problems = []
    for i, p in enumerate(problems_raw, 1):
        if not isinstance(p, dict):
            continue
        problems.append(
            {
                "number": str(p.get("number") or i),
                "statement_text": (p.get("statement_text") or "").strip(),
                "statement_math": (p.get("statement_math") or "").strip(),
            }
        )

    return {
        "model": _MODEL,
        "elapsed_sec": round(elapsed, 2),
        "input_file": Path(file_path).name,
        "input_size_bytes": len(raw),
        "input_type": suffix,
        "thinking": thinking_text,
        "raw_response": raw_response,
        "transcription": transcription,
        "problems": problems,
        "usage": {
            "input_tokens": getattr(message.usage, "input_tokens", None),
            "output_tokens": getattr(message.usage, "output_tokens", None),
        },
    }
