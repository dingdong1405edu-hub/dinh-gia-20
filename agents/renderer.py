"""Agent 8: Render báo cáo định giá thành PDF + Excel.

Style tokens (màu, font, size, layout) tách sang agents/report_style.py.
Sửa file đó để đổi look toàn bộ báo cáo.
"""
import json
import textwrap
import time
from datetime import datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager, rcParams
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.patches import FancyBboxPatch, Rectangle

from agents.report_style import (
    COLORS as C,
    SIZES as S,
    LAYOUT as L,
    PRIMARY_FONT,
    FONT_FALLBACKS,
    WEIGHT_HEADER,
    WEIGHT_BODY,
    grade_color as _grade_color_fn,
    rating_color as _rating_color_fn,
)

# Register vendored Vietnamese-supporting fonts (full diacritic coverage).
_FONT_DIR = Path(__file__).resolve().parent.parent / "fonts"
_PRIMARY_FONT_RESOLVED = "DejaVu Sans"
if _FONT_DIR.is_dir():
    for _ttf in sorted(_FONT_DIR.glob("*.ttf")):
        try:
            font_manager.fontManager.addfont(str(_ttf))
        except Exception:
            pass
    _families = {f.name for f in font_manager.fontManager.ttflist}
    if PRIMARY_FONT in _families:
        _PRIMARY_FONT_RESOLVED = PRIMARY_FONT

rcParams["font.family"] = "sans-serif"
rcParams["font.sans-serif"] = [_PRIMARY_FONT_RESOLVED, *FONT_FALLBACKS]
rcParams["mathtext.fontset"] = "cm"
rcParams["axes.unicode_minus"] = False
# Embed TrueType (Type 42) so Vietnamese combining diacritics survive PDF.
rcParams["pdf.fonttype"] = 42
rcParams["ps.fonttype"] = 42
rcParams["pdf.compression"] = 6

A4 = L["page_size"]

GRADE_COLOR = {g: _grade_color_fn(g) for g in "ABCDF"}
RATING_COLOR = {k: _rating_color_fn(k) for k in ("good", "warning", "poor", "n/a")}
RATING_LABEL_VI = {"good": "Tốt", "warning": "TB", "poor": "Kém", "n/a": "—"}

RATIO_LABEL_VI = {
    "current_ratio": "Hệ số TT hiện hành",
    "quick_ratio": "Hệ số TT nhanh",
    "cash_ratio": "Hệ số TT tiền mặt",
    "debt_ratio": "Hệ số nợ / TS",
    "debt_to_equity": "Nợ / VCSH",
    "equity_multiplier": "Hệ số nhân VCSH",
    "interest_coverage": "Khả năng trả lãi vay",
    "debt_to_ebitda": "Nợ / EBITDA",
    "gross_margin": "Biên LN gộp",
    "operating_margin": "Biên LN HĐKD",
    "ebitda_margin": "Biên EBITDA",
    "net_margin": "Biên LN ròng",
    "roa": "ROA",
    "roe": "ROE",
    "asset_turnover": "Vòng quay tổng TS",
    "inventory_turnover": "Vòng quay HTK",
    "receivables_turnover": "Vòng quay phải thu",
}
CATEGORY_LABEL_VI = {
    "liquidity": "Thanh khoản",
    "leverage": "Đòn bẩy / Cơ cấu vốn",
    "profitability": "Khả năng sinh lời",
    "efficiency": "Hiệu quả hoạt động",
}
PERCENT_RATIOS = {"gross_margin", "operating_margin", "ebitda_margin", "net_margin",
                  "roa", "roe", "debt_ratio"}


# ============================ Public API ============================

def _bundle(payload: dict) -> dict:
    """Unwrap pipeline payload into the flat dict each section function expects."""
    return {
        "financials": (payload.get("extracted") or {}).get("financials") or {},
        "industry": (payload.get("industry") or {}).get("industry") or {},
        "business": (payload.get("business") or {}).get("business") or {},
        "ratios": payload.get("ratios") or {},
        "projection": (payload.get("projection") or {}).get("projection") or {},
        "valuation": payload.get("valuation") or {},
        "thesis": (payload.get("thesis") or {}).get("thesis") or {},
    }


# Section registry: (kind, slug, title, builder).
# `builder(bundle)` yields matplotlib Figure objects for that section.
# `kind`  — stable id, dùng cho download URL.
# `slug`  — file name (numeric prefix giữ thứ tự khi liệt kê).
# `title` — tên hiển thị cho user.
SECTIONS = [
    ("cover", "00_cover", "Trang bìa",
     lambda b: [_page_cover(b["financials"], b["valuation"], b["thesis"])]),
    ("executive", "01_executive_summary", "1. Executive Summary",
     lambda b: list(_section_executive_summary(b["financials"], b["valuation"], b["thesis"]))),
    ("thesis", "02_investment_thesis", "2. Investment Thesis",
     lambda b: list(_section_investment_thesis(b["thesis"]))),
    ("company", "03_company_overview", "3. Tổng quan Doanh nghiệp",
     lambda b: list(_section_company_overview(b["financials"], b["business"]))),
    ("industry", "04_industry", "4. Phân tích Ngành",
     lambda b: list(_section_industry(b["industry"]))),
    ("operations", "05_operations", "5. Hoạt động kinh doanh",
     lambda b: list(_section_operations(b["thesis"], b["business"], b["ratios"]))),
    ("financials", "06_financial_statements", "6. Báo cáo tài chính",
     lambda b: list(_section_financial_statements(b["financials"]))),
    ("ratios", "07_ratios", "7. Tỷ số tài chính",
     lambda b: list(_section_ratios(b["ratios"]))),
    ("projections", "08_projections", "8. Dự phóng 5 năm",
     lambda b: list(_section_projections(b["projection"]))),
    ("valuation", "09_valuation", "9. Định giá",
     lambda b: list(_section_valuation(b["valuation"], b["financials"]))),
    ("sensitivity", "10_sensitivity", "10. Sensitivity",
     lambda b: list(_section_sensitivity(b["valuation"]))),
    ("conclusion", "11_conclusion", "11. Kết luận",
     lambda b: list(_section_conclusion(b["thesis"], b["valuation"]))),
    ("appendix", "12_appendix", "12. Phụ lục",
     lambda b: list(_section_appendix(b["valuation"], b["projection"], b["industry"]))),
]


def render_valuation_report(payload: dict, output_path: str) -> dict:
    """Render báo cáo đầy đủ thành 1 file PDF."""
    t0 = time.time()
    bundle = _bundle(payload)
    _reset_report_ctx(bundle.get("financials"))
    pages = 0
    with PdfPages(output_path) as pdf:
        for _kind, _slug, _title, builder in SECTIONS:
            for fig in builder(bundle):
                pdf.savefig(fig)
                plt.close(fig)
                pages += 1
    return {
        "elapsed_sec": round(time.time() - t0, 2),
        "pages": pages,
        "output_path": output_path,
    }


def render_all(payload: dict, output_dir: str, full_pdf_path: str) -> dict:
    """
    Render đồng thời:
      - Full PDF (tất cả mục) tại full_pdf_path.
      - Mỗi mục thành 1 PDF riêng tại output_dir/<slug>.pdf.

    Mỗi figure chỉ build 1 lần rồi ghi vào cả 2 PdfPages → tiết kiệm.
    """
    t0 = time.time()
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    bundle = _bundle(payload)
    _reset_report_ctx(bundle.get("financials"))

    section_files = []
    total_pages = 0
    with PdfPages(full_pdf_path) as full_pdf:
        for kind, slug, title, builder in SECTIONS:
            figs = list(builder(bundle))
            if not figs:
                continue
            section_path = out / f"{slug}.pdf"
            with PdfPages(str(section_path)) as sec_pdf:
                for fig in figs:
                    sec_pdf.savefig(fig)
                    full_pdf.savefig(fig)
                    plt.close(fig)
                    total_pages += 1
            section_files.append({
                "kind": kind,
                "slug": slug,
                "title": title,
                "file_name": section_path.name,
                "pages": len(figs),
                "size_bytes": section_path.stat().st_size,
            })

    return {
        "elapsed_sec": round(time.time() - t0, 2),
        "total_pages": total_pages,
        "section_files": section_files,
        "full_pdf_path": full_pdf_path,
        "full_pdf_size_bytes": Path(full_pdf_path).stat().st_size,
    }


def render_report(trace: dict, output_path: str) -> dict:
    """Debug trace report — input/output của mọi agent."""
    t0 = time.time()
    sections = _trace_sections(trace)
    pages = 0
    with PdfPages(output_path) as pdf:
        pdf.savefig(_report_cover_page(trace)); plt.close("all"); pages += 1
        for title, fields in sections:
            for fig in _section_pages(title, fields):
                pdf.savefig(fig); plt.close(fig); pages += 1
    return {"elapsed_sec": round(time.time() - t0, 2), "pages": pages, "output_path": output_path}


# ============================ Cover ============================

def _page_cover(financials, valuation, thesis):
    """IB-style hero cover: navy band, big title, fair value, metric strip, ribbon."""
    fig = plt.figure(figsize=A4)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.axis("off"); ax.set_xlim(0, 1); ax.set_ylim(0, 1)

    # ============ Top dark navy band (10% height) ============
    ax.add_patch(Rectangle((0, 0.93), 1, 0.07, color=C["primary_dark"],
                           transform=ax.transAxes, zorder=1))
    # Thin gold ribbon strip just below — IB-style elegance.
    ax.add_patch(Rectangle((0, 0.928), 1, 0.003, color=C["ribbon_gold"],
                           transform=ax.transAxes, zorder=2))

    # Eyebrow text on band: "BÁO CÁO ĐỊNH GIÁ" + report id (date) right-aligned.
    ax.text(0.07, 0.965, "B Á O   C Á O   Đ Ị N H   G I Á   D O A N H   N G H I Ệ P",
            ha="left", va="center", fontsize=S["cover_eyebrow"],
            color="#ffffff", fontweight=WEIGHT_HEADER,
            transform=ax.transAxes, zorder=3)
    ax.text(0.93, 0.965,
            datetime.now().strftime("%d / %m / %Y").upper(),
            ha="right", va="center", fontsize=S["cover_eyebrow"],
            color=C["ribbon_gold_light"], fontweight=WEIGHT_HEADER,
            transform=ax.transAxes, zorder=3, family="monospace")

    # ============ Hero — company name (big bold) ============
    ax.text(0.5, 0.84, "VALUATION REPORT",
            ha="center", va="center", fontsize=11,
            color=C["text_muted"], fontweight=WEIGHT_HEADER,
            transform=ax.transAxes)
    # Thin gold accent under report-type label.
    ax.plot([0.42, 0.58], [0.825, 0.825], color=C["ribbon_gold"],
            linewidth=1.2, transform=ax.transAxes)

    company = (_get(financials, "company", "name") or "(Không xác định)").strip()
    # Pick fontsize then wrap width based on it — đảm bảo mỗi line fit trang.
    # Cover content area ~ 0.84 wide. Title 32pt: ~0.032 per char → ~26 chars/line max.
    # Title 28pt: ~0.028 per char → ~30 chars/line max.
    if len(company) <= 26:
        company_lines = [company]
        title_fs = S["cover_title"]
    else:
        company_lines = textwrap.wrap(company, width=30,
                                      break_long_words=False) or [company]
        company_lines = company_lines[:2]
        title_fs = S["cover_title"] - 6  # giảm size khi 2 dòng
    base_y = 0.78 if len(company_lines) == 1 else 0.755
    line_gap = 0.05 if title_fs >= 28 else 0.045
    for i, line in enumerate(company_lines):
        # Final fit guard — nếu line vẫn quá dài thì truncate.
        line_fitted = _fit_text(line, 0.84, title_fs)
        ax.text(0.5, base_y - i * line_gap, line_fitted,
                ha="center", va="center", fontsize=title_fs,
                fontweight=WEIGHT_HEADER, color=C["primary_dark"],
                transform=ax.transAxes)

    # Period · industry · report_type subtitle line.
    period = _get(financials, "period", "current", "label") or ""
    industry_hint = _get(financials, "company", "industry") or ""
    report_type = _get(financials, "company", "report_type") or ""
    subtitle_parts = [p for p in [period, industry_hint, report_type] if p]
    if subtitle_parts:
        subtitle = "  ·  ".join(subtitle_parts).upper()
        ax.text(0.5, 0.685,
                _fit_text(subtitle, 0.84, S["cover_subtitle"]),
                ha="center", va="center", fontsize=S["cover_subtitle"],
                color=C["text_muted"], style="italic",
                transform=ax.transAxes)

    # ============ Fair value hero block ============
    summary = (valuation.get("summary") or {})
    fv_mid = summary.get("fair_value_mid")
    fv_low = summary.get("fair_value_low")
    fv_high = summary.get("fair_value_high")
    unit = financials.get("unit") or ""

    # Outer frame — subtle border, no fill (clean / formal look).
    ax.add_patch(Rectangle((0.10, 0.42), 0.80, 0.18,
                           linewidth=0.8, edgecolor=C["border_strong"],
                           facecolor="none", transform=ax.transAxes))
    # Inner left vertical accent bar (gold).
    ax.add_patch(Rectangle((0.10, 0.42), 0.006, 0.18,
                           color=C["ribbon_gold"], transform=ax.transAxes))

    ax.text(0.5, 0.575, "EQUITY VALUE — FAIR ESTIMATE",
            ha="center", va="center", fontsize=S["cover_value_label"],
            fontweight=WEIGHT_HEADER, color=C["text_muted"],
            transform=ax.transAxes)

    if fv_mid is not None:
        # Fair value 38pt — auto-shrink fontsize tới khi fit khung 0.78 wide.
        fv_text = _fmt_money(fv_mid)
        fv_fs = S["cover_value_amount"]
        while fv_fs > 18 and _est_text_width(fv_text, fv_fs) > 0.78:
            fv_fs -= 2
        # Nếu vẫn quá to ở 18pt thì đổi sang compact format.
        if _est_text_width(fv_text, fv_fs) > 0.78:
            fv_text = _fmt_money_compact(fv_mid, 0.78, fv_fs)
        ax.text(0.5, 0.51, fv_text,
                ha="center", va="center", fontsize=fv_fs,
                fontweight=WEIGHT_HEADER, color=C["primary_dark"],
                transform=ax.transAxes)
        if unit:
            ax.text(0.5, 0.46,
                    _fit_text(unit.upper(), 0.78, S["cover_value_unit"]),
                    ha="center", va="center", fontsize=S["cover_value_unit"],
                    color=C["text_muted"], fontweight=WEIGHT_HEADER,
                    transform=ax.transAxes)
        if fv_low is not None and fv_high is not None:
            range_text = (f"Range: {_fmt_money_compact(fv_low, 0.30, 10)}  —  "
                          f"{_fmt_money_compact(fv_high, 0.30, 10)}")
            ax.text(0.5, 0.435,
                    _fit_text(range_text, 0.78, 10),
                    ha="center", va="center", fontsize=10, color=C["text"],
                    transform=ax.transAxes)
    else:
        ax.text(0.5, 0.50, "(Không đủ dữ liệu định giá)",
                ha="center", va="center", fontsize=14, color=C["text_dim"],
                style="italic", transform=ax.transAxes)

    # ============ Metric strip (3 cols: Doanh thu / LNST / Tổng TS) ============
    is_cur = (financials.get("income_statement") or {}).get("current") or {}
    bs_cur = (financials.get("balance_sheet") or {}).get("current") or {}
    metrics = [
        ("DOANH THU", is_cur.get("net_revenue") or is_cur.get("revenue")),
        ("LỢI NHUẬN SAU THUẾ", is_cur.get("net_profit_after_tax")),
        ("TỔNG TÀI SẢN", _get(bs_cur, "assets", "total_assets")),
    ]
    strip_y = 0.34
    strip_h = 0.06
    ax.add_patch(Rectangle((0.10, strip_y), 0.80, strip_h,
                           color=C["surface_subtle"], transform=ax.transAxes))
    col_w = 0.80 / 3
    for i, (label, value) in enumerate(metrics):
        col_x = 0.10 + (i + 0.5) * col_w
        # Label fit trong cột (~0.25 wide với padding).
        ax.text(col_x, strip_y + strip_h - 0.018,
                _fit_text(label, col_w - 0.02, S["cover_metric_label"]),
                ha="center", va="center", fontsize=S["cover_metric_label"],
                fontweight=WEIGHT_HEADER, color=C["text_muted"],
                transform=ax.transAxes)
        # Value: dùng compact format để không bao giờ overflow cột.
        val_fs = S["cover_metric_value"]
        val_text = (_fmt_money_compact(value, col_w - 0.02, val_fs)
                    if value is not None else "—")
        ax.text(col_x, strip_y + 0.018, val_text,
                ha="center", va="center", fontsize=val_fs,
                fontweight=WEIGHT_HEADER, color=C["primary_dark"],
                transform=ax.transAxes)
        if i < len(metrics) - 1:
            sep_x = 0.10 + (i + 1) * col_w
            ax.plot([sep_x, sep_x], [strip_y + 0.008, strip_y + strip_h - 0.008],
                    color=C["border_strong"], linewidth=0.5, transform=ax.transAxes)

    # ============ Recommendation pill / executive headline ============
    headline = _get(thesis, "executive_summary", "headline") or ""
    rec = _get(thesis, "executive_summary", "recommendation") or ""

    if headline:
        # Center, max 3 lines, italic.
        _draw_block(ax, headline, x=0.10, y=0.27, max_chars=92, max_lines=3,
                    fontsize=10.5, color=C["text"], line_height=0.020)

    if rec:
        # "KHUYẾN NGHỊ" pill + body text.
        ax.add_patch(Rectangle((0.10, 0.165), 0.10, 0.025,
                               color=C["primary_dark"], transform=ax.transAxes))
        ax.text(0.15, 0.1775, "KHUYẾN NGHỊ", ha="center", va="center",
                fontsize=8, fontweight=WEIGHT_HEADER, color="#ffffff",
                transform=ax.transAxes)
        _draw_block(ax, rec, x=0.21, y=0.187, max_chars=78, max_lines=4,
                    fontsize=10.5, color=C["text_strong"], line_height=0.020)

    # ============ Bottom band + footer ============
    ax.add_patch(Rectangle((0, 0), 1, 0.06, color=C["primary_dark"],
                           transform=ax.transAxes, zorder=1))
    ax.add_patch(Rectangle((0, 0.06), 1, 0.003, color=C["ribbon_gold"],
                           transform=ax.transAxes, zorder=2))

    ax.text(0.07, 0.030,
            "PREPARED BY  ·  8-AGENT VALUATION PIPELINE",
            ha="left", va="center", fontsize=S["cover_footer"],
            color="#ffffff", fontweight=WEIGHT_HEADER,
            transform=ax.transAxes, zorder=3)
    ax.text(0.93, 0.030,
            "CLAUDE OPUS 4.7  ·  EXTENDED THINKING",
            ha="right", va="center", fontsize=S["cover_footer"],
            color=C["ribbon_gold_light"], fontweight=WEIGHT_HEADER,
            transform=ax.transAxes, zorder=3, family="monospace")

    return fig


# ============================ 1. Executive Summary ============================

def _section_executive_summary(financials, valuation, thesis):
    fig, ax = _new_page("1. Executive Summary")
    es = thesis.get("executive_summary") or {}
    val_summary = valuation.get("summary") or {}
    is_cur = (financials.get("income_statement") or {}).get("current") or {}
    bs_cur = (financials.get("balance_sheet") or {}).get("current") or {}
    company = financials.get("company") or {}
    industry_name = ""

    y = 0.92
    if es.get("headline"):
        # Headline có thể rất dài → wrap thay vì 1 dòng kéo tràn.
        y = _draw_block(ax, es["headline"], x=0, y=y,
                        max_chars=82, max_lines=3,
                        fontsize=12, color=C["primary"],
                        line_height=0.025)
        y -= 0.025

    # KV grid: 2 cột, mỗi pair (key 0.18 + value 0.30). Auto-fit + auto-truncate.
    y = _draw_kv_grid(ax, [
        ("Doanh nghiệp", company.get("name") or "—"),
        ("MST", company.get("tax_code") or "—"),
        ("Báo cáo", company.get("report_type") or "—"),
        ("Đơn vị", financials.get("unit") or "đồng"),
        ("Doanh thu", _fmt_money(is_cur.get("net_revenue") or is_cur.get("revenue"))),
        ("EBIT (HĐKD)", _fmt_money(is_cur.get("operating_profit"))),
        ("LNST", _fmt_money(is_cur.get("net_profit_after_tax"))),
        ("Tổng tài sản", _fmt_money(_get(bs_cur, "assets", "total_assets"))),
        ("Vốn CSH", _fmt_money(_get(bs_cur, "equity", "total_equity"))),
        ("Nợ phải trả", _fmt_money(_get(bs_cur, "liabilities", "total_liabilities"))),
    ], x=0, y=y, col_widths=[0.18, 0.30], cols=2, line_height=0.030)
    y -= 0.025

    if val_summary.get("method_values"):
        ax.text(0, y, "Kết quả định giá theo phương pháp", fontsize=12,
                fontweight="bold", color=C["primary"], va="top")
        y -= 0.030
        rows = []
        for mv in val_summary["method_values"]:
            rows.append((mv["method"], _fmt_money(mv["equity_value"])))
        rows.append(("Fair value range",
                     f"{_fmt_money(val_summary.get('fair_value_low'))} — {_fmt_money(val_summary.get('fair_value_high'))}"))
        rows.append(("Fair value mid", _fmt_money(val_summary.get("fair_value_mid"))))
        rows.append(("Sau chiết khấu thiểu số ({}%)".format(
            val_summary.get("minority_discount_pct") or 0),
            _fmt_money(val_summary.get("fair_value_after_minority_discount"))))
        y = _draw_simple_table(ax, rows, x=0, y=y,
                               col_widths=[0.55, 0.40], line_height=0.025)
        y -= 0.025

    if es.get("recommendation"):
        ax.text(0, y, "Khuyến nghị", fontsize=12, fontweight="bold",
                color=C["primary"], va="top")
        y -= 0.028
        y = _draw_block(ax, es["recommendation"], x=0, y=y,
                        max_chars=92, max_lines=5, fontsize=11,
                        color=C["text"], line_height=0.022)
        y -= 0.015

    if es.get("key_drivers"):
        ax.text(0, y, "Driver chính của giá trị", fontsize=12,
                fontweight="bold", color=C["primary"], va="top")
        y -= 0.028
        for d in (es["key_drivers"] or [])[:6]:
            if y < 0.04:
                break
            y = _draw_bullet(ax, d, x=0, y=y, fontsize=10,
                             color=C["text"], max_chars=98, max_lines=3,
                             line_height=0.020)
            y -= 0.005
    yield fig


# ============================ 2. Investment Thesis ============================

def _section_investment_thesis(thesis):
    it = thesis.get("investment_thesis") or {}

    fig, ax = _new_page("2. Investment Thesis (Luận điểm đầu tư)")
    y = 0.93
    points = it.get("thesis_points") or []
    if points:
        ax.text(0, y, "Luận điểm chính", fontsize=12,
                fontweight="bold", color=C["primary"], va="top")
        y -= 0.030
        for i, p in enumerate(points[:5], 1):
            if y < 0.10:
                break
            ax.text(0, y, f"{i}. {p.get('title','')}", fontsize=11,
                    fontweight="bold", color="#2563eb", va="top")
            y -= 0.025
            y = _draw_block(ax, p.get("thesis", ""), x=0.02, y=y,
                            max_chars=96, max_lines=4, fontsize=10,
                            color=C["text"], line_height=0.020)
            ev = p.get("evidence", "")
            if ev:
                y -= 0.005
                y = _draw_block(ax, f"Bằng chứng: {ev}", x=0.02, y=y,
                                max_chars=98, max_lines=3, fontsize=9,
                                color=C["text_muted"], line_height=0.018)
            y -= 0.012
    yield fig

    cats = it.get("catalysts") or []
    risks = it.get("risks") or []
    if cats or risks:
        fig2, ax2 = _new_page("2. Investment Thesis — Catalysts & Risks")
        y = 0.93
        if cats:
            ax2.text(0, y, "Catalysts (Yếu tố thúc đẩy giá trị)", fontsize=12,
                     fontweight="bold", color=C["good"], va="top")
            y -= 0.030
            for c in cats[:6]:
                if y < 0.55:
                    break
                title = f"[{(c.get('type') or '?').upper()}] {c.get('description', '')}"
                horizon = c.get("horizon", "")
                if horizon:
                    title += f" — horizon: {horizon}"
                y = _draw_bullet(ax2, title, x=0, y=y, fontsize=10,
                                 color=C["text"], max_chars=98, max_lines=3,
                                 line_height=0.020)
                y -= 0.005
            y -= 0.020

        if risks:
            ax2.text(0, y, "Rủi ro chính", fontsize=12,
                     fontweight="bold", color=C["poor"], va="top")
            y -= 0.030
            for r in risks[:8]:
                if y < 0.04:
                    break
                sev = (r.get("severity") or "").upper()
                sev_color = {"HIGH": C["poor"], "MEDIUM": C["warning"], "LOW": C["good"]}.get(sev, C["text_muted"])
                line = f"[{(r.get('type') or '?').upper()} · {sev}] {r.get('description', '')}"
                y = _draw_bullet(ax2, line, x=0, y=y, fontsize=10,
                                 color=sev_color, max_chars=98, max_lines=3,
                                 line_height=0.020)
                if r.get("mitigation"):
                    y -= 0.002
                    y = _draw_block(ax2, f"Mitigation: {r['mitigation']}", x=0.02, y=y,
                                    max_chars=98, max_lines=2, fontsize=9,
                                    color=C["text_muted"], line_height=0.018)
                y -= 0.008
        yield fig2


# ============================ 3. Company Overview ============================

def _section_company_overview(financials, business):
    company = financials.get("company") or {}
    fig, ax = _new_page("3. Tổng quan Doanh nghiệp")

    y = 0.93
    ax.text(0, y, "3.1. Thông tin cơ bản", fontsize=12,
            fontweight="bold", color=C["primary"], va="top")
    y -= 0.030
    rows = [
        ("Tên DN", company.get("name") or "—"),
        ("Mã số thuế", company.get("tax_code") or "—"),
        ("Địa chỉ", company.get("address") or "—"),
        ("Ngành (BCTC)", company.get("industry") or "—"),
        ("Báo cáo", company.get("report_type") or "—"),
        ("Lịch sử (suy đoán)", business.get("history_inferred") or "Không xác định từ BCTC"),
        ("Cơ cấu sở hữu", business.get("ownership_summary") or "—"),
        ("Ban lãnh đạo", business.get("management") or "—"),
    ]
    y = _draw_simple_table(ax, rows, x=0, y=y, col_widths=[0.25, 0.70], line_height=0.024)
    y -= 0.020

    bm = business.get("business_model") or {}
    ax.text(0, y, "3.2. Mô hình kinh doanh", fontsize=12,
            fontweight="bold", color=C["primary"], va="top")
    y -= 0.030
    y = _draw_block(ax, bm.get("summary") or "", x=0, y=y,
                    max_chars=96, max_lines=4, fontsize=10,
                    color=C["text"], line_height=0.020)
    y -= 0.010
    rows = [
        ("Revenue model", bm.get("revenue_model") or "—"),
        ("Sản phẩm/DV chính", "; ".join((bm.get("products_services") or [])[:5]) or "—"),
        ("Phân khúc KH", "; ".join((bm.get("customer_segments") or [])[:5]) or "—"),
    ]
    y = _draw_simple_table(ax, rows, x=0, y=y, col_widths=[0.25, 0.70], line_height=0.024)
    y -= 0.020

    ue = business.get("unit_economics") or {}
    if ue:
        ax.text(0, y, "Unit economics", fontsize=11,
                fontweight="bold", color=C["text"], va="top")
        y -= 0.025
        rows = [
            ("Biên LN gộp", _fmt_pct_or_dash(ue.get("gross_margin_pct"))),
            ("Biên LN HĐKD", _fmt_pct_or_dash(ue.get("operating_margin_pct"))),
        ]
        y = _draw_simple_table(ax, rows, x=0, y=y, col_widths=[0.25, 0.20],
                               line_height=0.022)
        if ue.get("comments"):
            y = _draw_block(ax, ue["comments"], x=0, y=y,
                            max_chars=96, max_lines=3, fontsize=10,
                            color=C["text"], line_height=0.020)
    yield fig

    fig2, ax2 = _new_page("3. Tổng quan Doanh nghiệp — Chuỗi giá trị")
    vc = business.get("value_chain") or {}
    si = business.get("scale_indicators") or {}
    y = 0.93
    ax2.text(0, y, "3.3. Chuỗi giá trị (Value Chain)", fontsize=12,
             fontweight="bold", color=C["primary"], va="top")
    y -= 0.040
    chain = [
        ("INPUT", vc.get("input") or "—", "#3b82f6"),
        ("PRODUCTION", vc.get("production") or "—", C["good"]),
        ("DISTRIBUTION", vc.get("distribution") or "—", C["warning"]),
        ("CUSTOMER", vc.get("customer") or "—", C["poor"]),
    ]
    box_w = 0.22; box_h = 0.10; gap = 0.025
    start_x = (1 - 4 * box_w - 3 * gap) / 2
    box_y = y - box_h
    for i, (title, body, color) in enumerate(chain):
        x = start_x + i * (box_w + gap)
        ax2.add_patch(FancyBboxPatch((x, box_y), box_w, box_h,
                                      boxstyle="round,pad=0.005,rounding_size=0.008",
                                      linewidth=1.2, edgecolor=color,
                                      facecolor="#fff", transform=ax2.transAxes))
        ax2.text(x + box_w / 2, box_y + box_h - 0.018, title, ha="center",
                 fontsize=10, fontweight="bold", color=color)
        _draw_block(ax2, body, x=x + 0.005, y=box_y + box_h - 0.04,
                    max_chars=24, max_lines=4, fontsize=8.5,
                    color=C["text"], line_height=0.014)
        if i < len(chain) - 1:
            arrow_x = x + box_w
            ax2.annotate("", xy=(arrow_x + gap - 0.005, box_y + box_h / 2),
                         xytext=(arrow_x + 0.005, box_y + box_h / 2),
                         arrowprops=dict(arrowstyle="->", color=C["text_dim"]))
    y = box_y - 0.05

    ax2.text(0, y, "Quy mô & vị thế", fontsize=12,
             fontweight="bold", color=C["primary"], va="top")
    y -= 0.030
    rows = [
        ("Quy mô doanh thu", si.get("revenue_size_class") or "—"),
        ("Số nhân viên ước lượng", si.get("employee_estimate") or "—"),
        ("Mức độ thâm dụng tài sản", si.get("asset_intensity") or "—"),
        ("Vị thế cạnh tranh", business.get("competitive_position") or "—"),
        ("Giai đoạn tăng trưởng", business.get("growth_stage") or "—"),
    ]
    y = _draw_simple_table(ax2, rows, x=0, y=y, col_widths=[0.30, 0.65], line_height=0.024)
    yield fig2


# ============================ 4. Industry ============================

def _section_industry(industry):
    fig, ax = _new_page("4. Phân tích Ngành & Thị trường")
    y = 0.93
    rows = [
        ("Ngành xác định", industry.get("industry_name") or "—"),
        ("Cơ sở phân loại", industry.get("industry_classification_basis") or "—"),
    ]
    y = _draw_simple_table(ax, rows, x=0, y=y, col_widths=[0.25, 0.70], line_height=0.024)
    y -= 0.010
    overview = industry.get("industry_overview")
    if overview:
        y = _draw_block(ax, overview, x=0, y=y, max_chars=96,
                        max_lines=5, fontsize=10,
                        color=C["text"], line_height=0.020)
        y -= 0.020

    ax.text(0, y, "Quy mô thị trường (TAM / SAM / SOM)", fontsize=12,
            fontweight="bold", color=C["primary"], va="top")
    y -= 0.030
    ms = industry.get("market_size") or {}
    rows = [
        ("TAM", _fmt_billion(ms.get("tam_vnd_billion"))),
        ("SAM", _fmt_billion(ms.get("sam_vnd_billion"))),
        ("SOM", _fmt_billion(ms.get("som_vnd_billion"))),
        ("Thị phần ước tính của DN", _fmt_pct_or_dash(ms.get("company_market_share_pct"))),
        ("CAGR ngành 5 năm", _fmt_pct_or_dash(industry.get("industry_cagr_5y_pct"))),
    ]
    y = _draw_simple_table(ax, rows, x=0, y=y, col_widths=[0.40, 0.30], line_height=0.024)
    if ms.get("assumptions"):
        y = _draw_block(ax, f"Giả định: {ms['assumptions']}", x=0, y=y,
                        max_chars=98, max_lines=3, fontsize=9,
                        color=C["text_muted"], line_height=0.018)
        y -= 0.015

    drivers = industry.get("industry_growth_drivers") or []
    trends = industry.get("industry_trends") or []
    if drivers:
        ax.text(0, y, "Driver tăng trưởng", fontsize=11,
                fontweight="bold", color=C["good"], va="top")
        y -= 0.025
        for d in drivers[:5]:
            if y < 0.04:
                break
            y = _draw_bullet(ax, d, x=0, y=y, fontsize=10,
                             color=C["text"], max_chars=98, max_lines=2,
                             line_height=0.020)
            y -= 0.003
        y -= 0.010

    if trends and y > 0.10:
        ax.text(0, y, "Xu hướng nổi bật", fontsize=11,
                fontweight="bold", color="#3b82f6", va="top")
        y -= 0.025
        for t in trends[:5]:
            if y < 0.04:
                break
            y = _draw_bullet(ax, t, x=0, y=y, fontsize=10,
                             color=C["text"], max_chars=98, max_lines=2,
                             line_height=0.020)
            y -= 0.003
    yield fig

    fig2, ax2 = _new_page("4. Phân tích Ngành — Cạnh tranh & Rủi ro")
    y = 0.93
    competitors = industry.get("key_competitors") or []
    if competitors:
        ax2.text(0, y, "Đối thủ cạnh tranh chính", fontsize=12,
                 fontweight="bold", color=C["primary"], va="top")
        y -= 0.030
        # Geometry rõ ràng: name 0.28 | rev 0.16 (right-align) | share 0.12 (right) | note 0.42
        col_name_w  = 0.28
        col_rev_w   = 0.16
        col_share_w = 0.12
        col_note_w  = 1.0 - col_name_w - col_rev_w - col_share_w  # 0.44
        col_name_x  = 0
        col_rev_x   = col_name_x + col_name_w
        col_share_x = col_rev_x + col_rev_w
        col_note_x  = col_share_x + col_share_w
        PAD = 0.005

        # Header row + background.
        ax2.add_patch(Rectangle((0, y - 0.004), 1.0, 0.022,
                                facecolor=C["primary_band"], edgecolor="none",
                                transform=ax2.transAxes, zorder=0))
        ax2.text(col_name_x + PAD, y,
                 _fit_text("Tên DN", col_name_w - 2 * PAD, 9),
                 fontsize=9, fontweight=WEIGHT_HEADER, color=C["primary_dark"],
                 va="top", zorder=2)
        ax2.text(col_rev_x + col_rev_w - PAD, y,
                 _fit_text("Doanh thu ước", col_rev_w - 2 * PAD, 9),
                 fontsize=9, fontweight=WEIGHT_HEADER, color=C["primary_dark"],
                 va="top", ha="right", zorder=2)
        ax2.text(col_share_x + col_share_w - PAD, y,
                 _fit_text("Thị phần", col_share_w - 2 * PAD, 9),
                 fontsize=9, fontweight=WEIGHT_HEADER, color=C["primary_dark"],
                 va="top", ha="right", zorder=2)
        ax2.text(col_note_x + PAD, y,
                 _fit_text("Ghi chú", col_note_w - 2 * PAD, 9),
                 fontsize=9, fontweight=WEIGHT_HEADER, color=C["primary_dark"],
                 va="top", zorder=2)
        y -= 0.022
        ax2.plot([0, 1], [y + 0.004, y + 0.004],
                 color=C["border_strong"], linewidth=0.5, zorder=1)
        y -= 0.003

        for row_idx, c in enumerate(competitors[:8]):
            if y < 0.20:
                break
            name = c.get("name") or "—"
            rev = _fmt_billion(c.get("estimated_revenue_vnd_billion"))
            share = _fmt_pct_or_dash(c.get("market_share_pct"))
            note = c.get("note") or ""
            row_h = 0.030
            if row_idx % 2 == 1:
                ax2.add_patch(Rectangle((0, y - row_h + 0.004), 1.0, row_h,
                                        facecolor=C["surface_alt"], edgecolor="none",
                                        transform=ax2.transAxes, zorder=0))
            # Name (left-align, truncate).
            ax2.text(col_name_x + PAD, y,
                     _fit_text(name, col_name_w - 2 * PAD, 9.5),
                     fontsize=9.5, color=C["text_strong"], fontweight=WEIGHT_HEADER,
                     va="top", zorder=2)
            # Revenue (right-align, truncate).
            ax2.text(col_rev_x + col_rev_w - PAD, y,
                     _fit_text(rev, col_rev_w - 2 * PAD, 9.5),
                     fontsize=9.5, color=C["text"], va="top", ha="right", zorder=2)
            # Share (right-align, truncate).
            ax2.text(col_share_x + col_share_w - PAD, y,
                     _fit_text(share, col_share_w - 2 * PAD, 9.5),
                     fontsize=9.5, color=C["text"], va="top", ha="right", zorder=2)
            # Note — wrapped block constrained to note column width.
            _draw_block(ax2, note, x=col_note_x + PAD, y=y,
                        max_chars=48, max_lines=2,
                        fontsize=8.5, color=C["text_muted"], line_height=0.014)
            y -= row_h
        y -= 0.005

    landscape = industry.get("competitive_landscape")
    if landscape:
        ax2.text(0, y, "Bối cảnh cạnh tranh", fontsize=11,
                 fontweight="bold", color=C["primary"], va="top")
        y -= 0.025
        y = _draw_block(ax2, landscape, x=0, y=y, max_chars=96,
                        max_lines=4, fontsize=10, color=C["text"], line_height=0.020)
        y -= 0.020

    risks = industry.get("industry_risks") or []
    if risks and y > 0.12:
        ax2.text(0, y, "Rủi ro ngành", fontsize=11,
                 fontweight="bold", color=C["poor"], va="top")
        y -= 0.025
        for r in risks[:5]:
            if y < 0.06:
                break
            y = _draw_bullet(ax2, r, x=0, y=y, fontsize=10,
                             color=C["text"], max_chars=98, max_lines=2,
                             line_height=0.020)
            y -= 0.003
        y -= 0.010

    barriers = industry.get("barriers_to_entry") or []
    if barriers and y > 0.08:
        ax2.text(0, y, "Rào cản gia nhập", fontsize=11,
                 fontweight="bold", color=C["text"], va="top")
        y -= 0.025
        for b in barriers[:4]:
            if y < 0.04:
                break
            y = _draw_bullet(ax2, b, x=0, y=y, fontsize=10,
                             color=C["text"], max_chars=98, max_lines=2,
                             line_height=0.020)
            y -= 0.003
    yield fig2


# ============================ 5. Operations ============================

def _section_operations(thesis, business, ratios):
    op = thesis.get("operations_analysis") or {}
    cur = (ratios.get("ratios") or {}).get("current") or {}

    fig, ax = _new_page("5. Phân tích Hoạt động Kinh doanh")
    y = 0.93

    if op.get("revenue_drivers"):
        ax.text(0, y, "Driver doanh thu", fontsize=12,
                fontweight="bold", color=C["primary"], va="top")
        y -= 0.028
        y = _draw_block(ax, op["revenue_drivers"], x=0, y=y,
                        max_chars=96, max_lines=5, fontsize=10,
                        color=C["text"], line_height=0.020)
        y -= 0.012

    if op.get("margin_analysis"):
        ax.text(0, y, "Phân tích biên lợi nhuận", fontsize=12,
                fontweight="bold", color=C["primary"], va="top")
        y -= 0.028
        y = _draw_block(ax, op["margin_analysis"], x=0, y=y,
                        max_chars=96, max_lines=5, fontsize=10,
                        color=C["text"], line_height=0.020)
        y -= 0.012

    profitability = cur.get("profitability") or {}
    if profitability:
        rows = []
        for k in ("gross_margin", "operating_margin", "ebitda_margin", "net_margin"):
            p = profitability.get(k) or {}
            rating = RATING_LABEL_VI.get(p.get("rating", "n/a"))
            value = p.get("value")
            rows.append((RATIO_LABEL_VI.get(k, k),
                         _fmt_ratio(k, value),
                         rating))
        y = _draw_simple_table(ax, rows, x=0, y=y, col_widths=[0.40, 0.20, 0.15],
                               line_height=0.025)
        y -= 0.015

    if op.get("channel_breakdown"):
        ax.text(0, y, "Phân bổ theo kênh / khu vực", fontsize=12,
                fontweight="bold", color=C["primary"], va="top")
        y -= 0.028
        y = _draw_block(ax, op["channel_breakdown"], x=0, y=y,
                        max_chars=96, max_lines=5, fontsize=10,
                        color=C["text"], line_height=0.020)
        y -= 0.012

    obs = op.get("key_metrics_observations") or []
    if obs:
        ax.text(0, y, "Quan sát quan trọng", fontsize=12,
                fontweight="bold", color=C["primary"], va="top")
        y -= 0.028
        for o in obs[:5]:
            if y < 0.04:
                break
            y = _draw_bullet(ax, o, x=0, y=y, fontsize=10,
                             color=C["text"], max_chars=98, max_lines=3,
                             line_height=0.020)
            y -= 0.005
    yield fig


# ============================ 6. Financial Statements ============================

def _section_financial_statements(financials):
    yield _page_balance_sheet(financials)
    yield _page_income_statement(financials)
    if _get(financials, "cash_flow", "current"):
        yield _page_cash_flow(financials)


def _page_balance_sheet(financials):
    fig, ax = _new_page("6.1. Bảng cân đối kế toán")
    unit = financials.get("unit") or "đồng"
    cur_label = _get(financials, "period", "current", "label") or "Kỳ này"
    prev_label = _get(financials, "period", "previous", "label")
    bs_cur = _get(financials, "balance_sheet", "current") or {}
    bs_prev = _get(financials, "balance_sheet", "previous") or {}
    ax.text(0, 0.93, f"Đơn vị: {unit}", fontsize=10, color=C["text_muted"],
            va="top", style="italic")
    rows = []
    a_cur = bs_cur.get("assets") or {}; a_prev = bs_prev.get("assets") if isinstance(bs_prev, dict) else {}
    rows.append(("TÀI SẢN", "header", None, None))
    rows.append(("Tài sản ngắn hạn", "subheader", None, None))
    rows.append(("Tiền và TĐ tiền", 1, a_cur.get("cash_and_equivalents"), a_prev.get("cash_and_equivalents")))
    rows.append(("Đầu tư TC NH", 1, a_cur.get("short_term_investments"), a_prev.get("short_term_investments")))
    rows.append(("Phải thu NH", 1, a_cur.get("short_term_receivables"), a_prev.get("short_term_receivables")))
    rows.append(("Hàng tồn kho", 1, a_cur.get("inventory"), a_prev.get("inventory")))
    rows.append(("TS NH khác", 1, a_cur.get("other_current_assets"), a_prev.get("other_current_assets")))
    rows.append(("Cộng TS NH", "total", a_cur.get("current_assets_total"), a_prev.get("current_assets_total")))
    rows.append(("Tài sản dài hạn", "subheader", None, None))
    rows.append(("Phải thu DH", 1, a_cur.get("long_term_receivables"), a_prev.get("long_term_receivables")))
    rows.append(("TSCĐ", 1, a_cur.get("fixed_assets"), a_prev.get("fixed_assets")))
    rows.append(("BĐS đầu tư", 1, a_cur.get("investment_properties"), a_prev.get("investment_properties")))
    rows.append(("Đầu tư TC DH", 1, a_cur.get("long_term_investments"), a_prev.get("long_term_investments")))
    rows.append(("TS DH khác", 1, a_cur.get("other_non_current_assets"), a_prev.get("other_non_current_assets")))
    rows.append(("Cộng TS DH", "total", a_cur.get("non_current_assets_total"), a_prev.get("non_current_assets_total")))
    rows.append(("TỔNG TÀI SẢN", "grand", a_cur.get("total_assets"), a_prev.get("total_assets")))

    l_cur = bs_cur.get("liabilities") or {}; l_prev = bs_prev.get("liabilities") if isinstance(bs_prev, dict) else {}
    e_cur = bs_cur.get("equity") or {}; e_prev = bs_prev.get("equity") if isinstance(bs_prev, dict) else {}
    rows.append(("NGUỒN VỐN", "header", None, None))
    rows.append(("Nợ ngắn hạn", "subheader", None, None))
    rows.append(("Vay NH", 1, l_cur.get("short_term_debt"), l_prev.get("short_term_debt")))
    rows.append(("Phải trả NB", 1, l_cur.get("accounts_payable"), l_prev.get("accounts_payable")))
    rows.append(("Nợ NH khác", 1, l_cur.get("other_current_liabilities"), l_prev.get("other_current_liabilities")))
    rows.append(("Cộng nợ NH", "total", l_cur.get("current_liabilities_total"), l_prev.get("current_liabilities_total")))
    rows.append(("Nợ dài hạn", "subheader", None, None))
    rows.append(("Vay DH", 1, l_cur.get("long_term_debt"), l_prev.get("long_term_debt")))
    rows.append(("Nợ DH khác", 1, l_cur.get("other_non_current_liabilities"), l_prev.get("other_non_current_liabilities")))
    rows.append(("Cộng nợ DH", "total", l_cur.get("non_current_liabilities_total"), l_prev.get("non_current_liabilities_total")))
    rows.append(("TỔNG NỢ PHẢI TRẢ", "grand", l_cur.get("total_liabilities"), l_prev.get("total_liabilities")))
    rows.append(("Vốn chủ sở hữu", "subheader", None, None))
    rows.append(("Vốn góp CSH", 1, e_cur.get("share_capital"), e_prev.get("share_capital")))
    rows.append(("LN sau thuế chưa PP", 1, e_cur.get("retained_earnings"), e_prev.get("retained_earnings")))
    rows.append(("VCSH khác", 1, e_cur.get("other_equity"), e_prev.get("other_equity")))
    rows.append(("TỔNG VCSH", "grand", e_cur.get("total_equity"), e_prev.get("total_equity")))

    _draw_table(ax, rows, x=0, y=0.89, width=1.0, line_height=0.0205,
                show_prev=bool(bs_prev), cur_label=cur_label,
                prev_label=prev_label or "Kỳ trước")
    return fig


def _page_income_statement(financials):
    fig, ax = _new_page("6.2. Báo cáo Kết quả Kinh doanh")
    unit = financials.get("unit") or "đồng"
    cur_label = _get(financials, "period", "current", "label") or "Kỳ này"
    prev_label = _get(financials, "period", "previous", "label")
    is_cur = _get(financials, "income_statement", "current") or {}
    is_prev = _get(financials, "income_statement", "previous") or {}
    ax.text(0, 0.93, f"Đơn vị: {unit}", fontsize=10, color=C["text_muted"],
            va="top", style="italic")
    rows = [
        ("Doanh thu BH&CCDV", 0, is_cur.get("revenue"), is_prev.get("revenue")),
        ("Các khoản giảm trừ DT", 0, is_cur.get("revenue_deductions"), is_prev.get("revenue_deductions")),
        ("Doanh thu thuần", "total", is_cur.get("net_revenue"), is_prev.get("net_revenue")),
        ("Giá vốn hàng bán", 0, is_cur.get("cogs"), is_prev.get("cogs")),
        ("LỢI NHUẬN GỘP", "grand", is_cur.get("gross_profit"), is_prev.get("gross_profit")),
        ("DT tài chính", 0, is_cur.get("financial_income"), is_prev.get("financial_income")),
        ("Chi phí TC", 0, is_cur.get("financial_expense"), is_prev.get("financial_expense")),
        ("  trong đó: Lãi vay", 1, is_cur.get("interest_expense"), is_prev.get("interest_expense")),
        ("Chi phí bán hàng", 0, is_cur.get("selling_expense"), is_prev.get("selling_expense")),
        ("Chi phí QLDN", 0, is_cur.get("admin_expense"), is_prev.get("admin_expense")),
        ("LN TỪ HĐKD", "grand", is_cur.get("operating_profit"), is_prev.get("operating_profit")),
        ("TN khác", 0, is_cur.get("other_income"), is_prev.get("other_income")),
        ("CP khác", 0, is_cur.get("other_expense"), is_prev.get("other_expense")),
        ("LN TRƯỚC THUẾ", "grand", is_cur.get("profit_before_tax"), is_prev.get("profit_before_tax")),
        ("Thuế TNDN HH", 0, is_cur.get("current_tax"), is_prev.get("current_tax")),
        ("Thuế TNDN HL", 0, is_cur.get("deferred_tax"), is_prev.get("deferred_tax")),
        ("LỢI NHUẬN SAU THUẾ", "grand", is_cur.get("net_profit_after_tax"), is_prev.get("net_profit_after_tax")),
        ("EPS", 0, is_cur.get("eps"), is_prev.get("eps")),
    ]
    _draw_table(ax, rows, x=0, y=0.89, width=1.0, line_height=0.026,
                show_prev=bool(is_prev), cur_label=cur_label,
                prev_label=prev_label or "Kỳ trước")
    return fig


def _page_cash_flow(financials):
    fig, ax = _new_page("6.3. Báo cáo Lưu chuyển Tiền tệ")
    unit = financials.get("unit") or "đồng"
    cur_label = _get(financials, "period", "current", "label") or "Kỳ này"
    prev_label = _get(financials, "period", "previous", "label")
    cf_cur = _get(financials, "cash_flow", "current") or {}
    cf_prev = _get(financials, "cash_flow", "previous") or {}
    ax.text(0, 0.93, f"Đơn vị: {unit}", fontsize=10, color=C["text_muted"],
            va="top", style="italic")
    rows = [
        ("LCTT từ HĐKD", "grand", cf_cur.get("cf_operating"), cf_prev.get("cf_operating")),
        ("LCTT từ HĐ đầu tư", "grand", cf_cur.get("cf_investing"), cf_prev.get("cf_investing")),
        ("LCTT từ HĐ tài chính", "grand", cf_cur.get("cf_financing"), cf_prev.get("cf_financing")),
        ("LCTT thuần trong kỳ", "grand", cf_cur.get("net_cf"), cf_prev.get("net_cf")),
        ("Tiền cuối kỳ", "grand", cf_cur.get("ending_cash"), cf_prev.get("ending_cash")),
    ]
    _draw_table(ax, rows, x=0, y=0.88, width=1.0, line_height=0.034,
                show_prev=bool(cf_prev), cur_label=cur_label,
                prev_label=prev_label or "Kỳ trước")
    return fig


# ============================ 7. Ratios ============================

def _section_ratios(ratios):
    fig, ax = _new_page("7. Phân tích Chỉ số tài chính")
    cur_ratios = (ratios.get("ratios") or {}).get("current") or {}
    prev_ratios = (ratios.get("ratios") or {}).get("previous") or {}
    growth = ratios.get("growth") or {}

    y = 0.93
    if growth:
        ax.text(0, y, "Tăng trưởng (YoY)", fontsize=12,
                fontweight="bold", color=C["primary"], va="top")
        y -= 0.028
        rows = [
            ("Doanh thu thuần", _fmt_pct_signed(growth.get("revenue_yoy"))),
            ("Lợi nhuận gộp", _fmt_pct_signed(growth.get("gross_profit_yoy"))),
            ("EBIT", _fmt_pct_signed(growth.get("ebit_yoy"))),
            ("LNST", _fmt_pct_signed(growth.get("net_income_yoy"))),
            ("Tổng tài sản", _fmt_pct_signed(growth.get("total_assets_yoy"))),
            ("Vốn CSH", _fmt_pct_signed(growth.get("total_equity_yoy"))),
        ]
        y = _draw_simple_table(ax, rows, x=0, y=y, col_widths=[0.40, 0.20], line_height=0.022)
        y -= 0.020

    for cat in ("liquidity", "leverage", "profitability", "efficiency"):
        cat_data = cur_ratios.get(cat) or {}
        if not cat_data or y < 0.10:
            continue
        ax.text(0, y, CATEGORY_LABEL_VI.get(cat, cat).upper(), fontsize=11,
                fontweight="bold", color="#2563eb", va="top")
        y -= 0.022
        ax.text(0, y, "Chỉ tiêu", fontsize=8.5, fontweight="bold", color=C["text_muted"], va="top")
        ax.text(0.50, y, "Kỳ này", fontsize=8.5, fontweight="bold", color=C["text_muted"], va="top", ha="right")
        ax.text(0.65, y, "Kỳ trước", fontsize=8.5, fontweight="bold", color=C["text_muted"], va="top", ha="right")
        ax.text(0.85, y, "Đánh giá", fontsize=8.5, fontweight="bold", color=C["text_muted"], va="top", ha="right")
        y -= 0.014
        ax.plot([0, 0.95], [y + 0.005, y + 0.005], color=C["border"], linewidth=0.5)
        for name, payload in cat_data.items():
            if y < 0.04:
                break
            value = payload.get("value")
            rating = payload.get("rating", "n/a")
            prev_value = ((prev_ratios.get(cat) or {}).get(name) or {}).get("value")
            ax.text(0, y, RATIO_LABEL_VI.get(name, name), fontsize=9.5,
                    color=C["text"], va="top")
            ax.text(0.50, y, _fmt_ratio(name, value), fontsize=9.5,
                    color="#111827", va="top", ha="right")
            ax.text(0.65, y, _fmt_ratio(name, prev_value), fontsize=9.5,
                    color=C["text_muted"], va="top", ha="right")
            box = FancyBboxPatch((0.70, y - 0.014), 0.16, 0.018,
                                 boxstyle="round,pad=0.001,rounding_size=0.004",
                                 linewidth=0,
                                 facecolor=RATING_COLOR.get(rating, C["text_dim"]),
                                 alpha=0.85, transform=ax.transAxes)
            ax.add_patch(box)
            ax.text(0.78, y - 0.005, RATING_LABEL_VI.get(rating, rating),
                    fontsize=8, color="#fff", va="center", ha="center", fontweight="bold")
            y -= 0.018
        y -= 0.010
    yield fig


# ============================ 8. Projections ============================

def _section_projections(projection):
    if not projection:
        return
    fig, ax = _new_page("8. Dự phóng Tài chính 5 năm")
    assumptions = projection.get("assumptions") or {}
    projections = projection.get("projections") or []
    summary = projection.get("summary_5y") or {}

    y = 0.93
    ax.text(0, y, "Giả định chính", fontsize=12,
            fontweight="bold", color=C["primary"], va="top")
    y -= 0.026
    rows = [
        ("Tăng trưởng DT (Y1-Y5)",
         _fmt_pct_list(assumptions.get("revenue_growth_pct"))),
        ("Biên LN gộp (Y1-Y5)",
         _fmt_pct_list(assumptions.get("gross_margin_pct"))),
        ("OPEX % DT (Y1-Y5)",
         _fmt_pct_list(assumptions.get("operating_expense_pct_revenue"))),
        ("Thuế suất", _fmt_pct_or_dash(assumptions.get("tax_rate_pct"))),
        ("D&A % DT", _fmt_pct_or_dash(assumptions.get("depreciation_pct_revenue"))),
        ("CAPEX % DT (Y1-Y5)",
         _fmt_pct_list(assumptions.get("capex_pct_revenue"))),
        ("Working capital days",
         f"{assumptions.get('working_capital_days')}" if assumptions.get("working_capital_days") is not None else "—"),
    ]
    y = _draw_simple_table(ax, rows, x=0, y=y, col_widths=[0.30, 0.65], line_height=0.020)
    y -= 0.005
    if assumptions.get("growth_rationale"):
        y = _draw_block(ax, f"Lý giải tăng trưởng: {assumptions['growth_rationale']}",
                        x=0, y=y, max_chars=98, max_lines=3, fontsize=9,
                        color=C["text_muted"], line_height=0.018)
        y -= 0.012

    if projections:
        ax.text(0, y, "Dự phóng KQKD & FCFF", fontsize=12,
                fontweight="bold", color=C["primary"], va="top")
        y -= 0.024
        # Geometry: label col 0.22, mỗi năm chia đều phần còn lại (max 1.0 - 0.22).
        headers = ["Khoản mục"] + [p.get("year_label", f"Y{i+1}") for i, p in enumerate(projections)]
        cols = len(headers)
        col_w_label = 0.22
        col_w_year = (1.0 - col_w_label) / max(1, cols - 1)
        PAD = 0.005
        # Header row + zebra bg.
        ax.add_patch(Rectangle((0, y - 0.004), 1.0, 0.022,
                               facecolor=C["primary_band"], edgecolor="none",
                               transform=ax.transAxes, zorder=0))
        # Label header.
        ax.text(PAD, y, _fit_text("Khoản mục", col_w_label - 2 * PAD, 9),
                fontsize=9, fontweight=WEIGHT_HEADER, color=C["primary_dark"],
                va="top", zorder=2)
        # Year headers — right-aligned at right edge of each year column.
        for i, h in enumerate(headers[1:]):
            right_edge = col_w_label + (i + 1) * col_w_year - PAD
            ax.text(right_edge, y,
                    _fit_text(str(h), col_w_year - 2 * PAD, 9),
                    fontsize=9, fontweight=WEIGHT_HEADER, color=C["primary_dark"],
                    va="top", ha="right", zorder=2)
        y -= 0.022
        ax.plot([0, 1.0], [y + 0.004, y + 0.004],
                color=C["border_strong"], linewidth=0.5, zorder=1)
        y -= 0.003

        proj_rows = [
            ("Doanh thu",   "revenue",       "money"),
            ("Tăng trưởng", "growth_pct",    "pct"),
            ("LN gộp",      "gross_profit",  "money"),
            ("EBIT",        "ebit",          "money"),
            ("EBITDA",      "ebitda",        "money"),
            ("LNST",        "net_income",    "money"),
            ("CAPEX",       "capex",         "money"),
            ("ΔWC",         "change_in_wc",  "money"),
            ("FCFF",        "fcff",          "highlight"),
        ]
        for row_idx, (label, key, mode) in enumerate(proj_rows):
            if y < 0.10:
                break
            is_highlight = mode == "highlight"
            color = C["primary_dark"] if is_highlight else C["text"]
            fw = WEIGHT_HEADER if is_highlight else WEIGHT_BODY
            fs = 9
            line_h = 0.022
            # Zebra striping for readability (skip highlight row).
            if is_highlight:
                ax.add_patch(Rectangle((0, y - line_h + 0.004), 1.0, line_h,
                                       facecolor=C["primary_light"], edgecolor="none",
                                       transform=ax.transAxes, zorder=0))
            elif row_idx % 2 == 1:
                ax.add_patch(Rectangle((0, y - line_h + 0.004), 1.0, line_h,
                                       facecolor=C["surface_alt"], edgecolor="none",
                                       transform=ax.transAxes, zorder=0))
            # Label.
            ax.text(PAD, y,
                    _fit_text(label, col_w_label - 2 * PAD, fs),
                    fontsize=fs, color=color, fontweight=fw, va="top", zorder=2)
            # Year values — compact format, right-aligned at right edge.
            for i, p in enumerate(projections):
                right_edge = col_w_label + (i + 1) * col_w_year - PAD
                v = p.get(key)
                if mode == "pct":
                    s = _fmt_pct_or_dash(v)
                    s = _fit_text(s, col_w_year - 2 * PAD, fs)
                else:
                    s = _fmt_money_compact(v, col_w_year - 2 * PAD, fs)
                ax.text(right_edge, y, s,
                        fontsize=fs, color=color, fontweight=fw,
                        va="top", ha="right", zorder=2)
            if is_highlight:
                ax.plot([0, 1.0], [y + 0.002, y + 0.002],
                        color=C["primary_dark"], linewidth=0.8, zorder=2)
            y -= line_h
        y -= 0.010

    if summary and y > 0.10:
        ax.text(0, y, "Tổng hợp dự phóng 5 năm", fontsize=12,
                fontweight="bold", color=C["primary"], va="top")
        y -= 0.026
        rows = [
            ("CAGR doanh thu 5Y", _fmt_pct_or_dash(summary.get("revenue_cagr_pct"))),
            ("CAGR EBITDA 5Y", _fmt_pct_or_dash(summary.get("ebitda_cagr_pct"))),
            ("ΣFCFF 5 năm", _fmt_money(summary.get("fcff_cumulative"))),
        ]
        y = _draw_simple_table(ax, rows, x=0, y=y, col_widths=[0.40, 0.30], line_height=0.022)
        if summary.get("comments"):
            y = _draw_block(ax, summary["comments"], x=0, y=y,
                            max_chars=98, max_lines=3, fontsize=10,
                            color=C["text"], line_height=0.020)
    yield fig

    # Chart: revenue/EBITDA/FCFF over 5 years
    if projections:
        fig2 = plt.figure(figsize=A4)
        fig2.suptitle("8. Dự phóng — Biểu đồ", fontsize=16, fontweight="bold",
                      color=C["text_strong"], x=0.08, y=0.96, ha="left")
        ax_rev = fig2.add_axes([0.10, 0.55, 0.80, 0.32])
        years = [p.get("year_label", f"Y{i+1}") for i, p in enumerate(projections)]
        revenues = [p.get("revenue") or 0 for p in projections]
        ebitdas = [p.get("ebitda") or 0 for p in projections]
        fcffs = [p.get("fcff") or 0 for p in projections]
        x = range(len(years))
        ax_rev.bar([i - 0.2 for i in x], revenues, width=0.4, color="#3b82f6", label="Doanh thu")
        ax_rev.bar([i + 0.2 for i in x], ebitdas, width=0.4, color=C["good"], label="EBITDA")
        ax_rev.set_xticks(list(x)); ax_rev.set_xticklabels(years, fontsize=10)
        ax_rev.set_title("Doanh thu vs EBITDA", fontsize=12, fontweight="bold")
        ax_rev.legend(fontsize=9); ax_rev.grid(axis="y", linestyle=":", alpha=0.4)
        ax_fcf = fig2.add_axes([0.10, 0.10, 0.80, 0.32])
        colors_fcf = [C["good"] if v >= 0 else C["poor"] for v in fcffs]
        ax_fcf.bar(years, fcffs, color=colors_fcf)
        for i, v in enumerate(fcffs):
            ax_fcf.text(i, v, _fmt_money(v), ha="center", va="bottom" if v >= 0 else "top",
                        fontsize=9, color=C["text_strong"])
        ax_fcf.set_title("Free Cash Flow to Firm (FCFF)", fontsize=12, fontweight="bold")
        ax_fcf.grid(axis="y", linestyle=":", alpha=0.4)
        ax_fcf.axhline(0, color=C["text"], linewidth=0.5)
        yield fig2


# ============================ 9. Valuation ============================

def _section_valuation(valuation, financials):
    if not valuation:
        return
    assumptions = valuation.get("assumptions") or {}
    dcf = valuation.get("dcf") or {}
    multiples = valuation.get("multiples") or {}
    summary = valuation.get("summary") or {}

    fig, ax = _new_page("9.1. Định giá DCF (FCFF)")
    y = 0.93
    breakdown = assumptions.get("wacc_breakdown") or {}
    rows = [
        ("WACC", _fmt_pct_or_dash(assumptions.get("wacc_pct"))),
        ("  Risk-free rate", _fmt_pct_or_dash(breakdown.get("risk_free_rate_pct"))),
        ("  Equity risk premium", _fmt_pct_or_dash(breakdown.get("equity_risk_premium_pct"))),
        ("  Beta", str(breakdown.get("beta") or "—")),
        ("  Cost of equity", _fmt_pct_or_dash(breakdown.get("cost_of_equity_pct"))),
        ("  Cost of debt", _fmt_pct_or_dash(breakdown.get("cost_of_debt_pct"))),
        ("  Debt weight", _fmt_pct_or_dash(breakdown.get("debt_weight_pct"))),
        ("  Equity weight", _fmt_pct_or_dash(breakdown.get("equity_weight_pct"))),
        ("Terminal growth", _fmt_pct_or_dash(assumptions.get("terminal_growth_pct"))),
    ]
    y = _draw_simple_table(ax, rows, x=0, y=y, col_widths=[0.35, 0.25], line_height=0.022)
    y -= 0.012
    if breakdown.get("rationale"):
        y = _draw_block(ax, f"Lý giải WACC: {breakdown['rationale']}", x=0, y=y,
                        max_chars=98, max_lines=3, fontsize=9,
                        color=C["text_muted"], line_height=0.018)
        y -= 0.010

    pv_breakdown = dcf.get("pv_breakdown") or []
    if pv_breakdown:
        ax.text(0, y, "Chiết khấu FCFF", fontsize=12,
                fontweight="bold", color=C["primary"], va="top")
        y -= 0.024
        ax.text(0, y, "Năm", fontsize=9, fontweight="bold", color=C["text_muted"], va="top")
        ax.text(0.30, y, "FCFF", fontsize=9, fontweight="bold", color=C["text_muted"], va="top", ha="right")
        ax.text(0.55, y, "Discount factor", fontsize=9, fontweight="bold", color=C["text_muted"], va="top", ha="right")
        ax.text(0.85, y, "PV", fontsize=9, fontweight="bold", color=C["text_muted"], va="top", ha="right")
        y -= 0.017
        ax.plot([0, 0.95], [y + 0.005, y + 0.005], color="#d1d5db", linewidth=0.5)
        for row in pv_breakdown:
            if y < 0.20:
                break
            ax.text(0, y, f"Y{row.get('year')}", fontsize=9, color=C["text"], va="top")
            ax.text(0.30, y, _fmt_money(row.get("fcff")), fontsize=9,
                    color=C["text"], va="top", ha="right")
            ax.text(0.55, y, f"{row.get('discount_factor'):.4f}",
                    fontsize=9, color=C["text"], va="top", ha="right")
            ax.text(0.85, y, _fmt_money(row.get("pv")), fontsize=9,
                    color=C["text"], va="top", ha="right")
            y -= 0.020
        y -= 0.005

    rows = [
        ("PV của FCFF dự phóng", _fmt_money(dcf.get("pv_explicit_fcff"))),
        ("Terminal value", _fmt_money(dcf.get("terminal_value"))),
        ("PV of TV", _fmt_money(dcf.get("pv_terminal"))),
        ("Enterprise Value (EV)", _fmt_money(dcf.get("enterprise_value"))),
        ("(-) Nợ phải trả", _fmt_money(dcf.get("debt_subtracted"))),
        ("Equity Value (DCF)", _fmt_money(dcf.get("equity_value"))),
    ]
    y = _draw_simple_table(ax, rows, x=0, y=y, col_widths=[0.45, 0.40], line_height=0.024,
                           highlight_last=True)
    yield fig

    # Multiples page
    fig2, ax2 = _new_page("9.2. Định giá Multiples (EV/EBITDA, P/E, P/B)")
    y = 0.93
    ax2.text(0, y, "Multiples giả định", fontsize=12,
             fontweight="bold", color=C["primary"], va="top")
    y -= 0.026
    rows = [
        ("EV/EBITDA", str(assumptions.get("ev_ebitda_multiple") or "—")),
        ("P/E", str(assumptions.get("pe_multiple") or "—")),
        ("P/B", str(assumptions.get("pb_multiple") or "—")),
    ]
    y = _draw_simple_table(ax2, rows, x=0, y=y, col_widths=[0.30, 0.20], line_height=0.022)
    y -= 0.010
    for k, label in [("ev_ebitda_rationale", "EV/EBITDA"),
                     ("pe_rationale", "P/E"),
                     ("pb_rationale", "P/B")]:
        if assumptions.get(k):
            y = _draw_block(ax2, f"{label}: {assumptions[k]}", x=0, y=y,
                            max_chars=98, max_lines=2, fontsize=9,
                            color=C["text_muted"], line_height=0.018)
            y -= 0.005
    y -= 0.015

    ax2.text(0, y, "Kết quả định giá theo Multiples", fontsize=12,
             fontweight="bold", color=C["primary"], va="top")
    y -= 0.026
    rows = []
    ev_e = multiples.get("ev_ebitda") or {}
    if ev_e.get("equity_value") is not None:
        rows.append(("EV/EBITDA — EBITDA × multiple - Nợ",
                     _fmt_money(ev_e["equity_value"])))
    pe_m = multiples.get("pe") or {}
    if pe_m.get("equity_value") is not None:
        rows.append(("P/E — LNST × multiple", _fmt_money(pe_m["equity_value"])))
    pb_m = multiples.get("pb") or {}
    if pb_m.get("equity_value") is not None:
        rows.append(("P/B — VCSH × multiple", _fmt_money(pb_m["equity_value"])))
    if rows:
        y = _draw_simple_table(ax2, rows, x=0, y=y, col_widths=[0.55, 0.40],
                               line_height=0.024)
    y -= 0.020

    comps = assumptions.get("comparable_companies") or []
    if comps:
        ax2.text(0, y, "Comparable companies (DN niêm yết tương đương)",
                 fontsize=12, fontweight="bold", color=C["primary"], va="top")
        y -= 0.026
        ax2.text(0, y, "Tên DN", fontsize=9, fontweight="bold", color=C["text_muted"], va="top")
        ax2.text(0.40, y, "EV/EBITDA", fontsize=9, fontweight="bold", color=C["text_muted"], va="top", ha="right")
        ax2.text(0.55, y, "P/E", fontsize=9, fontweight="bold", color=C["text_muted"], va="top", ha="right")
        ax2.text(0.70, y, "P/B", fontsize=9, fontweight="bold", color=C["text_muted"], va="top", ha="right")
        ax2.text(0.95, y, "Ghi chú", fontsize=9, fontweight="bold", color=C["text_muted"], va="top", ha="right")
        y -= 0.017
        ax2.plot([0, 0.95], [y + 0.005, y + 0.005], color="#d1d5db", linewidth=0.5)
        for c in comps[:6]:
            if y < 0.05:
                break
            ax2.text(0, y, c.get("name") or "—", fontsize=9, color=C["text"], va="top")
            ax2.text(0.40, y, str(c.get("ev_ebitda") or "—"),
                     fontsize=9, color=C["text"], va="top", ha="right")
            ax2.text(0.55, y, str(c.get("pe") or "—"),
                     fontsize=9, color=C["text"], va="top", ha="right")
            ax2.text(0.70, y, str(c.get("pb") or "—"),
                     fontsize=9, color=C["text"], va="top", ha="right")
            note = (c.get("note") or "")[:40]
            ax2.text(0.95, y, note, fontsize=8.5, color=C["text_muted"], va="top", ha="right")
            y -= 0.022
    yield fig2

    # Summary page
    fig3, ax3 = _new_page("9.4. Tổng hợp Định giá")
    y = 0.93
    method_values = summary.get("method_values") or []
    if method_values:
        ax3.text(0, y, "Kết quả theo từng phương pháp", fontsize=12,
                 fontweight="bold", color=C["primary"], va="top")
        y -= 0.026
        ax3.text(0, y, "Phương pháp", fontsize=9.5, fontweight="bold", color=C["text_muted"], va="top")
        ax3.text(0.55, y, "Equity Value", fontsize=9.5, fontweight="bold", color=C["text_muted"], va="top", ha="right")
        y -= 0.018
        ax3.plot([0, 0.85], [y + 0.005, y + 0.005], color="#d1d5db", linewidth=0.5)
        for mv in method_values:
            if y < 0.30:
                break
            ax3.text(0, y, mv.get("method") or "—", fontsize=10, color=C["text"], va="top")
            ax3.text(0.55, y, _fmt_money(mv.get("equity_value")),
                     fontsize=10, color=C["text"], va="top", ha="right")
            y -= 0.022
        y -= 0.015

    rows = [
        ("Fair value low", _fmt_money(summary.get("fair_value_low"))),
        ("Fair value mid", _fmt_money(summary.get("fair_value_mid"))),
        ("Fair value high", _fmt_money(summary.get("fair_value_high"))),
        ("Chiết khấu cổ đông thiểu số",
         _fmt_pct_or_dash(summary.get("minority_discount_pct"))),
        ("Fair value (sau chiết khấu)",
         _fmt_money(summary.get("fair_value_after_minority_discount"))),
    ]
    y = _draw_simple_table(ax3, rows, x=0, y=y, col_widths=[0.45, 0.40],
                           line_height=0.026, highlight_last=True)
    y -= 0.025

    if assumptions.get("valuation_method_recommendation"):
        ax3.text(0, y, "Phương pháp khuyến nghị", fontsize=12,
                 fontweight="bold", color=C["primary"], va="top")
        y -= 0.024
        y = _draw_block(ax3, assumptions["valuation_method_recommendation"],
                        x=0, y=y, max_chars=98, max_lines=4, fontsize=10,
                        color=C["text"], line_height=0.020)
    yield fig3


# ============================ 10. Sensitivity ============================

def _section_sensitivity(valuation):
    sens = (valuation or {}).get("sensitivity") or {}
    if not sens:
        return
    matrix = sens.get("matrix") or []
    fig, ax = _new_page("10. Phân tích Nhạy cảm (Sensitivity)")
    y = 0.93
    ax.text(0, y, "Bảng độ nhạy: Equity Value theo WACC × Terminal Growth",
            fontsize=11, fontweight="bold", color=C["primary"], va="top")
    y -= 0.034

    growth_axis = sens.get("growth_axis_pct") or []
    if not matrix or not growth_axis:
        ax.text(0, y, "(Không đủ dữ liệu)", fontsize=10,
                color=C["text_dim"], va="top", style="italic")
        yield fig
        return

    cols = len(growth_axis) + 1
    col_w = 0.85 / cols
    start_x = 0.05

    ax.text(start_x, y, "WACC \\ g", fontsize=9, fontweight="bold",
            color=C["text_muted"], va="top")
    for i, g in enumerate(growth_axis):
        x = start_x + (i + 1) * col_w
        ax.text(x + col_w / 2, y, f"g={g}%", fontsize=9,
                fontweight="bold", color=C["text_muted"], va="top", ha="center")
    y -= 0.022

    base_w = sens.get("base_wacc_pct"); base_g = sens.get("base_growth_pct")

    all_values = []
    for row in matrix:
        for v in row.get("values", []):
            ev = v.get("equity_value")
            if isinstance(ev, (int, float)):
                all_values.append(ev)
    vmin = min(all_values) if all_values else 0
    vmax = max(all_values) if all_values else 1
    vrange = vmax - vmin if vmax != vmin else 1

    for row in matrix:
        if y < 0.10:
            break
        w = row.get("wacc_pct")
        ax.text(start_x, y, f"WACC={w}%", fontsize=9,
                fontweight="bold", color=C["text_muted"], va="top")
        for i, v in enumerate(row.get("values", [])):
            x = start_x + (i + 1) * col_w
            ev = v.get("equity_value")
            g_val = v.get("terminal_growth_pct")
            if ev is None:
                color = "#f3f4f6"; label = "—"
            else:
                norm = (ev - vmin) / vrange
                r = int(254 - norm * 70); g = int(243 - norm * 100); b = int(199 + norm * 50)
                color = f"#{r:02x}{g:02x}{b:02x}"
                label = _fmt_money(ev)
            is_base = (abs(w - base_w) < 0.01) and (abs(g_val - base_g) < 0.01)
            ax.add_patch(Rectangle((x, y - 0.020), col_w, 0.020,
                                    facecolor=color,
                                    edgecolor=C["accent"] if is_base else C["border"],
                                    linewidth=1.5 if is_base else 0.5,
                                    transform=ax.transAxes))
            ax.text(x + col_w / 2, y - 0.012, label, fontsize=8.5,
                    color=C["text_strong"], va="center", ha="center",
                    fontweight="bold" if is_base else "normal")
        y -= 0.022
    y -= 0.020

    ax.text(0, y, "Cách đọc", fontsize=11,
            fontweight="bold", color=C["primary"], va="top")
    y -= 0.024
    notes = [
        f"Ô đỏ viền là kịch bản gốc: WACC={base_w}%, g={base_g}%.",
        "Ô càng xanh đậm: equity value càng cao. Ô càng nhạt: equity value càng thấp.",
        "WACC tăng → equity value giảm. Terminal growth tăng → equity value tăng (nếu g < WACC).",
    ]
    for n in notes:
        if y < 0.05:
            break
        y = _draw_bullet(ax, n, x=0, y=y, fontsize=9.5,
                         color=C["text"], max_chars=98, max_lines=2,
                         line_height=0.018)
        y -= 0.005
    yield fig


# ============================ 11. Conclusion ============================

def _section_conclusion(thesis, valuation):
    deal = thesis.get("deal_recommendation") or {}
    val_summary = (valuation or {}).get("summary") or {}
    val_comm = thesis.get("valuation_commentary") or {}

    fig, ax = _new_page("11. Kết luận & Khuyến nghị")
    y = 0.93

    if val_comm.get("method_comparison"):
        ax.text(0, y, "So sánh phương pháp", fontsize=12,
                fontweight="bold", color=C["primary"], va="top")
        y -= 0.026
        y = _draw_block(ax, val_comm["method_comparison"], x=0, y=y,
                        max_chars=98, max_lines=4, fontsize=10,
                        color=C["text"], line_height=0.020)
        y -= 0.015

    if val_comm.get("fair_value_view"):
        ax.text(0, y, "Quan điểm về giá trị hợp lý", fontsize=12,
                fontweight="bold", color=C["primary"], va="top")
        y -= 0.026
        y = _draw_block(ax, val_comm["fair_value_view"], x=0, y=y,
                        max_chars=98, max_lines=4, fontsize=10,
                        color=C["text"], line_height=0.020)
        y -= 0.015

    rows = [
        ("Mục tiêu chính", deal.get("primary_objective") or "—"),
        ("Khoảng giá trị hợp lý", deal.get("fair_value_range_text") or
         f"{_fmt_money(val_summary.get('fair_value_low'))} — {_fmt_money(val_summary.get('fair_value_high'))}"),
        ("Đề xuất giá vào (entry price)",
         deal.get("entry_price_recommendation") or "—"),
        ("Cấu trúc deal", deal.get("deal_structure") or "—"),
    ]
    y = _draw_simple_table(ax, rows, x=0, y=y, col_widths=[0.30, 0.65], line_height=0.026)
    y -= 0.015

    governance = deal.get("post_deal_governance") or []
    if governance:
        ax.text(0, y, "Quản trị sau deal", fontsize=12,
                fontweight="bold", color=C["primary"], va="top")
        y -= 0.026
        for g in governance[:5]:
            if y < 0.10:
                break
            y = _draw_bullet(ax, g, x=0, y=y, fontsize=10,
                             color=C["text"], max_chars=98, max_lines=2,
                             line_height=0.020)
            y -= 0.005
        y -= 0.010

    next_steps = deal.get("next_steps") or []
    if next_steps:
        ax.text(0, y, "Bước tiếp theo", fontsize=12,
                fontweight="bold", color=C["good"], va="top")
        y -= 0.026
        for i, s in enumerate(next_steps[:6], 1):
            if y < 0.05:
                break
            y = _draw_bullet(ax, f"{i}. {s}", x=0, y=y, fontsize=10,
                             color=C["text"], max_chars=98, max_lines=3,
                             line_height=0.020)
            y -= 0.005
    yield fig


# ============================ 12. Appendix ============================

def _section_appendix(valuation, projection, industry):
    assumptions_v = (valuation or {}).get("assumptions") or {}
    assumptions_p = (projection or {}).get("assumptions") or {}

    fig, ax = _new_page("12. Phụ lục — Giả định & Tham số")
    y = 0.93
    ax.text(0, y, "12.1. Giả định Định giá", fontsize=12,
            fontweight="bold", color=C["primary"], va="top")
    y -= 0.026
    rows = [
        ("WACC", _fmt_pct_or_dash(assumptions_v.get("wacc_pct"))),
        ("Terminal growth", _fmt_pct_or_dash(assumptions_v.get("terminal_growth_pct"))),
        ("EV/EBITDA multiple", str(assumptions_v.get("ev_ebitda_multiple") or "—")),
        ("P/E multiple", str(assumptions_v.get("pe_multiple") or "—")),
        ("P/B multiple", str(assumptions_v.get("pb_multiple") or "—")),
        ("Chiết khấu thiểu số", _fmt_pct_or_dash(assumptions_v.get("minority_discount_pct"))),
    ]
    y = _draw_simple_table(ax, rows, x=0, y=y, col_widths=[0.40, 0.30], line_height=0.022)
    y -= 0.020

    ax.text(0, y, "12.2. Giả định Dự phóng", fontsize=12,
            fontweight="bold", color=C["primary"], va="top")
    y -= 0.026
    rows = [
        ("Tăng trưởng DT (Y1-Y5)",
         _fmt_pct_list(assumptions_p.get("revenue_growth_pct"))),
        ("Biên LN gộp (Y1-Y5)",
         _fmt_pct_list(assumptions_p.get("gross_margin_pct"))),
        ("OPEX % DT (Y1-Y5)",
         _fmt_pct_list(assumptions_p.get("operating_expense_pct_revenue"))),
        ("CAPEX % DT (Y1-Y5)",
         _fmt_pct_list(assumptions_p.get("capex_pct_revenue"))),
        ("Thuế suất", _fmt_pct_or_dash(assumptions_p.get("tax_rate_pct"))),
        ("D&A % DT", _fmt_pct_or_dash(assumptions_p.get("depreciation_pct_revenue"))),
        ("WC days", str(assumptions_p.get("working_capital_days") or "—")),
    ]
    y = _draw_simple_table(ax, rows, x=0, y=y, col_widths=[0.30, 0.65], line_height=0.022)
    y -= 0.020

    ax.text(0, y, "12.3. Comparable Companies", fontsize=12,
            fontweight="bold", color=C["primary"], va="top")
    y -= 0.026
    comps = assumptions_v.get("comparable_companies") or []
    if comps:
        for c in comps[:8]:
            if y < 0.08:
                break
            y = _draw_bullet(ax,
                f"{c.get('name')} — EV/EBITDA={c.get('ev_ebitda') or '—'}, P/E={c.get('pe') or '—'}, P/B={c.get('pb') or '—'}",
                x=0, y=y, fontsize=9.5, color=C["text"],
                max_chars=98, max_lines=2, line_height=0.018)
            y -= 0.003
    else:
        ax.text(0, y, "(Không có)", fontsize=10, color=C["text_dim"], va="top", style="italic")
    yield fig


# ============================ Helpers — page templates ============================

# Module-level state for running header / page counter.
# Reset by render_valuation_report() / render_all() / render_report() at start.
_REPORT_CTX: dict = {
    "company": "",          # tên DN — show ở running header
    "period": "",           # kỳ — show ở running header
    "page_no": 0,           # trang content hiện tại (cover không tính)
}


def _reset_report_ctx(financials: dict | None = None):
    """Gọi ở đầu mỗi render để reset page counter + lấy company info."""
    _REPORT_CTX["page_no"] = 0
    if financials:
        company = (_get(financials, "company", "name") or "").strip()
        period = _get(financials, "period", "current", "label") or ""
        _REPORT_CTX["company"] = company[:50]  # truncate dài quá
        _REPORT_CTX["period"] = period
    else:
        _REPORT_CTX["company"] = ""
        _REPORT_CTX["period"] = ""


def _new_page(title: str):
    """IB-style content page: thin running header + content area + footer with page #.

    Running header (small caps): company name (left) · section title (center) · page # (right)
    Footer: gold accent + report identifier left + page count right
    """
    _REPORT_CTX["page_no"] += 1
    page_no = _REPORT_CTX["page_no"]
    company = _REPORT_CTX["company"] or "—"
    period = _REPORT_CTX["period"]

    fig = plt.figure(figsize=A4)
    # Slightly more generous content margins for a refined feel.
    ml, mr = 0.075, 0.075
    mt, mb = 0.07, 0.06
    ax = fig.add_axes([ml, mb, 1 - ml - mr, 1 - mt - mb])
    ax.axis("off"); ax.set_xlim(0, 1); ax.set_ylim(0, 1)

    # =========== RUNNING HEADER (top of content area, above page) ===========
    # Three-segment line at top — company | section | page no.
    # Drawn in figure coordinates so they align outside the content axes too.
    fig.text(0.075, 0.967, company.upper(),
             fontsize=S["running_header"], color=C["text_muted"],
             fontweight=WEIGHT_HEADER, ha="left", va="center")
    if period:
        fig.text(0.5, 0.967, period.upper(),
                 fontsize=S["running_header"], color=C["text_muted"],
                 ha="center", va="center", style="italic")
    fig.text(0.925, 0.967, f"PAGE {page_no:02d}",
             fontsize=S["running_header"], color=C["text_muted"],
             fontweight=WEIGHT_HEADER, ha="right", va="center",
             family="monospace")
    # Hairline rule under running header.
    fig.add_artist(plt.Line2D([0.075, 0.925], [0.957, 0.957],
                              color=C["border_strong"], linewidth=0.5))

    # =========== SECTION TITLE BAR (inside content area) ===========
    # Gold + navy double-block bên trái + tiêu đề UPPERCASE (truncated nếu cần).
    ax.add_patch(Rectangle((0, 0.953), 0.008, 0.030,
                           facecolor=C["ribbon_gold"], edgecolor="none",
                           transform=ax.transAxes))
    ax.add_patch(Rectangle((0.008, 0.953), 0.008, 0.030,
                           facecolor=C["primary_dark"], edgecolor="none",
                           transform=ax.transAxes))
    # Title fit vào content area (sau accent block 0.024, đến 0.98 chừa lề phải).
    title_max_w = 0.95
    ax.text(0.024, 0.968,
            _fit_text(title.upper(), title_max_w, S["page_title"]),
            fontsize=S["page_title"], fontweight=WEIGHT_HEADER,
            color=C["primary_dark"], va="center")
    # Rule chính + gold accent — TẤT CẢ cùng x range (0 → 1) cho thẳng.
    ax.plot([0, 1], [0.945, 0.945], color=C["primary_dark"], linewidth=1.0,
            transform=ax.transAxes)
    ax.plot([0, 0.12], [0.945, 0.945], color=C["ribbon_gold"], linewidth=1.6,
            transform=ax.transAxes)

    # =========== FOOTER ===========
    fig.text(0.075, 0.030, "BÁO CÁO ĐỊNH GIÁ DOANH NGHIỆP",
             fontsize=S["footnote"], color=C["text_muted"],
             fontweight=WEIGHT_HEADER, ha="left", va="center")
    fig.text(0.5, 0.030, datetime.now().strftime("%d/%m/%Y"),
             fontsize=S["footnote"], color=C["text_dim"],
             ha="center", va="center", style="italic")
    fig.text(0.925, 0.030, f"— {page_no} —",
             fontsize=S["footnote"], color=C["text_muted"],
             ha="right", va="center", family="monospace")
    fig.add_artist(plt.Line2D([0.075, 0.925], [0.044, 0.044],
                              color=C["border_strong"], linewidth=0.5))
    fig.add_artist(plt.Line2D([0.075, 0.16], [0.046, 0.046],
                              color=C["ribbon_gold"], linewidth=1.2))

    return fig, ax


# ============================ Helpers — drawing ============================

def _draw_block(ax, text, x, y, fontsize, color, max_chars, max_lines, line_height):
    """Multi-line wrapped paragraph. Mỗi line được hard-clip bởi _fit_text để
    nếu textwrap tạo line dài hơn max_chars dự kiến (vd: 1 từ không bẻ được),
    line đó vẫn không tràn sang vùng khác.

    Width an toàn = max_chars × char_w. Nếu dòng wrap dài quá thì truncate.
    Cuối line wrapping: nếu có >max_lines dòng, dòng cuối thêm "…" để báo
    text bị cắt.
    """
    if not text:
        return y
    # Hard-cap width per line based on fontsize and intended max_chars.
    safe_width = max_chars * fontsize * _CHAR_WIDTH_PER_PT
    # Some prefix space (e.g. bullet indent) may already have eaten width; use
    # current x as offset (assume target right edge = 1.0).
    available = max(0.05, min(safe_width, 1.0 - x - 0.01))

    lines: list[str] = []
    for paragraph in str(text).split("\n"):
        if not paragraph.strip():
            lines.append("")
            continue
        wrapped = textwrap.wrap(paragraph, width=max_chars,
                                break_long_words=False, break_on_hyphens=False)
        lines.extend(wrapped or [""])

    truncated = len(lines) > max_lines
    visible = lines[:max_lines]
    for i, line in enumerate(visible):
        # Mark "…" on last visible line if there's more.
        if i == max_lines - 1 and truncated:
            line = (line + " …") if line else "…"
        # Per-line hard clip (catches stubborn long words / non-wrappable text).
        line = _fit_text(line, available, fontsize)
        ax.text(x, y - i * line_height, line, fontsize=fontsize,
                color=color, va="top")
    return y - len(visible) * line_height


def _draw_bullet(ax, text, x, y, fontsize, color, max_chars, max_lines, line_height):
    ax.text(x, y, "•", fontsize=fontsize + 1, color=color,
            va="top", fontweight="bold")
    return _draw_block(ax, str(text), x=x + 0.018, y=y,
                       fontsize=fontsize, color=color,
                       max_chars=max_chars, max_lines=max_lines,
                       line_height=line_height)


def _draw_simple_table(ax, rows, x, y, col_widths, line_height, highlight_last=False):
    """K/V table with zebra striping. Mỗi ô được FIT vào col_width (truncate nếu cần).

    Numeric-looking cells right-align. Padding 0.006 mỗi bên trong ô để tránh
    sát mép. Last row (totals): bold + primary band + rule above.
    """
    total_w = sum(col_widths)
    PAD = 0.006  # padding mỗi bên trong ô — quan trọng để text không sát viền
    for idx, row in enumerate(rows):
        if y < 0.04:
            break
        is_last = highlight_last and idx == len(rows) - 1

        # Zebra striping background.
        if not is_last and idx % 2 == 1:
            ax.add_patch(Rectangle((x, y - line_height + 0.004),
                                   total_w, line_height,
                                   facecolor=C["surface_alt"], edgecolor="none",
                                   transform=ax.transAxes, zorder=0))
        elif is_last:
            ax.add_patch(Rectangle((x, y - line_height + 0.004),
                                   total_w, line_height,
                                   facecolor=C["primary_band"], edgecolor="none",
                                   transform=ax.transAxes, zorder=0))

        cur_x = x
        for i, cell in enumerate(row):
            w = col_widths[i] if i < len(col_widths) else 0.20
            inner_w = max(0.02, w - 2 * PAD)
            text = "" if cell is None else str(cell)
            color = C["primary_dark"] if is_last else C["text"]
            fw = WEIGHT_HEADER if (is_last or i == 0) else WEIGHT_BODY
            fs = 10.5 if is_last else 10
            ha = "right" if (i == len(row) - 1 and i > 0 and _looks_numeric(text)) else "left"
            # Truncate text to fit inside cell — prevents collision với cell kế bên.
            display = _fit_text(text, inner_w, fs)
            tx = cur_x + (w - PAD) if ha == "right" else cur_x + PAD
            ax.text(tx, y, display, fontsize=fs, color=color,
                    fontweight=fw, va="top", ha=ha, zorder=2)
            cur_x += w
        if is_last:
            ax.plot([x, x + total_w], [y + 0.002, y + 0.002],
                    color=C["primary_dark"], linewidth=1, zorder=2)
        y -= line_height
    return y


def _looks_numeric(text: str) -> bool:
    """True nếu chuỗi nhìn như con số / tỷ lệ — để right-align trong table."""
    if not text or text == "—":
        return False
    s = text.strip()
    stripped = s.replace(".", "").replace(",", "").replace("%", "").replace(" ", "")
    stripped = stripped.lstrip("+-").rstrip("x").rstrip("X")
    return stripped.isdigit() if stripped else False


def _draw_kv_grid(ax, items, x, y, col_widths, cols=2, line_height=0.028):
    """Key/value grid with proper truncation. Auto-derives column geometry
    based on number of cols + available width (0..1) so it never overflows.

    col_widths = [key_w, value_w] mỗi cell. Mỗi pair (k, v) chiếm
    (key_w + value_w). Gap giữa các pair được tính tự động để vừa width.
    """
    if cols < 1:
        cols = 1
    pair_w = col_widths[0] + col_widths[1]
    # Available total width = 1 - x. Tính gap để N pair vừa.
    available = max(0.0, 1.0 - x)
    if cols == 1:
        gap = 0.0
        pair_w = min(pair_w, available)
    else:
        # N pair + (N-1) gap = available
        gap = max(0.01, (available - cols * pair_w) / (cols - 1))
        if gap > 0.06:
            gap = 0.06  # cap nếu thừa width
    key_fs = 9
    val_fs = 10
    key_inner = col_widths[0] - 0.005
    val_inner = col_widths[1] - 0.005
    PAD = 0.003
    for i, (k, v) in enumerate(items):
        col = i % cols
        row = i // cols
        cx = x + col * (pair_w + gap)
        cy = y - row * line_height
        # Key (light grey, small)
        ax.text(cx + PAD, cy,
                _fit_text(str(k), key_inner, key_fs),
                fontsize=key_fs, color=C["text_muted"], va="top")
        # Value (strong, bold) — truncate hoặc compact cho number-like.
        v_str = str(v) if v is not None else "—"
        # Nếu là số formatted (chỉ chứa số + dấu chấm/phẩy/dấu trừ) → compact.
        if v_str and v_str != "—" and v_str.replace(".", "").replace(",", "").replace("-", "").replace("+", "").isdigit():
            try:
                num_val = float(v_str.replace(".", "").replace(",", "."))
                v_str = _fmt_money_compact(num_val, val_inner, val_fs)
            except ValueError:
                v_str = _fit_text(v_str, val_inner, val_fs)
        else:
            v_str = _fit_text(v_str, val_inner, val_fs)
        ax.text(cx + col_widths[0] + PAD, cy, v_str,
                fontsize=val_fs, color=C["text_strong"], va="top",
                fontweight=WEIGHT_HEADER)
    rows = (len(items) + cols - 1) // cols
    return y - rows * line_height


def _draw_table(ax, rows, x, y, width, line_height, show_prev, cur_label, prev_label):
    """Financial-statement table với column geometry CỐ ĐỊNH (label + cur + prev + Δ%).

    Mỗi cell được fit/compact để không bao giờ overflow. Số rất to tự động chuyển
    sang format compact "1,23 tỷ". Label dài tự cắt với ellipsis.

    Geometry (assuming width=1.0):
      - Label column:    x      → 0.42       (42% — đủ chỗ tên khoản mục)
      - Current period:  0.42   → 0.62       (20% — số kỳ này, right-align ở 0.62)
      - Previous period: 0.62   → 0.82       (20% — số kỳ trước, right-align ở 0.82)
      - Δ %:             0.82   → 0.99       (17% — phần trăm chênh, right-align ở 0.99)
    """
    PAD = 0.006
    # Column right edges (right-aligned text ENDS at these x).
    label_x_start = x + PAD
    label_max_w   = width * 0.41 - PAD                       # đủ chỗ cho label, dừng trước cur col
    cur_right     = x + width * 0.62
    cur_max_w     = width * 0.20 - PAD * 2                    # số tự fit trong 20%
    prev_right    = x + width * 0.82
    prev_max_w    = width * 0.20 - PAD * 2
    chg_right     = x + width * 0.99
    chg_max_w     = width * 0.17 - PAD * 2

    # Header row.
    ax.text(label_x_start, y,
            _fit_text("Khoản mục", label_max_w, 9),
            fontsize=9, fontweight="bold", color=C["text_muted"], va="top")
    ax.text(cur_right, y,
            _fit_text(cur_label, cur_max_w, 9),
            fontsize=9, fontweight="bold", color=C["text_muted"], va="top", ha="right")
    if show_prev:
        ax.text(prev_right, y,
                _fit_text(prev_label, prev_max_w, 9),
                fontsize=9, fontweight="bold", color=C["text_muted"], va="top", ha="right")
        ax.text(chg_right, y, "Δ%", fontsize=9, fontweight="bold",
                color=C["text_muted"], va="top", ha="right")
    y -= line_height
    ax.plot([x, x + width], [y + 0.003, y + 0.003],
            color=C["border_strong"], linewidth=0.7)
    y -= 0.005

    for label, level, cv, pv in rows:
        if y < 0.04:
            break
        # Section sub-headers (TÀI SẢN / NGUỒN VỐN / Tài sản ngắn hạn …).
        if level == "header":
            ax.text(label_x_start, y,
                    _fit_text(label, width - 2 * PAD, 11),
                    fontsize=11, fontweight="bold",
                    color=C["text_strong"], va="top")
            y -= line_height
            continue
        if level == "subheader":
            ax.text(label_x_start + 0.005, y,
                    _fit_text(label, width - 2 * PAD, 10),
                    fontsize=10, fontweight="bold",
                    color=C["text"], va="top", style="italic")
            y -= line_height
            continue
        # Leaf rows.
        if level == "grand":
            font_w = "bold"; color = C["text_strong"]; fs = 10
        elif level == "total":
            font_w = "bold"; color = C["text"]; fs = 9.5
        else:
            font_w = "normal"; color = C["text"]; fs = 9
            label = "  " + label

        # Label — fit to label_max_w.
        ax.text(label_x_start, y,
                _fit_text(label, label_max_w, fs),
                fontsize=fs, fontweight=font_w, color=color, va="top")
        # Current period — auto-compact format if number too wide for cell.
        ax.text(cur_right, y,
                _fmt_money_compact(cv, cur_max_w, fs),
                fontsize=fs, fontweight=font_w, color=color,
                va="top", ha="right")
        if show_prev:
            ax.text(prev_right, y,
                    _fmt_money_compact(pv, prev_max_w, fs),
                    fontsize=fs, color=C["text_muted"],
                    va="top", ha="right")
            chg_pct = _percent_change(cv, pv)
            chg_color = C["text"]
            if chg_pct is not None:
                chg_color = C["good"] if chg_pct > 0 else (C["poor"] if chg_pct < 0 else C["text_muted"])
            ax.text(chg_right, y,
                    _fit_text(_fmt_pct_signed_pct(chg_pct), chg_max_w, fs - 0.5),
                    fontsize=fs - 0.5, color=chg_color,
                    va="top", ha="right")
        if level == "grand":
            ax.plot([x, x + width], [y - 0.002, y - 0.002],
                    color=C["text_dim"], linewidth=0.5)
        y -= line_height


# ============================ Helpers — formatting ============================

def _fmt_money(value):
    if value is None:
        return "—"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)
    if v == 0:
        return "0"
    sign = "-" if v < 0 else ""
    s = f"{int(abs(v)):,}".replace(",", ".")
    return sign + s


# ---------- Text-fitting helpers (to prevent text overflow / overlap) ----------
# Heuristic: char width in axes-normalized coords [0..1] for an axes occupying
# ~85% of A4 width. At fontsize=10pt, avg char ≈ 5pt = 5/72 inch ≈ 0.069 inch.
# Axes width = 0.85 × 8.27 inch ≈ 7.03 inch → 1 char ≈ 0.0099 of axes width.
_CHAR_WIDTH_PER_PT = 0.00099  # axes-normalized width per char per pt fontsize


def _est_text_width(text: str, fontsize: float) -> float:
    """Estimate axes-normalized width of `text` at `fontsize` (in pt)."""
    if not text:
        return 0.0
    return len(str(text)) * fontsize * _CHAR_WIDTH_PER_PT


def _fit_text(text, max_width: float, fontsize: float, ellipsis: str = "…") -> str:
    """Truncate text with ellipsis to fit `max_width` (axes-normalized)."""
    s = "" if text is None else str(text)
    if not s or max_width <= 0:
        return ""
    if _est_text_width(s, fontsize) <= max_width:
        return s
    char_w = fontsize * _CHAR_WIDTH_PER_PT
    if char_w <= 0:
        return s
    n_max = max(1, int((max_width / char_w) - len(ellipsis)))
    if n_max >= len(s):
        return s
    return s[:n_max].rstrip() + ellipsis


def _fmt_money_compact(value, max_width: float, fontsize: float) -> str:
    """Format money — auto-scales to tỷ / triệu / nghìn nếu format đầy đủ
    quá rộng so với max_width."""
    full = _fmt_money(value)
    if value is None or full == "—" or full == "0":
        return full
    if _est_text_width(full, fontsize) <= max_width:
        return full
    try:
        v = float(value)
    except (TypeError, ValueError):
        return _fit_text(full, max_width, fontsize)
    abs_v = abs(v)
    sign = "-" if v < 0 else ""
    # Try compact formats from biggest to smallest divisor.
    for divisor, suffix in [
        (1e12, " ng.tỷ"),  # nghìn tỷ
        (1e9,  " tỷ"),
        (1e6,  " tr"),
        (1e3,  " k"),
    ]:
        if abs_v >= divisor:
            scaled = abs_v / divisor
            # Pick precision that fits.
            for fmt in ["{:,.2f}", "{:,.1f}", "{:,.0f}"]:
                candidate = f"{sign}{fmt.format(scaled)}{suffix}".replace(",", ".")
                if _est_text_width(candidate, fontsize) <= max_width:
                    return candidate
            break
    # Last resort: truncate the full string.
    return _fit_text(full, max_width, fontsize)


def _fmt_billion(value):
    if value is None:
        return "—"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)
    return f"{v:,.1f} tỷ".replace(",", ".")


def _fmt_pct_or_dash(value):
    if value is None:
        return "—"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)
    return f"{v:.2f}%"


def _fmt_pct_signed(value):
    """Input is a fraction (0.08 = 8%), returns '+8.00%' or '-8.00%'."""
    if value is None:
        return "—"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)
    return f"{v * 100:+.2f}%"


def _fmt_pct_signed_pct(value):
    """Input already in percent (vd 8 = 8%), returns '+8.0%'."""
    if value is None:
        return "—"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)
    return f"{v:+.1f}%"


def _fmt_pct_list(values):
    if not values:
        return "—"
    return " · ".join(f"{v:.1f}%" if isinstance(v, (int, float)) else "—" for v in values)


def _fmt_ratio(name, value):
    if value is None:
        return "—"
    if name in PERCENT_RATIOS:
        return f"{value * 100:.2f}%"
    return f"{value:.2f}"


def _percent_change(current, previous):
    if current is None or previous is None:
        return None
    try:
        c = float(current); p = float(previous)
    except (TypeError, ValueError):
        return None
    if p == 0:
        return None
    return (c - p) / abs(p) * 100


def _get(d, *path):
    cur = d
    for k in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    return cur


# ============================ Debug report ============================

def _trace_sections(trace: dict):
    sections = []
    sections.append(("Tổng quan", [
        ("Job ID", trace.get("job_id", "?")),
        ("Created", trace.get("created_at", "?")),
        ("Pipeline duration", f"{trace.get('total_elapsed_sec', '?')} s"),
    ]))

    for key, name in [
        ("agent1_extract", "Agent 1 — Extractor"),
        ("agent2_industry", "Agent 2 — Industry Analyst"),
        ("agent3_business", "Agent 3 — Business Profile"),
        ("agent4_ratios", "Agent 4 — Ratios & Growth"),
        ("agent5_projector", "Agent 5 — Projector"),
        ("agent6_valuator", "Agent 6 — Valuator"),
        ("agent7_thesis", "Agent 7 — Thesis Writer"),
    ]:
        a = trace.get(key) or {}
        meta = []
        if a.get("model"):
            meta.append(("Model", a.get("model")))
        if a.get("elapsed_sec") is not None:
            meta.append(("Elapsed (s)", str(a.get("elapsed_sec"))))
        usage = a.get("usage") or {}
        if usage.get("input_tokens") is not None:
            meta.append(("Input tokens", str(usage.get("input_tokens"))))
        if usage.get("output_tokens") is not None:
            meta.append(("Output tokens", str(usage.get("output_tokens"))))
        if a.get("thinking"):
            meta.append(("Thinking trace", a.get("thinking")))
        if a.get("raw_response"):
            meta.append(("Raw response", a.get("raw_response")))
        meta.append(("Full payload",
                     json.dumps({k: v for k, v in a.items()
                                 if k not in ("thinking", "raw_response")},
                                ensure_ascii=False, indent=2)))
        if meta:
            sections.append((name, meta))
    return sections


def _report_cover_page(trace):
    fig = plt.figure(figsize=A4)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.axis("off"); ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    ax.text(0.5, 0.72, "Báo cáo Debug", ha="center", va="center",
            fontsize=30, fontweight="bold", color="#111827")
    ax.text(0.5, 0.66, "Trace input + output mọi agent",
            ha="center", va="center", fontsize=14, color=C["text_muted"])
    ax.plot([0.20, 0.80], [0.62, 0.62], color=C["accent"], linewidth=2)
    ax.text(0.5, 0.55, f"Job: {trace.get('job_id','?')}",
            ha="center", va="center", fontsize=12, color=C["text"])
    ax.text(0.5, 0.50, datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
            ha="center", va="center", fontsize=11, color=C["text_dim"])
    return fig


def _section_pages(title, fields):
    lines = []
    for name, value in fields:
        lines.append(("__field__", name))
        for chunk in _wrap_block(str(value or ""), width=92):
            lines.append(("body", chunk))
        lines.append(("body", ""))
    page_capacity = 50
    for chunk_start in range(0, len(lines), page_capacity):
        chunk = lines[chunk_start:chunk_start + page_capacity]
        yield _make_section_page(title, chunk)


def _make_section_page(title, lines):
    fig = plt.figure(figsize=A4)
    ax = fig.add_axes([0.07, 0.05, 0.86, 0.92])
    ax.axis("off"); ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    ax.text(0, 0.98, title, fontsize=16, fontweight="bold",
            color=C["accent"], va="top")
    ax.plot([0, 1], [0.955, 0.955], color="#fee2e2", linewidth=1)
    y = 0.93
    line_h = 0.018
    for kind, content in lines:
        if y < 0.04:
            break
        if kind == "__field__":
            y -= 0.005
            ax.text(0, y, content, fontsize=11, fontweight="bold",
                    color=C["text_strong"], va="top")
            y -= line_h
        else:
            ax.text(0, y, content, fontsize=8.5, color=C["text"],
                    va="top", family="monospace")
            y -= line_h
    return fig


def _wrap_block(text, width):
    out = []
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
