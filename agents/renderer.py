"""Agent 3: Render answers PDF + debug report PDF."""
import json
import re
import textwrap
import time
from datetime import datetime

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import rcParams
from matplotlib.backends.backend_pdf import PdfPages

rcParams["font.family"] = "DejaVu Sans"
rcParams["mathtext.fontset"] = "cm"
rcParams["axes.unicode_minus"] = False

A4 = (8.27, 11.69)


# -------- Public API --------

def render_answers(problems: list[dict], solutions: list[dict], output_path: str) -> dict:
    t0 = time.time()
    sol_by_num = {str(s.get("number")): s for s in solutions}

    pages = 0
    with PdfPages(output_path) as pdf:
        pdf.savefig(_cover_page(len(problems)))
        plt.close("all")
        pages += 1

        for prob in problems:
            sol = sol_by_num.get(str(prob.get("number")), {})
            fig = _problem_page(prob, sol)
            pdf.savefig(fig)
            plt.close(fig)
            pages += 1

    return {
        "elapsed_sec": round(time.time() - t0, 2),
        "pages": pages,
        "input_problems_count": len(problems),
        "input_solutions_count": len(solutions),
        "output_path": output_path,
    }


def render_report(trace: dict, output_path: str) -> dict:
    t0 = time.time()

    sections: list[tuple[str, list[tuple[str, str]]]] = []

    overview = [
        ("Job ID", trace.get("job_id", "?")),
        ("Created", trace.get("created_at", "?")),
        ("Input file", f"{trace['agent1'].get('input_file','?')} ({trace['agent1'].get('input_size_bytes',0)} bytes, {trace['agent1'].get('input_type','?')})"),
        ("Total problems", str(len(trace["agent1"].get("problems", [])))),
        ("Total solutions", str(len(trace["agent2"].get("solutions", [])))),
        ("Pipeline duration", f"{trace.get('total_elapsed_sec', '?')} s"),
        ("Models", f"A1={trace['agent1'].get('model')}, A2={trace['agent2'].get('model')}"),
    ]
    sections.append(("Tổng quan", overview))

    a1 = trace["agent1"]
    sections.append(("Agent 1 — INPUT", [
        ("File", a1.get("input_file", "?")),
        ("Type", a1.get("input_type", "?")),
        ("Size (bytes)", str(a1.get("input_size_bytes", "?"))),
    ]))
    sections.append(("Agent 1 — OUTPUT (transcription)", [
        ("Transcription", a1.get("transcription", "")),
    ]))
    sections.append(("Agent 1 — OUTPUT (problems JSON)", [
        ("Problems", json.dumps(a1.get("problems", []), ensure_ascii=False, indent=2)),
    ]))
    sections.append(("Agent 1 — meta", [
        ("Model", a1.get("model", "?")),
        ("Elapsed (s)", str(a1.get("elapsed_sec", "?"))),
        ("Input tokens", str(a1.get("usage", {}).get("input_tokens", "?"))),
        ("Output tokens", str(a1.get("usage", {}).get("output_tokens", "?"))),
        ("Thinking trace", a1.get("thinking", "") or "(none)"),
    ]))

    a2 = trace["agent2"]
    sections.append(("Agent 2 — INPUT (problems)", [
        ("Problems", json.dumps(a2.get("input_problems", []), ensure_ascii=False, indent=2)),
    ]))
    sections.append(("Agent 2 — OUTPUT (solutions JSON)", [
        ("Solutions", json.dumps(a2.get("solutions", []), ensure_ascii=False, indent=2)),
    ]))
    sections.append(("Agent 2 — meta", [
        ("Model", a2.get("model", "?")),
        ("Elapsed (s)", str(a2.get("elapsed_sec", "?"))),
        ("Input tokens", str(a2.get("usage", {}).get("input_tokens", "?"))),
        ("Output tokens", str(a2.get("usage", {}).get("output_tokens", "?"))),
        ("Thinking trace", a2.get("thinking", "") or "(none)"),
    ]))

    a3 = trace["agent3"]
    sections.append(("Agent 3 — INPUT", [
        ("Problems count", str(a3.get("input_problems_count", "?"))),
        ("Solutions count", str(a3.get("input_solutions_count", "?"))),
    ]))
    sections.append(("Agent 3 — OUTPUT", [
        ("Output PDF", a3.get("output_path", "?")),
        ("Pages", str(a3.get("pages", "?"))),
        ("Elapsed (s)", str(a3.get("elapsed_sec", "?"))),
    ]))

    pages = 0
    with PdfPages(output_path) as pdf:
        pdf.savefig(_report_cover_page(trace))
        plt.close("all")
        pages += 1

        for title, fields in sections:
            for fig in _section_pages(title, fields):
                pdf.savefig(fig)
                plt.close(fig)
                pages += 1

    return {
        "elapsed_sec": round(time.time() - t0, 2),
        "pages": pages,
        "output_path": output_path,
    }


# -------- Answer pages --------

def _cover_page(count: int):
    fig = plt.figure(figsize=A4)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.axis("off"); ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    ax.text(0.5, 0.72, "Đáp án phiếu bài tập", ha="center", va="center",
            fontsize=30, fontweight="bold", color="#111827")
    ax.plot([0.25, 0.75], [0.66, 0.66], color="#2563eb", linewidth=2)
    ax.text(0.5, 0.60, f"{count} câu hỏi", ha="center", va="center",
            fontsize=18, color="#6b7280")
    ax.text(0.5, 0.52, datetime.now().strftime("%d/%m/%Y %H:%M"),
            ha="center", va="center", fontsize=12, color="#9ca3af")
    ax.text(0.5, 0.05, "Generated by 3-agent Math Solver",
            ha="center", va="center", fontsize=9, color="#9ca3af", style="italic")
    return fig


def _problem_page(prob: dict, sol: dict):
    fig = plt.figure(figsize=A4)
    ax = fig.add_axes([0.08, 0.05, 0.84, 0.9])
    ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")

    label = prob.get("number") or "?"
    ax.text(0, 0.97, f"Bài {label}", fontsize=22, fontweight="bold", color="#2563eb", va="top")
    conf = (sol.get("confidence") or "").lower()
    if conf == "low":
        ax.text(1, 0.97, "⚠ độ tin cậy thấp", ha="right", va="top", fontsize=10, color="#dc2626")
    elif conf == "medium":
        ax.text(1, 0.97, "độ tin cậy trung bình", ha="right", va="top", fontsize=9, color="#d97706")
    ax.plot([0, 1], [0.935, 0.935], color="#e5e7eb", linewidth=1)

    ax.text(0, 0.91, "Đề bài", fontsize=12, fontweight="bold", color="#374151", va="top")
    statement = prob.get("statement_text") or ""
    if not statement and prob.get("statement_math"):
        statement = f"${_sanitize_math(prob['statement_math'])}$"
    next_y = _draw_wrapped(ax, statement, x=0, y=0.87, fontsize=13, color="#111827",
                           max_chars=78, max_lines=10, line_height=0.026)

    answer_y = min(next_y - 0.04, 0.55)
    ax.text(0, answer_y, "Đáp án", fontsize=12, fontweight="bold", color="#374151", va="top")

    ans_latex = (sol.get("answer_latex") or "").strip()
    if ans_latex and ans_latex != "?":
        try:
            ax.text(0.5, answer_y - 0.06, f"${_sanitize_math(ans_latex)}$",
                    fontsize=22, ha="center", va="top", color="#10b981")
        except Exception:
            ax.text(0.5, answer_y - 0.06, ans_latex,
                    fontsize=18, ha="center", va="top", color="#10b981")
    else:
        ax.text(0.5, answer_y - 0.06, "Không xác định", fontsize=16, ha="center", va="top",
                color="#dc2626", style="italic")

    if sol.get("answer_numeric"):
        ax.text(0.5, answer_y - 0.13, f"≈ {sol['answer_numeric']}",
                fontsize=13, ha="center", va="top", color="#6b7280")

    steps_y = answer_y - 0.22
    ax.text(0, steps_y, "Lời giải", fontsize=12, fontweight="bold", color="#374151", va="top")
    steps = (sol.get("steps_text") or "").strip()
    if steps:
        _draw_wrapped(ax, steps, x=0, y=steps_y - 0.04, fontsize=11, color="#374151",
                      max_chars=88, max_lines=10, line_height=0.023)
    else:
        ax.text(0, steps_y - 0.04, "(không có)", fontsize=11, color="#9ca3af",
                va="top", style="italic")

    return fig


# -------- Report pages --------

def _report_cover_page(trace: dict):
    fig = plt.figure(figsize=A4)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.axis("off"); ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    ax.text(0.5, 0.72, "Báo cáo Debug", ha="center", va="center",
            fontsize=30, fontweight="bold", color="#111827")
    ax.text(0.5, 0.66, "Trace input + output từng agent",
            ha="center", va="center", fontsize=14, color="#6b7280")
    ax.plot([0.20, 0.80], [0.62, 0.62], color="#dc2626", linewidth=2)
    ax.text(0.5, 0.55, f"Job: {trace.get('job_id','?')}",
            ha="center", va="center", fontsize=12, color="#374151")
    ax.text(0.5, 0.50, datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
            ha="center", va="center", fontsize=11, color="#9ca3af")
    ax.text(0.5, 0.05, "Generated by 3-agent Math Solver",
            ha="center", va="center", fontsize=9, color="#9ca3af", style="italic")
    return fig


def _section_pages(title: str, fields: list[tuple[str, str]]):
    """Yield Figure pages for one section. Long fields are paginated."""
    lines: list[tuple[str, str]] = []
    for name, value in fields:
        lines.append(("__field__", name))
        for chunk in _wrap_block(str(value or ""), width=92):
            lines.append(("body", chunk))
        lines.append(("body", ""))

    page_capacity = 50
    for chunk_start in range(0, len(lines), page_capacity):
        chunk = lines[chunk_start:chunk_start + page_capacity]
        yield _make_section_page(title, chunk)


def _make_section_page(title: str, lines: list[tuple[str, str]]):
    fig = plt.figure(figsize=A4)
    ax = fig.add_axes([0.07, 0.05, 0.86, 0.92])
    ax.axis("off"); ax.set_xlim(0, 1); ax.set_ylim(0, 1)

    ax.text(0, 0.98, title, fontsize=16, fontweight="bold", color="#dc2626", va="top")
    ax.plot([0, 1], [0.955, 0.955], color="#fee2e2", linewidth=1)

    y = 0.93
    line_h = 0.018
    for kind, content in lines:
        if y < 0.04:
            break
        if kind == "__field__":
            y -= 0.005
            ax.text(0, y, content, fontsize=11, fontweight="bold",
                    color="#1f2937", va="top")
            y -= line_h
        else:
            ax.text(0, y, content, fontsize=8.5, color="#374151",
                    va="top", family="monospace")
            y -= line_h
    return fig


def _wrap_block(text: str, width: int) -> list[str]:
    """Hard-wrap arbitrary text including JSON / code, preserving line breaks."""
    out: list[str] = []
    if not text:
        out.append("")
        return out
    for line in text.split("\n"):
        if not line:
            out.append("")
            continue
        out.extend(textwrap.wrap(line, width=width,
                                 replace_whitespace=False,
                                 drop_whitespace=False,
                                 break_long_words=True,
                                 break_on_hyphens=False) or [""])
    return out


# -------- Helpers --------

def _sanitize_math(s: str) -> str:
    s = s.strip().strip("$").strip()
    s = re.sub(r"\\text\{([^}]*)\}", r"\\mathrm{\1}", s)
    return s


def _draw_wrapped(ax, text: str, x: float, y: float,
                  fontsize: int, color: str,
                  max_chars: int, max_lines: int,
                  line_height: float) -> float:
    if not text:
        return y

    placeholders: list[str] = []

    def stash(m: re.Match) -> str:
        placeholders.append(m.group(0))
        return f"\x00M{len(placeholders)-1}\x00"

    masked = re.sub(r"\$[^$\n]+\$", stash, text)

    lines: list[str] = []
    for paragraph in masked.split("\n"):
        if not paragraph.strip():
            lines.append("")
            continue
        wrapped = textwrap.wrap(paragraph, width=max_chars,
                                break_long_words=False, break_on_hyphens=False)
        lines.extend(wrapped or [""])

    def restore(line: str) -> str:
        return re.sub(r"\x00M(\d+)\x00",
                      lambda m: placeholders[int(m.group(1))], line)

    for i, line in enumerate(lines[:max_lines]):
        ax.text(x, y - i * line_height, restore(line),
                fontsize=fontsize, color=color, va="top")

    return y - len(lines[:max_lines]) * line_height
