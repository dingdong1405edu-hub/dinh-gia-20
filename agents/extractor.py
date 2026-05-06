"""Agent 1: Scan PDF -> LaTeX expression."""
import base64
from pathlib import Path

import anthropic

_client = anthropic.Anthropic()

_MODEL = "claude-sonnet-4-6"

_PROMPT = (
    "This PDF contains a scanned mathematical expression or equation. "
    "Extract it as a single LaTeX expression. "
    "Rules:\n"
    "- Return ONLY the LaTeX code, nothing else.\n"
    "- Do NOT wrap in $ or $$ delimiters.\n"
    "- Do NOT use markdown code fences.\n"
    "- Do NOT add any explanation.\n"
    "- If multiple expressions are present, pick the main/largest one.\n"
    "- Preserve the original operators exactly (=, +, -, fractions, integrals, etc.)."
)


def extract_latex(pdf_path: str) -> str:
    pdf_data = base64.standard_b64encode(Path(pdf_path).read_bytes()).decode("utf-8")

    message = _client.messages.create(
        model=_MODEL,
        max_tokens=512,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": pdf_data,
                        },
                    },
                    {"type": "text", "text": _PROMPT},
                ],
            }
        ],
    )

    text = message.content[0].text.strip()
    for prefix in ("```latex", "```tex", "```"):
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
    if text.endswith("```"):
        text = text[:-3].strip()
    return text.strip("$").strip()
