"""Agent 2: List of problems -> list of solutions."""
import json
import re

import anthropic

_client = anthropic.Anthropic()
_MODEL = "claude-sonnet-4-6"


def solve_problems(problems: list[dict]) -> list[dict]:
    if not problems:
        return []

    prompt = f"""You are a careful Vietnamese math tutor. Solve EACH problem below precisely.

Input problems (JSON):
{json.dumps(problems, ensure_ascii=False, indent=2)}

Return ONLY a JSON array — no markdown fences, no explanation, no extra text. \
One entry per input problem, in the SAME ORDER:

[
  {{
    "number": "<copied verbatim from input>",
    "answer_latex": "<the final answer as LaTeX, no $ delimiters. For equations, give the variable solution like 'x = 5' or 'x = 2, x = -3'. For 'rút gọn'/'simplify' problems, give the simplified expression.>",
    "answer_numeric": "<a decimal value as a string like '3.14159', or null if not numerically meaningful>",
    "steps_text": "<concise Vietnamese explanation in 1-3 short sentences. Wrap inline math in $...$.>"
  }},
  ...
]

CRITICAL rules:
- Be EXACT. Prefer fractions \\\\frac{{1}}{{3}} over 0.333. Prefer \\\\sqrt{{2}} over 1.414.
- For 'tính' (compute) -> the simplified value. For 'giải' (solve) -> the variable solution. \
For 'rút gọn' (simplify) -> the simplified expression. For 'tìm' (find) -> the requested object.
- For multi-part problems (a, b, c) inside one entry, separate parts in answer_latex with '; ' \
(e.g. 'a) x=1; b) x=2'). Same for steps_text.
- Do NOT put Vietnamese text inside \\\\text{{}} — keep Vietnamese outside math.
- If a problem is illegible/incomplete, set answer_latex = "?" and explain in steps_text.
- Keep steps_text under 250 characters.
- Double-check arithmetic before returning.
"""

    message = _client.messages.create(
        model=_MODEL,
        max_tokens=8192,
        messages=[{"role": "user", "content": prompt}],
    )
    text = message.content[0].text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\[.*\]", text, re.DOTALL)
        if not match:
            raise ValueError(f"Solver did not return JSON: {text[:300]!r}")
        data = json.loads(match.group(0))

    if not isinstance(data, list):
        raise ValueError(f"Solver returned non-list: {type(data)}")

    cleaned = []
    for s in data:
        if not isinstance(s, dict):
            continue
        cleaned.append(
            {
                "number": str(s.get("number", "")),
                "answer_latex": (s.get("answer_latex") or "").strip(),
                "answer_numeric": s.get("answer_numeric"),
                "steps_text": (s.get("steps_text") or "").strip(),
            }
        )
    return cleaned
