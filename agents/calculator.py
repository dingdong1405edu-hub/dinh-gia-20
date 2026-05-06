"""Agent 2: List of problems -> list of solutions, with extended thinking."""
import json
import re
import time

import anthropic

_client = anthropic.Anthropic()
_MODEL = "claude-opus-4-7"
_EFFORT = "high"


def solve(problems: list[dict]) -> dict:
    if not problems:
        return {
            "model": _MODEL,
            "elapsed_sec": 0,
            "thinking": "",
            "raw_response": "",
            "input_problems": [],
            "solutions": [],
            "usage": {"input_tokens": 0, "output_tokens": 0},
        }

    user_prompt = f"""You are a careful, expert Vietnamese math tutor. Solve EACH problem below precisely.

INPUT (JSON list of problems extracted from a worksheet):
{json.dumps(problems, ensure_ascii=False, indent=2)}

Think step by step in your scratchpad. For each problem:
1. Re-read the statement carefully. Distinguish operators and numbers.
2. Identify what is asked: tính (compute), giải (solve), rút gọn (simplify), tìm (find), chứng minh (prove), …
3. Work the math carefully. Verify by substitution or alternate method when possible.
4. Express the final answer.

Then return ONLY this JSON (no markdown fences, no commentary):
{{
  "solutions": [
    {{
      "number": "<copied verbatim from input>",
      "answer_latex": "<final answer as LaTeX without $ delimiters. For equations: 'x = 5' or 'x = 2, x = -3'. For systems: 'x = 1, y = 2'. For simplify: the simplified expression. For prove: 'Đã chứng minh' if shown, else '?'.>",
      "answer_numeric": "<a decimal value as a string like '3.14159', or null if not numerically meaningful>",
      "steps_text": "<concise Vietnamese explanation in 1-3 short sentences. Wrap inline math in $...$. Show the key arithmetic.>",
      "confidence": "<one of: high, medium, low>"
    }}
  ]
}}

CRITICAL ACCURACY RULES:
- Be EXACT. Prefer fractions \\\\frac{{1}}{{3}} over 0.333. Prefer \\\\sqrt{{2}} over 1.414. Prefer \\\\pi over 3.14.
- Verify arithmetic. 2+3=5, NOT 6. 7×8=56, NOT 54. Re-check before answering.
- For equations like 2x+3=11: solve x = (11-3)/2 = 4. Don't skip steps mentally.
- For 'tính' problems: return the final simplified value, not the original expression.
- For 'giải phương trình': return the solution set, not the equation.
- For 'rút gọn': return the simplified expression.
- For multi-part problems (a, b, c) inside one entry, separate with '; ' (e.g. 'a) x=1; b) x=2; c) x=3').
- Do NOT put Vietnamese text inside \\\\text{{}}. Keep Vietnamese outside math.
- If a problem is illegible/incomplete, set answer_latex = "?" and explain in steps_text.
- Set confidence to 'low' if you had to guess at the input or the math is ambiguous.
- Keep steps_text under 280 characters.
"""

    t0 = time.time()
    message = _client.messages.create(
        model=_MODEL,
        max_tokens=16000,
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
            raise ValueError(f"Solver did not return JSON: {cleaned[:300]!r}")
        parsed = json.loads(match.group(0))

    sols_raw = parsed.get("solutions") or []
    solutions = []
    for s in sols_raw:
        if not isinstance(s, dict):
            continue
        solutions.append(
            {
                "number": str(s.get("number", "")),
                "answer_latex": (s.get("answer_latex") or "").strip(),
                "answer_numeric": s.get("answer_numeric"),
                "steps_text": (s.get("steps_text") or "").strip(),
                "confidence": (s.get("confidence") or "medium").strip().lower(),
            }
        )

    return {
        "model": _MODEL,
        "elapsed_sec": round(elapsed, 2),
        "input_problems": problems,
        "thinking": thinking_text,
        "raw_response": raw_response,
        "solutions": solutions,
        "usage": {
            "input_tokens": getattr(message.usage, "input_tokens", None),
            "output_tokens": getattr(message.usage, "output_tokens", None),
        },
    }
