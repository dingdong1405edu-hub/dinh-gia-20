"""Agent 8: Render 12-section SME Valuation Report PDF + debug report."""
import json
import textwrap
import time
from datetime import datetime

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import rcParams
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.patches import FancyBboxPatch, Rectangle

rcParams["font.family"] = "DejaVu Sans"
rcParams["mathtext.fontset"] = "cm"
rcParams["axes.unicode_minus"] = False

A4 = (8.27, 11.69)

GRADE_COLOR = {"A": "#10b981", "B": "#22c55e", "C": "#f59e0b",
               "D": "#f97316", "F": "#ef4444"}
RATING_COLOR = {"good": "#10b981", "warning": "#f59e0b", "poor": "#ef4444", "n/a": "#9ca3af"}
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

def render_valuation_report(payload: dict, output_path: str) -> dict:
    """
    payload = {
      "extracted": {financials, raw_response, thinking, ...},
      "industry": {industry: {...}, ...},
      "business": {business: {...}, ...},
      "ratios": {ratios, growth},
      "projection": {projection: {...}, ...},
      "valuation": {assumptions, dcf, multiples, sensitivity, summary, ...},
      "thesis": {thesis: {...}, ...},
    }
    """
    t0 = time.time()
    financials = (payload.get("extracted") or {}).get("financials") or {}
    industry = (payload.get("industry") or {}).get("industry") or {}
    business = (payload.get("business") or {}).get("business") or {}
    ratios = payload.get("ratios") or {}
    projection = (payload.get("projection") or {}).get("projection") or {}
    valuation = payload.get("valuation") or {}
    thesis = (payload.get("thesis") or {}).get("thesis") or {}

    pages = 0
    with PdfPages(output_path) as pdf:
        for fig in _build_pages(financials, industry, business, ratios,
                                projection, valuation, thesis):
            pdf.savefig(fig)
            plt.close(fig)
            pages += 1

    return {
        "elapsed_sec": round(time.time() - t0, 2),
        "pages": pages,
        "output_path": output_path,
    }


def render_report(trace: dict, output_path: str) -> dict:
    """Debug trace report — input/output of every agent."""
    t0 = time.time()
    sections = _trace_sections(trace)
    pages = 0
    with PdfPages(output_path) as pdf:
        pdf.savefig(_report_cover_page(trace)); plt.close("all"); pages += 1
        for title, fields in sections:
            for fig in _section_pages(title, fields):
                pdf.savefig(fig); plt.close(fig); pages += 1
    return {"elapsed_sec": round(time.time() - t0, 2), "pages": pages, "output_path": output_path}


# ============================ Page builder ============================

def _build_pages(financials, industry, business, ratios, projection, valuation, thesis):
    yield _page_cover(financials, valuation, thesis)
    yield from _section_executive_summary(financials, valuation, thesis)
    yield from _section_investment_thesis(thesis)
    yield from _section_company_overview(financials, business)
    yield from _section_industry(industry)
    yield from _section_operations(thesis, business, ratios)
    yield from _section_financial_statements(financials)
    yield from _section_ratios(ratios)
    yield from _section_projections(projection)
    yield from _section_valuation(valuation, financials)
    yield from _section_sensitivity(valuation)
    yield from _section_conclusion(thesis, valuation)
    yield from _section_appendix(valuation, projection, industry)


# ============================ Cover ============================

def _page_cover(financials, valuation, thesis):
    fig = plt.figure(figsize=A4)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.axis("off"); ax.set_xlim(0, 1); ax.set_ylim(0, 1)

    ax.add_patch(Rectangle((0, 0.96), 1, 0.04, color="#1e3a8a", transform=ax.transAxes))
    ax.add_patch(Rectangle((0, 0), 1, 0.03, color="#1e3a8a", transform=ax.transAxes))

    ax.text(0.5, 0.88, "BÁO CÁO ĐỊNH GIÁ DOANH NGHIỆP",
            ha="center", va="top", fontsize=22, fontweight="bold", color="#1e3a8a")
    ax.text(0.5, 0.83, "SME Valuation Report",
            ha="center", va="top", fontsize=13, color="#6b7280", style="italic")
    ax.plot([0.18, 0.82], [0.81, 0.81], color="#1e3a8a", linewidth=2.5)

    company = (_get(financials, "company", "name") or "(Không xác định)").strip()
    ax.text(0.5, 0.74, company, ha="center", va="top",
            fontsize=20, fontweight="bold", color="#1e3a8a")

    period = _get(financials, "period", "current", "label") or ""
    if period:
        ax.text(0.5, 0.685, f"Kỳ phân tích: {period}", ha="center", va="top",
                fontsize=13, color="#374151")

    industry_name = ""
    rt = _get(financials, "company", "report_type")
    if rt:
        industry_name = rt
    if industry_name:
        ax.text(0.5, 0.65, industry_name, ha="center", va="top",
                fontsize=11, color="#6b7280", style="italic")

    summary = (valuation.get("summary") or {})
    fv_mid = summary.get("fair_value_mid")
    fv_low = summary.get("fair_value_low")
    fv_high = summary.get("fair_value_high")
    unit = financials.get("unit") or ""

    box_y = 0.42
    ax.add_patch(FancyBboxPatch((0.10, box_y - 0.02), 0.80, 0.18,
                                 boxstyle="round,pad=0.005,rounding_size=0.012",
                                 linewidth=1.5, edgecolor="#1e3a8a",
                                 facecolor="#eff6ff", transform=ax.transAxes))
    ax.text(0.5, box_y + 0.13, "Giá trị hợp lý ước tính (Equity Value)",
            ha="center", va="center", fontsize=12, fontweight="bold", color="#1e3a8a")
    if fv_mid is not None:
        ax.text(0.5, box_y + 0.08, _fmt_money(fv_mid),
                ha="center", va="center", fontsize=24, fontweight="bold", color="#1e3a8a")
        ax.text(0.5, box_y + 0.04, f"({unit})",
                ha="center", va="center", fontsize=10, color="#6b7280")
        if fv_low is not None and fv_high is not None:
            ax.text(0.5, box_y, f"Khoảng: {_fmt_money(fv_low)} — {_fmt_money(fv_high)}",
                    ha="center", va="center", fontsize=11, color="#374151")
    else:
        ax.text(0.5, box_y + 0.06, "(Không đủ dữ liệu định giá)",
                ha="center", va="center", fontsize=14, color="#9ca3af", style="italic")

    headline = _get(thesis, "executive_summary", "headline") or ""
    if headline:
        _draw_block(ax, headline, x=0.10, y=0.34, max_chars=72,
                    max_lines=4, fontsize=11, color="#374151", line_height=0.022)

    rec = _get(thesis, "executive_summary", "recommendation") or ""
    if rec:
        ax.text(0.10, 0.18, "KHUYẾN NGHỊ", fontsize=10,
                fontweight="bold", color="#1e3a8a", va="top")
        _draw_block(ax, rec, x=0.10, y=0.16, max_chars=80, max_lines=4,
                    fontsize=11, color="#1f2937", line_height=0.022)

    ax.text(0.5, 0.07, datetime.now().strftime("%d/%m/%Y · Generated by 3-agent pipeline"),
            ha="center", va="bottom", fontsize=9, color="#9ca3af", style="italic")
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
        ax.text(0, y, es["headline"], fontsize=12, fontweight="bold",
                color="#1e3a8a", va="top", wrap=True)
        y -= 0.05

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
    ], x=0, y=y, col_widths=[0.20, 0.30], cols=2)
    y -= 0.02

    if val_summary.get("method_values"):
        ax.text(0, y, "Kết quả định giá theo phương pháp", fontsize=12,
                fontweight="bold", color="#1e3a8a", va="top")
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
                color="#1e3a8a", va="top")
        y -= 0.028
        y = _draw_block(ax, es["recommendation"], x=0, y=y,
                        max_chars=92, max_lines=5, fontsize=11,
                        color="#374151", line_height=0.022)
        y -= 0.015

    if es.get("key_drivers"):
        ax.text(0, y, "Driver chính của giá trị", fontsize=12,
                fontweight="bold", color="#1e3a8a", va="top")
        y -= 0.028
        for d in (es["key_drivers"] or [])[:6]:
            if y < 0.04:
                break
            y = _draw_bullet(ax, d, x=0, y=y, fontsize=10,
                             color="#374151", max_chars=98, max_lines=3,
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
                fontweight="bold", color="#1e3a8a", va="top")
        y -= 0.030
        for i, p in enumerate(points[:5], 1):
            if y < 0.10:
                break
            ax.text(0, y, f"{i}. {p.get('title','')}", fontsize=11,
                    fontweight="bold", color="#2563eb", va="top")
            y -= 0.025
            y = _draw_block(ax, p.get("thesis", ""), x=0.02, y=y,
                            max_chars=96, max_lines=4, fontsize=10,
                            color="#374151", line_height=0.020)
            ev = p.get("evidence", "")
            if ev:
                y -= 0.005
                y = _draw_block(ax, f"📊 {ev}", x=0.02, y=y,
                                max_chars=98, max_lines=3, fontsize=9,
                                color="#6b7280", line_height=0.018)
            y -= 0.012
    yield fig

    cats = it.get("catalysts") or []
    risks = it.get("risks") or []
    if cats or risks:
        fig2, ax2 = _new_page("2. Investment Thesis — Catalysts & Risks")
        y = 0.93
        if cats:
            ax2.text(0, y, "Catalysts (Yếu tố thúc đẩy giá trị)", fontsize=12,
                     fontweight="bold", color="#10b981", va="top")
            y -= 0.030
            for c in cats[:6]:
                if y < 0.55:
                    break
                title = f"[{(c.get('type') or '?').upper()}] {c.get('description', '')}"
                horizon = c.get("horizon", "")
                if horizon:
                    title += f" — horizon: {horizon}"
                y = _draw_bullet(ax2, title, x=0, y=y, fontsize=10,
                                 color="#374151", max_chars=98, max_lines=3,
                                 line_height=0.020)
                y -= 0.005
            y -= 0.020

        if risks:
            ax2.text(0, y, "Rủi ro chính", fontsize=12,
                     fontweight="bold", color="#ef4444", va="top")
            y -= 0.030
            for r in risks[:8]:
                if y < 0.04:
                    break
                sev = (r.get("severity") or "").upper()
                sev_color = {"HIGH": "#ef4444", "MEDIUM": "#f59e0b", "LOW": "#10b981"}.get(sev, "#6b7280")
                line = f"[{(r.get('type') or '?').upper()} · {sev}] {r.get('description', '')}"
                y = _draw_bullet(ax2, line, x=0, y=y, fontsize=10,
                                 color=sev_color, max_chars=98, max_lines=3,
                                 line_height=0.020)
                if r.get("mitigation"):
                    y -= 0.002
                    y = _draw_block(ax2, f"Mitigation: {r['mitigation']}", x=0.02, y=y,
                                    max_chars=98, max_lines=2, fontsize=9,
                                    color="#6b7280", line_height=0.018)
                y -= 0.008
        yield fig2


# ============================ 3. Company Overview ============================

def _section_company_overview(financials, business):
    company = financials.get("company") or {}
    fig, ax = _new_page("3. Tổng quan Doanh nghiệp")

    y = 0.93
    ax.text(0, y, "3.1. Thông tin cơ bản", fontsize=12,
            fontweight="bold", color="#1e3a8a", va="top")
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
            fontweight="bold", color="#1e3a8a", va="top")
    y -= 0.030
    y = _draw_block(ax, bm.get("summary") or "", x=0, y=y,
                    max_chars=96, max_lines=4, fontsize=10,
                    color="#374151", line_height=0.020)
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
                fontweight="bold", color="#374151", va="top")
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
                            color="#374151", line_height=0.020)
    yield fig

    fig2, ax2 = _new_page("3. Tổng quan Doanh nghiệp — Chuỗi giá trị")
    vc = business.get("value_chain") or {}
    si = business.get("scale_indicators") or {}
    y = 0.93
    ax2.text(0, y, "3.3. Chuỗi giá trị (Value Chain)", fontsize=12,
             fontweight="bold", color="#1e3a8a", va="top")
    y -= 0.040
    chain = [
        ("INPUT", vc.get("input") or "—", "#3b82f6"),
        ("PRODUCTION", vc.get("production") or "—", "#10b981"),
        ("DISTRIBUTION", vc.get("distribution") or "—", "#f59e0b"),
        ("CUSTOMER", vc.get("customer") or "—", "#ef4444"),
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
                    color="#374151", line_height=0.014)
        if i < len(chain) - 1:
            arrow_x = x + box_w
            ax2.annotate("", xy=(arrow_x + gap - 0.005, box_y + box_h / 2),
                         xytext=(arrow_x + 0.005, box_y + box_h / 2),
                         arrowprops=dict(arrowstyle="->", color="#9ca3af"))
    y = box_y - 0.05

    ax2.text(0, y, "Quy mô & vị thế", fontsize=12,
             fontweight="bold", color="#1e3a8a", va="top")
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
                        color="#374151", line_height=0.020)
        y -= 0.020

    ax.text(0, y, "Quy mô thị trường (TAM / SAM / SOM)", fontsize=12,
            fontweight="bold", color="#1e3a8a", va="top")
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
                        color="#6b7280", line_height=0.018)
        y -= 0.015

    drivers = industry.get("industry_growth_drivers") or []
    trends = industry.get("industry_trends") or []
    if drivers:
        ax.text(0, y, "Driver tăng trưởng", fontsize=11,
                fontweight="bold", color="#10b981", va="top")
        y -= 0.025
        for d in drivers[:5]:
            if y < 0.04:
                break
            y = _draw_bullet(ax, d, x=0, y=y, fontsize=10,
                             color="#374151", max_chars=98, max_lines=2,
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
                             color="#374151", max_chars=98, max_lines=2,
                             line_height=0.020)
            y -= 0.003
    yield fig

    fig2, ax2 = _new_page("4. Phân tích Ngành — Cạnh tranh & Rủi ro")
    y = 0.93
    competitors = industry.get("key_competitors") or []
    if competitors:
        ax2.text(0, y, "Đối thủ cạnh tranh chính", fontsize=12,
                 fontweight="bold", color="#1e3a8a", va="top")
        y -= 0.030
        rows = []
        for c in competitors[:8]:
            rows.append((c.get("name") or "—",
                         _fmt_billion(c.get("estimated_revenue_vnd_billion")),
                         _fmt_pct_or_dash(c.get("market_share_pct")),
                         c.get("note") or ""))
        ax2.text(0, y, "Tên DN", fontsize=9, fontweight="bold", color="#6b7280", va="top")
        ax2.text(0.30, y, "Doanh thu ước", fontsize=9, fontweight="bold", color="#6b7280", va="top")
        ax2.text(0.50, y, "Thị phần", fontsize=9, fontweight="bold", color="#6b7280", va="top")
        ax2.text(0.65, y, "Ghi chú", fontsize=9, fontweight="bold", color="#6b7280", va="top")
        y -= 0.020
        ax2.plot([0, 1], [y + 0.005, y + 0.005], color="#d1d5db", linewidth=0.6)
        for name, rev, share, note in rows:
            if y < 0.30:
                break
            ax2.text(0, y, name, fontsize=9.5, color="#374151", va="top")
            ax2.text(0.30, y, rev, fontsize=9.5, color="#374151", va="top")
            ax2.text(0.50, y, share, fontsize=9.5, color="#374151", va="top")
            _draw_block(ax2, note[:70], x=0.65, y=y,
                        max_chars=42, max_lines=2,
                        fontsize=9, color="#6b7280", line_height=0.016)
            y -= 0.030
        y -= 0.005

    landscape = industry.get("competitive_landscape")
    if landscape:
        ax2.text(0, y, "Bối cảnh cạnh tranh", fontsize=11,
                 fontweight="bold", color="#1e3a8a", va="top")
        y -= 0.025
        y = _draw_block(ax2, landscape, x=0, y=y, max_chars=96,
                        max_lines=4, fontsize=10, color="#374151", line_height=0.020)
        y -= 0.020

    risks = industry.get("industry_risks") or []
    if risks and y > 0.12:
        ax2.text(0, y, "Rủi ro ngành", fontsize=11,
                 fontweight="bold", color="#ef4444", va="top")
        y -= 0.025
        for r in risks[:5]:
            if y < 0.06:
                break
            y = _draw_bullet(ax2, r, x=0, y=y, fontsize=10,
                             color="#374151", max_chars=98, max_lines=2,
                             line_height=0.020)
            y -= 0.003
        y -= 0.010

    barriers = industry.get("barriers_to_entry") or []
    if barriers and y > 0.08:
        ax2.text(0, y, "Rào cản gia nhập", fontsize=11,
                 fontweight="bold", color="#374151", va="top")
        y -= 0.025
        for b in barriers[:4]:
            if y < 0.04:
                break
            y = _draw_bullet(ax2, b, x=0, y=y, fontsize=10,
                             color="#374151", max_chars=98, max_lines=2,
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
                fontweight="bold", color="#1e3a8a", va="top")
        y -= 0.028
        y = _draw_block(ax, op["revenue_drivers"], x=0, y=y,
                        max_chars=96, max_lines=5, fontsize=10,
                        color="#374151", line_height=0.020)
        y -= 0.012

    if op.get("margin_analysis"):
        ax.text(0, y, "Phân tích biên lợi nhuận", fontsize=12,
                fontweight="bold", color="#1e3a8a", va="top")
        y -= 0.028
        y = _draw_block(ax, op["margin_analysis"], x=0, y=y,
                        max_chars=96, max_lines=5, fontsize=10,
                        color="#374151", line_height=0.020)
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
                fontweight="bold", color="#1e3a8a", va="top")
        y -= 0.028
        y = _draw_block(ax, op["channel_breakdown"], x=0, y=y,
                        max_chars=96, max_lines=5, fontsize=10,
                        color="#374151", line_height=0.020)
        y -= 0.012

    obs = op.get("key_metrics_observations") or []
    if obs:
        ax.text(0, y, "Quan sát quan trọng", fontsize=12,
                fontweight="bold", color="#1e3a8a", va="top")
        y -= 0.028
        for o in obs[:5]:
            if y < 0.04:
                break
            y = _draw_bullet(ax, o, x=0, y=y, fontsize=10,
                             color="#374151", max_chars=98, max_lines=3,
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
    ax.text(0, 0.93, f"Đơn vị: {unit}", fontsize=10, color="#6b7280",
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
    ax.text(0, 0.93, f"Đơn vị: {unit}", fontsize=10, color="#6b7280",
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
    ax.text(0, 0.93, f"Đơn vị: {unit}", fontsize=10, color="#6b7280",
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
                fontweight="bold", color="#1e3a8a", va="top")
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
        ax.text(0, y, "Chỉ tiêu", fontsize=8.5, fontweight="bold", color="#6b7280", va="top")
        ax.text(0.50, y, "Kỳ này", fontsize=8.5, fontweight="bold", color="#6b7280", va="top", ha="right")
        ax.text(0.65, y, "Kỳ trước", fontsize=8.5, fontweight="bold", color="#6b7280", va="top", ha="right")
        ax.text(0.85, y, "Đánh giá", fontsize=8.5, fontweight="bold", color="#6b7280", va="top", ha="right")
        y -= 0.014
        ax.plot([0, 0.95], [y + 0.005, y + 0.005], color="#e5e7eb", linewidth=0.5)
        for name, payload in cat_data.items():
            if y < 0.04:
                break
            value = payload.get("value")
            rating = payload.get("rating", "n/a")
            prev_value = ((prev_ratios.get(cat) or {}).get(name) or {}).get("value")
            ax.text(0, y, RATIO_LABEL_VI.get(name, name), fontsize=9.5,
                    color="#374151", va="top")
            ax.text(0.50, y, _fmt_ratio(name, value), fontsize=9.5,
                    color="#111827", va="top", ha="right")
            ax.text(0.65, y, _fmt_ratio(name, prev_value), fontsize=9.5,
                    color="#6b7280", va="top", ha="right")
            box = FancyBboxPatch((0.70, y - 0.014), 0.16, 0.018,
                                 boxstyle="round,pad=0.001,rounding_size=0.004",
                                 linewidth=0,
                                 facecolor=RATING_COLOR.get(rating, "#9ca3af"),
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
            fontweight="bold", color="#1e3a8a", va="top")
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
                        color="#6b7280", line_height=0.018)
        y -= 0.012

    if projections:
        ax.text(0, y, "Dự phóng KQKD & FCFF", fontsize=12,
                fontweight="bold", color="#1e3a8a", va="top")
        y -= 0.024
        headers = ["Khoản mục"] + [p.get("year_label", f"Y{i+1}") for i, p in enumerate(projections)]
        cols = len(headers)
        col_w = (0.95) / cols
        col_w_label = 0.25
        col_w_year = (0.95 - col_w_label) / max(1, cols - 1)
        for i, h in enumerate(headers):
            x = 0 if i == 0 else col_w_label + (i - 1) * col_w_year
            ha = "left" if i == 0 else "right"
            ax.text(x + (0 if i == 0 else col_w_year), y, h,
                    fontsize=9, fontweight="bold", color="#6b7280",
                    va="top", ha=ha)
        y -= 0.018
        ax.plot([0, 0.95], [y + 0.005, y + 0.005], color="#d1d5db", linewidth=0.5)

        proj_rows = [
            ("Doanh thu", "revenue", False),
            ("Tăng trưởng", "growth_pct", "pct"),
            ("LN gộp", "gross_profit", False),
            ("EBIT", "ebit", False),
            ("EBITDA", "ebitda", False),
            ("LNST", "net_income", False),
            ("CAPEX", "capex", False),
            ("ΔWC", "change_in_wc", False),
            ("FCFF", "fcff", "highlight"),
        ]
        for label, key, mode in proj_rows:
            if y < 0.10:
                break
            color = "#1e3a8a" if mode == "highlight" else "#374151"
            fw = "bold" if mode == "highlight" else "normal"
            fs = 9
            ax.text(0, y, label, fontsize=fs, color=color,
                    va="top", fontweight=fw)
            for i, p in enumerate(projections):
                xx = col_w_label + i * col_w_year + col_w_year
                v = p.get(key)
                if mode == "pct":
                    s = _fmt_pct_or_dash(v)
                else:
                    s = _fmt_money(v)
                ax.text(xx, y, s, fontsize=fs, color=color,
                        va="top", ha="right", fontweight=fw)
            y -= 0.020
        y -= 0.010

    if summary and y > 0.10:
        ax.text(0, y, "Tổng hợp dự phóng 5 năm", fontsize=12,
                fontweight="bold", color="#1e3a8a", va="top")
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
                            color="#374151", line_height=0.020)
    yield fig

    # Chart: revenue/EBITDA/FCFF over 5 years
    if projections:
        fig2 = plt.figure(figsize=A4)
        fig2.suptitle("8. Dự phóng — Biểu đồ", fontsize=16, fontweight="bold",
                      color="#1f2937", x=0.08, y=0.96, ha="left")
        ax_rev = fig2.add_axes([0.10, 0.55, 0.80, 0.32])
        years = [p.get("year_label", f"Y{i+1}") for i, p in enumerate(projections)]
        revenues = [p.get("revenue") or 0 for p in projections]
        ebitdas = [p.get("ebitda") or 0 for p in projections]
        fcffs = [p.get("fcff") or 0 for p in projections]
        x = range(len(years))
        ax_rev.bar([i - 0.2 for i in x], revenues, width=0.4, color="#3b82f6", label="Doanh thu")
        ax_rev.bar([i + 0.2 for i in x], ebitdas, width=0.4, color="#10b981", label="EBITDA")
        ax_rev.set_xticks(list(x)); ax_rev.set_xticklabels(years, fontsize=10)
        ax_rev.set_title("Doanh thu vs EBITDA", fontsize=12, fontweight="bold")
        ax_rev.legend(fontsize=9); ax_rev.grid(axis="y", linestyle=":", alpha=0.4)
        ax_fcf = fig2.add_axes([0.10, 0.10, 0.80, 0.32])
        colors_fcf = ["#10b981" if v >= 0 else "#ef4444" for v in fcffs]
        ax_fcf.bar(years, fcffs, color=colors_fcf)
        for i, v in enumerate(fcffs):
            ax_fcf.text(i, v, _fmt_money(v), ha="center", va="bottom" if v >= 0 else "top",
                        fontsize=9, color="#1f2937")
        ax_fcf.set_title("Free Cash Flow to Firm (FCFF)", fontsize=12, fontweight="bold")
        ax_fcf.grid(axis="y", linestyle=":", alpha=0.4)
        ax_fcf.axhline(0, color="#374151", linewidth=0.5)
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
                        color="#6b7280", line_height=0.018)
        y -= 0.010

    pv_breakdown = dcf.get("pv_breakdown") or []
    if pv_breakdown:
        ax.text(0, y, "Chiết khấu FCFF", fontsize=12,
                fontweight="bold", color="#1e3a8a", va="top")
        y -= 0.024
        ax.text(0, y, "Năm", fontsize=9, fontweight="bold", color="#6b7280", va="top")
        ax.text(0.30, y, "FCFF", fontsize=9, fontweight="bold", color="#6b7280", va="top", ha="right")
        ax.text(0.55, y, "Discount factor", fontsize=9, fontweight="bold", color="#6b7280", va="top", ha="right")
        ax.text(0.85, y, "PV", fontsize=9, fontweight="bold", color="#6b7280", va="top", ha="right")
        y -= 0.017
        ax.plot([0, 0.95], [y + 0.005, y + 0.005], color="#d1d5db", linewidth=0.5)
        for row in pv_breakdown:
            if y < 0.20:
                break
            ax.text(0, y, f"Y{row.get('year')}", fontsize=9, color="#374151", va="top")
            ax.text(0.30, y, _fmt_money(row.get("fcff")), fontsize=9,
                    color="#374151", va="top", ha="right")
            ax.text(0.55, y, f"{row.get('discount_factor'):.4f}",
                    fontsize=9, color="#374151", va="top", ha="right")
            ax.text(0.85, y, _fmt_money(row.get("pv")), fontsize=9,
                    color="#374151", va="top", ha="right")
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
             fontweight="bold", color="#1e3a8a", va="top")
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
                            color="#6b7280", line_height=0.018)
            y -= 0.005
    y -= 0.015

    ax2.text(0, y, "Kết quả định giá theo Multiples", fontsize=12,
             fontweight="bold", color="#1e3a8a", va="top")
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
                 fontsize=12, fontweight="bold", color="#1e3a8a", va="top")
        y -= 0.026
        ax2.text(0, y, "Tên DN", fontsize=9, fontweight="bold", color="#6b7280", va="top")
        ax2.text(0.40, y, "EV/EBITDA", fontsize=9, fontweight="bold", color="#6b7280", va="top", ha="right")
        ax2.text(0.55, y, "P/E", fontsize=9, fontweight="bold", color="#6b7280", va="top", ha="right")
        ax2.text(0.70, y, "P/B", fontsize=9, fontweight="bold", color="#6b7280", va="top", ha="right")
        ax2.text(0.95, y, "Ghi chú", fontsize=9, fontweight="bold", color="#6b7280", va="top", ha="right")
        y -= 0.017
        ax2.plot([0, 0.95], [y + 0.005, y + 0.005], color="#d1d5db", linewidth=0.5)
        for c in comps[:6]:
            if y < 0.05:
                break
            ax2.text(0, y, c.get("name") or "—", fontsize=9, color="#374151", va="top")
            ax2.text(0.40, y, str(c.get("ev_ebitda") or "—"),
                     fontsize=9, color="#374151", va="top", ha="right")
            ax2.text(0.55, y, str(c.get("pe") or "—"),
                     fontsize=9, color="#374151", va="top", ha="right")
            ax2.text(0.70, y, str(c.get("pb") or "—"),
                     fontsize=9, color="#374151", va="top", ha="right")
            note = (c.get("note") or "")[:40]
            ax2.text(0.95, y, note, fontsize=8.5, color="#6b7280", va="top", ha="right")
            y -= 0.022
    yield fig2

    # Summary page
    fig3, ax3 = _new_page("9.4. Tổng hợp Định giá")
    y = 0.93
    method_values = summary.get("method_values") or []
    if method_values:
        ax3.text(0, y, "Kết quả theo từng phương pháp", fontsize=12,
                 fontweight="bold", color="#1e3a8a", va="top")
        y -= 0.026
        ax3.text(0, y, "Phương pháp", fontsize=9.5, fontweight="bold", color="#6b7280", va="top")
        ax3.text(0.55, y, "Equity Value", fontsize=9.5, fontweight="bold", color="#6b7280", va="top", ha="right")
        y -= 0.018
        ax3.plot([0, 0.85], [y + 0.005, y + 0.005], color="#d1d5db", linewidth=0.5)
        for mv in method_values:
            if y < 0.30:
                break
            ax3.text(0, y, mv.get("method") or "—", fontsize=10, color="#374151", va="top")
            ax3.text(0.55, y, _fmt_money(mv.get("equity_value")),
                     fontsize=10, color="#374151", va="top", ha="right")
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
                 fontweight="bold", color="#1e3a8a", va="top")
        y -= 0.024
        y = _draw_block(ax3, assumptions["valuation_method_recommendation"],
                        x=0, y=y, max_chars=98, max_lines=4, fontsize=10,
                        color="#374151", line_height=0.020)
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
            fontsize=11, fontweight="bold", color="#1e3a8a", va="top")
    y -= 0.034

    growth_axis = sens.get("growth_axis_pct") or []
    if not matrix or not growth_axis:
        ax.text(0, y, "(Không đủ dữ liệu)", fontsize=10,
                color="#9ca3af", va="top", style="italic")
        yield fig
        return

    cols = len(growth_axis) + 1
    col_w = 0.85 / cols
    start_x = 0.05

    ax.text(start_x, y, "WACC \\ g", fontsize=9, fontweight="bold",
            color="#6b7280", va="top")
    for i, g in enumerate(growth_axis):
        x = start_x + (i + 1) * col_w
        ax.text(x + col_w / 2, y, f"g={g}%", fontsize=9,
                fontweight="bold", color="#6b7280", va="top", ha="center")
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
                fontweight="bold", color="#6b7280", va="top")
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
                                    edgecolor="#dc2626" if is_base else "#e5e7eb",
                                    linewidth=1.5 if is_base else 0.5,
                                    transform=ax.transAxes))
            ax.text(x + col_w / 2, y - 0.012, label, fontsize=8.5,
                    color="#1f2937", va="center", ha="center",
                    fontweight="bold" if is_base else "normal")
        y -= 0.022
    y -= 0.020

    ax.text(0, y, "Cách đọc", fontsize=11,
            fontweight="bold", color="#1e3a8a", va="top")
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
                         color="#374151", max_chars=98, max_lines=2,
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
                fontweight="bold", color="#1e3a8a", va="top")
        y -= 0.026
        y = _draw_block(ax, val_comm["method_comparison"], x=0, y=y,
                        max_chars=98, max_lines=4, fontsize=10,
                        color="#374151", line_height=0.020)
        y -= 0.015

    if val_comm.get("fair_value_view"):
        ax.text(0, y, "Quan điểm về giá trị hợp lý", fontsize=12,
                fontweight="bold", color="#1e3a8a", va="top")
        y -= 0.026
        y = _draw_block(ax, val_comm["fair_value_view"], x=0, y=y,
                        max_chars=98, max_lines=4, fontsize=10,
                        color="#374151", line_height=0.020)
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
                fontweight="bold", color="#1e3a8a", va="top")
        y -= 0.026
        for g in governance[:5]:
            if y < 0.10:
                break
            y = _draw_bullet(ax, g, x=0, y=y, fontsize=10,
                             color="#374151", max_chars=98, max_lines=2,
                             line_height=0.020)
            y -= 0.005
        y -= 0.010

    next_steps = deal.get("next_steps") or []
    if next_steps:
        ax.text(0, y, "Bước tiếp theo", fontsize=12,
                fontweight="bold", color="#10b981", va="top")
        y -= 0.026
        for i, s in enumerate(next_steps[:6], 1):
            if y < 0.05:
                break
            y = _draw_bullet(ax, f"{i}. {s}", x=0, y=y, fontsize=10,
                             color="#374151", max_chars=98, max_lines=3,
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
            fontweight="bold", color="#1e3a8a", va="top")
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
            fontweight="bold", color="#1e3a8a", va="top")
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
            fontweight="bold", color="#1e3a8a", va="top")
    y -= 0.026
    comps = assumptions_v.get("comparable_companies") or []
    if comps:
        for c in comps[:8]:
            if y < 0.08:
                break
            y = _draw_bullet(ax,
                f"{c.get('name')} — EV/EBITDA={c.get('ev_ebitda') or '—'}, P/E={c.get('pe') or '—'}, P/B={c.get('pb') or '—'}",
                x=0, y=y, fontsize=9.5, color="#374151",
                max_chars=98, max_lines=2, line_height=0.018)
            y -= 0.003
    else:
        ax.text(0, y, "(Không có)", fontsize=10, color="#9ca3af", va="top", style="italic")
    yield fig


# ============================ Helpers — page templates ============================

def _new_page(title: str):
    fig = plt.figure(figsize=A4)
    ax = fig.add_axes([0.07, 0.05, 0.86, 0.92])
    ax.axis("off"); ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    ax.text(0, 0.97, title, fontsize=16, fontweight="bold",
            color="#1e3a8a", va="top")
    ax.plot([0, 1], [0.952, 0.952], color="#1e3a8a", linewidth=1.5)
    return fig, ax


# ============================ Helpers — drawing ============================

def _draw_block(ax, text, x, y, fontsize, color, max_chars, max_lines, line_height):
    if not text:
        return y
    lines: list[str] = []
    for paragraph in str(text).split("\n"):
        if not paragraph.strip():
            lines.append("")
            continue
        wrapped = textwrap.wrap(paragraph, width=max_chars,
                                break_long_words=False, break_on_hyphens=False)
        lines.extend(wrapped or [""])
    for i, line in enumerate(lines[:max_lines]):
        ax.text(x, y - i * line_height, line, fontsize=fontsize,
                color=color, va="top")
    return y - len(lines[:max_lines]) * line_height


def _draw_bullet(ax, text, x, y, fontsize, color, max_chars, max_lines, line_height):
    ax.text(x, y, "•", fontsize=fontsize + 1, color=color,
            va="top", fontweight="bold")
    return _draw_block(ax, str(text), x=x + 0.018, y=y,
                       fontsize=fontsize, color=color,
                       max_chars=max_chars, max_lines=max_lines,
                       line_height=line_height)


def _draw_simple_table(ax, rows, x, y, col_widths, line_height, highlight_last=False):
    for idx, row in enumerate(rows):
        if y < 0.04:
            break
        is_last = highlight_last and idx == len(rows) - 1
        cur_x = x
        for i, cell in enumerate(row):
            w = col_widths[i] if i < len(col_widths) else 0.20
            text = "" if cell is None else str(cell)
            color = "#1e3a8a" if is_last else "#374151"
            fw = "bold" if (is_last or i == 0) else "normal"
            fs = 11 if is_last else 10
            ha = "left"
            ax.text(cur_x, y, text, fontsize=fs, color=color,
                    fontweight=fw, va="top", ha=ha)
            cur_x += w
        if is_last:
            ax.plot([x, x + sum(col_widths)], [y - 0.003, y - 0.003],
                    color="#1e3a8a", linewidth=1)
        y -= line_height
    return y


def _draw_kv_grid(ax, items, x, y, col_widths, cols=2, line_height=0.024):
    for i, (k, v) in enumerate(items):
        col = i % cols
        row = i // cols
        cx = x + col * (col_widths[0] + col_widths[1] + 0.04)
        cy = y - row * line_height
        ax.text(cx, cy, k, fontsize=9, color="#6b7280", va="top")
        ax.text(cx + col_widths[0], cy, str(v), fontsize=10,
                color="#1f2937", va="top", fontweight="bold")
    rows = (len(items) + cols - 1) // cols
    return y - rows * line_height


def _draw_table(ax, rows, x, y, width, line_height, show_prev, cur_label, prev_label):
    label_x = x + 0.005
    cur_x = x + width * 0.62
    prev_x = x + width * 0.82
    chg_x = x + width * 0.99

    ax.text(label_x, y, "Khoản mục", fontsize=9, fontweight="bold",
            color="#6b7280", va="top")
    ax.text(cur_x, y, cur_label, fontsize=9, fontweight="bold",
            color="#6b7280", va="top", ha="right")
    if show_prev:
        ax.text(prev_x, y, prev_label, fontsize=9, fontweight="bold",
                color="#6b7280", va="top", ha="right")
        ax.text(chg_x, y, "Δ%", fontsize=9, fontweight="bold",
                color="#6b7280", va="top", ha="right")
    y -= line_height
    ax.plot([x, x + width], [y + 0.003, y + 0.003], color="#d1d5db", linewidth=0.7)
    y -= 0.005

    for label, level, cv, pv in rows:
        if y < 0.04:
            break
        if level == "header":
            ax.text(label_x, y, label, fontsize=11, fontweight="bold",
                    color="#1f2937", va="top")
            y -= line_height
            continue
        if level == "subheader":
            ax.text(label_x + 0.005, y, label, fontsize=10, fontweight="bold",
                    color="#374151", va="top", style="italic")
            y -= line_height
            continue
        if level == "grand":
            font_w = "bold"; color = "#1f2937"; fs = 10
        elif level == "total":
            font_w = "bold"; color = "#374151"; fs = 9.5
        else:
            font_w = "normal"; color = "#374151"; fs = 9
            label = "  " + label
        ax.text(label_x, y, label, fontsize=fs, fontweight=font_w,
                color=color, va="top")
        ax.text(cur_x, y, _fmt_money(cv), fontsize=fs,
                fontweight=font_w, color=color, va="top", ha="right")
        if show_prev:
            ax.text(prev_x, y, _fmt_money(pv), fontsize=fs,
                    color="#6b7280", va="top", ha="right")
            chg_pct = _percent_change(cv, pv)
            chg_color = "#374151"
            if chg_pct is not None:
                chg_color = "#10b981" if chg_pct > 0 else ("#ef4444" if chg_pct < 0 else "#6b7280")
            ax.text(chg_x, y, _fmt_pct_signed_pct(chg_pct),
                    fontsize=fs - 0.5, color=chg_color, va="top", ha="right")
        if level == "grand":
            ax.plot([x, x + width], [y - 0.002, y - 0.002],
                    color="#9ca3af", linewidth=0.5)
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
            ha="center", va="center", fontsize=14, color="#6b7280")
    ax.plot([0.20, 0.80], [0.62, 0.62], color="#dc2626", linewidth=2)
    ax.text(0.5, 0.55, f"Job: {trace.get('job_id','?')}",
            ha="center", va="center", fontsize=12, color="#374151")
    ax.text(0.5, 0.50, datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
            ha="center", va="center", fontsize=11, color="#9ca3af")
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
            color="#dc2626", va="top")
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
