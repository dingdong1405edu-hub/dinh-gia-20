"""Agent 2: LaTeX expression -> computed result."""
import json
import re

import anthropic

_client = anthropic.Anthropic()

_MODEL = "claude-sonnet-4-6"

_PROMPT_TEMPLATE = """You are a precise math solver. Given a LaTeX expression, compute its result.

Input LaTeX:
{latex}

Solve it. Return ONLY a JSON object with these fields, nothing else (no markdown, no explanation):
{{
  "result_latex": "<the final result as a LaTeX expression, no $ delimiters>",
  "result_numeric": "<decimal/numeric value if applicable, or null>",
  "steps": "<brief solution steps in plain text, max 3 short lines>"
}}

Rules:
- If it's an equation (has =), solve for the variable and return the solution.
- If it's an arithmetic expression, return the simplified value.
- If it's an integral/derivative/limit, compute it.
- Be exact: prefer fractions like \\frac{{1}}{{3}} over 0.333.
- result_numeric should be a decimal approximation (string) or null if not meaningful."""


def calculate(latex_expr: str) -> dict:
    prompt = _PROMPT_TEMPLATE.format(latex=latex_expr)
    message = _client.messages.create(
        model=_MODEL,
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    text = message.content[0].text.strip()

    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError(f"Calculator did not return JSON: {text!r}")
    data = json.loads(match.group(0))

    return {
        "expression": latex_expr,
        "result_latex": data.get("result_latex", "").strip(),
        "result_numeric": data.get("result_numeric"),
        "steps": data.get("steps", "").strip(),
    }
