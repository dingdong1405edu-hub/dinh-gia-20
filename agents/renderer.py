"""Agent 3: Render financial analysis PDF + debug report PDF."""
import json
import textwrap
import time
from datetime import datetime

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import rcParams
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.patches import Circle, FancyBboxPatch

rcParams["font.family"] = "DejaVu Sans"
rcParams["mathtext.fontset"] = "cm"
rcParams["axes.unicode_minus"] = False

A4 = (8.27, 11.69)

RATING_COLOR = {
    "good": "#10b981",
    "warning": "#f59e0b",
    "poor": "#ef4444",
    "n/a": "#9ca3af",
}
RATING_LABEL_VI = {
    "good": "Tốt",
    "warning": "Trung bình",
    "poor": "Kém",
    "n/a": "—",
}
GRADE_COLOR = {
    "A": "#10b981",
    "B": "#22c55e",
    "C": "#f59e0b",
    "D": "#f97316",
    "F": "#ef4444",
}

RATIO_LABEL_VI = {
    "current_ratio": "Hệ số thanh toán hiện hành",
    "quick_ratio": "Hệ số thanh toán nhanh",
    "cash_ratio": "Hệ số thanh toán tiền mặt",
    "debt_ratio": "Hệ số nợ trên tổng TS",
    "debt_to_equity": "Nợ / Vốn CSH",
    "equity_multiplier": "Hệ số nhân vốn CSH",
    "gross_margin": "Biên lợi nhuận gộp",
    "operating_margin": "Biên LN từ HĐKD",
    "net_margin": "Biên lợi nhuận ròng",
    "roa": "ROA — Tỷ suất sinh lời TS",
    "roe": "ROE — Tỷ suất sinh lời VCSH",
    "asset_turnover": "Vòng quay tổng TS",
    "inventory_turnover": "Vòng quay hàng tồn kho",
    "receivables_turnover": "Vòng quay khoản phải thu",
}
CATEGORY_LABEL_VI = {
    "liquidity": "Thanh khoản",
    "leverage": "Đòn bẩy / Cơ cấu vốn",
    "profitability": "Khả năng sinh lời",
    "efficiency": "Hiệu quả hoạt động",
}
PERCENT_RATIOS = {"gross_margin", "operating_margin", "net_margin", "roa", "roe", "debt_ratio"}


# ============= Public API =============

def render_analysis(extractor_payload: dict, analyzer_payload: dict, output_path: str) -> dict:
    t0 = time.time()
    financials = extractor_payload.get("financials") or {}
    ratios = analyzer_payload.get("ratios") or {}
    insights = analyzer_payload.get("insights") or {}

    pages = 0
    with PdfPages(output_path) as pdf:
        for fig in _build_pages(financials, ratios, insights):
            pdf.savefig(fig)
            plt.close(fig)
            pages += 1

    return {
        "elapsed_sec": round(time.time() - t0, 2),
        "pages": pages,
        "output_path": output_path,
    }


def render_report(trace: dict, output_path: str) -> dict:
    t0 = time.time()
    sections = _trace_sections(trace)

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


# ============= Analysis pages =============

def _build_pages(financials, ratios, insights):
    yield _page_cover(financials, insights)
    yield _page_summary(insights)
    yield _page_balance_sheet(financials)
    yield _page_income_statement(financials)
    if _get(financials, "cash_flow", "current"):
        yield _page_cash_flow(financials)
    yield _page_ratios(ratios, insights)
    yield _page_charts(financials, ratios)
    for fig in _pages_insights(insights):
        yield fig


def _page_cover(financials, insights):
    fig = plt.figure(figsize=A4)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.axis("off"); ax.set_xlim(0, 1); ax.set_ylim(0, 1)

    ax.text(0.5, 0.92, "BÁO CÁO PHÂN TÍCH TÀI CHÍNH",
            ha="center", va="top", fontsize=22, fontweight="bold", color="#1f2937")
    ax.plot([0.18, 0.82], [0.885, 0.885], color="#2563eb", linewidth=2.5)

    company = (_get(financials, "company", "name") or "(Không xác định)").strip()
    ax.text(0.5, 0.78, company, ha="center", va="top",
            fontsize=18, fontweight="bold", color="#2563eb",
            wrap=True)

    period_label = _get(financials, "period", "current", "label") or ""
    if period_label:
        ax.text(0.5, 0.71, f"Kỳ: {period_label}", ha="center", va="top",
                fontsize=14, color="#374151")

    report_type = _get(financials, "company", "report_type")
    if report_type:
        ax.text(0.5, 0.66, report_type, ha="center", va="top",
                fontsize=12, color="#6b7280", style="italic")

    grade = (insights.get("health_grade") or "?").upper()
    score = insights.get("health_score")
    grade_color = GRADE_COLOR.get(grade, "#6b7280")
    circle = Circle((0.5, 0.43), 0.13, color=grade_color, alpha=0.95, transform=ax.transAxes)
    ax.add_patch(circle)
    ax.text(0.5, 0.435, grade, ha="center", va="center",
            fontsize=70, fontweight="bold", color="#fff")
    ax.text(0.5, 0.27, "Đánh giá tổng thể", ha="center", va="center",
            fontsize=12, color="#6b7280")
    if isinstance(score, (int, float)):
        ax.text(0.5, 0.225, f"{int(score)} / 100", ha="center", va="center",
                fontsize=16, fontweight="bold", color="#1f2937")

    tax_code = _get(financials, "company", "tax_code")
    if tax_code:
        ax.text(0.5, 0.14, f"MST: {tax_code}", ha="center", va="center",
                fontsize=10, color="#9ca3af")

    ax.text(0.5, 0.06, datetime.now().strftime("Báo cáo phân tích — %d/%m/%Y %H:%M"),
            ha="center", va="center", fontsize=9, color="#9ca3af", style="italic")
    return fig


def _page_summary(insights):
    fig = plt.figure(figsize=A4)
    ax = fig.add_axes([0.08, 0.05, 0.84, 0.92])
    ax.axis("off"); ax.set_xlim(0, 1); ax.set_ylim(0, 1)

    ax.text(0, 0.97, "Tổng quan & Điểm nổi bật", fontsize=18,
            fontweight="bold", color="#1f2937", va="top")
    ax.plot([0, 1], [0.945, 0.945], color="#2563eb", linewidth=2)

    summary = insights.get("executive_summary") or "(Không có)"
    y = _draw_block(ax, summary, x=0, y=0.91, fontsize=12, color="#374151",
                    max_chars=88, max_lines=10, line_height=0.025)

    y -= 0.04
    ax.text(0, y, "Điểm nổi bật", fontsize=14, fontweight="bold",
            color="#2563eb", va="top")
    y -= 0.04
    insights_list = insights.get("key_insights") or []
    for item in insights_list[:8]:
        if y < 0.05:
            break
        y -= 0.005
        used = _draw_bullet(ax, item, x=0, y=y, fontsize=11,
                            color="#374151", max_chars=92, max_lines=4,
                            line_height=0.022)
        y = used - 0.008
    return fig


def _page_balance_sheet(financials):
    fig = plt.figure(figsize=A4)
    ax = fig.add_axes([0.06, 0.05, 0.88, 0.92])
    ax.axis("off"); ax.set_xlim(0, 1); ax.set_ylim(0, 1)

    ax.text(0, 0.97, "Bảng cân đối kế toán", fontsize=18,
            fontweight="bold", color="#1f2937", va="top")
    ax.plot([0, 1], [0.945, 0.945], color="#2563eb", linewidth=2)

    unit = financials.get("unit") or "đồng"
    cur_label = _get(financials, "period", "current", "label") or "Kỳ này"
    prev_label = _get(financials, "period", "previous", "label")
    ax.text(0, 0.92, f"Đơn vị: {unit}", fontsize=10,
            color="#6b7280", va="top", style="italic")

    bs_cur = _get(financials, "balance_sheet", "current") or {}
    bs_prev = _get(financials, "balance_sheet", "previous") or {}

    rows: list[tuple[str, str, object, object]] = []

    def add(label, current_val, previous_val, level=0):
        rows.append((label, level, current_val, previous_val))

    a_cur = bs_cur.get("assets") or {}
    a_prev = bs_prev.get("assets") if isinstance(bs_prev, dict) else {}
    add("TÀI SẢN", "header", None, None)
    add("Tài sản ngắn hạn", "subheader", None, None)
    add("Tiền và tương đương tiền", 1, _get(a_cur, "cash_and_equivalents"), _get(a_prev, "cash_and_equivalents"))
    add("Đầu tư tài chính ngắn hạn", 1, _get(a_cur, "short_term_investments"), _get(a_prev, "short_term_investments"))
    add("Phải thu ngắn hạn", 1, _get(a_cur, "short_term_receivables"), _get(a_prev, "short_term_receivables"))
    add("Hàng tồn kho", 1, _get(a_cur, "inventory"), _get(a_prev, "inventory"))
    add("TS ngắn hạn khác", 1, _get(a_cur, "other_current_assets"), _get(a_prev, "other_current_assets"))
    add("Cộng TS ngắn hạn", "total", _get(a_cur, "current_assets_total"), _get(a_prev, "current_assets_total"))
    add("Tài sản dài hạn", "subheader", None, None)
    add("Phải thu dài hạn", 1, _get(a_cur, "long_term_receivables"), _get(a_prev, "long_term_receivables"))
    add("Tài sản cố định", 1, _get(a_cur, "fixed_assets"), _get(a_prev, "fixed_assets"))
    add("Bất động sản đầu tư", 1, _get(a_cur, "investment_properties"), _get(a_prev, "investment_properties"))
    add("Đầu tư tài chính dài hạn", 1, _get(a_cur, "long_term_investments"), _get(a_prev, "long_term_investments"))
    add("TS dài hạn khác", 1, _get(a_cur, "other_non_current_assets"), _get(a_prev, "other_non_current_assets"))
    add("Cộng TS dài hạn", "total", _get(a_cur, "non_current_assets_total"), _get(a_prev, "non_current_assets_total"))
    add("TỔNG CỘNG TÀI SẢN", "grand", _get(a_cur, "total_assets"), _get(a_prev, "total_assets"))

    l_cur = bs_cur.get("liabilities") or {}
    l_prev = bs_prev.get("liabilities") if isinstance(bs_prev, dict) else {}
    e_cur = bs_cur.get("equity") or {}
    e_prev = bs_prev.get("equity") if isinstance(bs_prev, dict) else {}

    add("NGUỒN VỐN", "header", None, None)
    add("Nợ ngắn hạn", "subheader", None, None)
    add("Vay ngắn hạn", 1, _get(l_cur, "short_term_debt"), _get(l_prev, "short_term_debt"))
    add("Phải trả người bán", 1, _get(l_cur, "accounts_payable"), _get(l_prev, "accounts_payable"))
    add("Nợ ngắn hạn khác", 1, _get(l_cur, "other_current_liabilities"), _get(l_prev, "other_current_liabilities"))
    add("Cộng nợ ngắn hạn", "total", _get(l_cur, "current_liabilities_total"), _get(l_prev, "current_liabilities_total"))
    add("Nợ dài hạn", "subheader", None, None)
    add("Vay dài hạn", 1, _get(l_cur, "long_term_debt"), _get(l_prev, "long_term_debt"))
    add("Nợ dài hạn khác", 1, _get(l_cur, "other_non_current_liabilities"), _get(l_prev, "other_non_current_liabilities"))
    add("Cộng nợ dài hạn", "total", _get(l_cur, "non_current_liabilities_total"), _get(l_prev, "non_current_liabilities_total"))
    add("TỔNG NỢ PHẢI TRẢ", "grand", _get(l_cur, "total_liabilities"), _get(l_prev, "total_liabilities"))
    add("Vốn chủ sở hữu", "subheader", None, None)
    add("Vốn góp chủ sở hữu", 1, _get(e_cur, "share_capital"), _get(e_prev, "share_capital"))
    add("Lợi nhuận sau thuế chưa PP", 1, _get(e_cur, "retained_earnings"), _get(e_prev, "retained_earnings"))
    add("VCSH khác", 1, _get(e_cur, "other_equity"), _get(e_prev, "other_equity"))
    add("TỔNG VỐN CHỦ SỞ HỮU", "grand", _get(e_cur, "total_equity"), _get(e_prev, "total_equity"))

    _draw_table(ax, rows, x=0, y=0.89, width=1.0, line_height=0.0205,
                show_prev=bool(bs_prev) and prev_label is not None,
                cur_label=cur_label, prev_label=prev_label or "Kỳ trước")
    return fig


def _page_income_statement(financials):
    fig = plt.figure(figsize=A4)
    ax = fig.add_axes([0.06, 0.05, 0.88, 0.92])
    ax.axis("off"); ax.set_xlim(0, 1); ax.set_ylim(0, 1)

    ax.text(0, 0.97, "Báo cáo kết quả hoạt động kinh doanh",
            fontsize=18, fontweight="bold", color="#1f2937", va="top")
    ax.plot([0, 1], [0.945, 0.945], color="#2563eb", linewidth=2)

    unit = financials.get("unit") or "đồng"
    ax.text(0, 0.92, f"Đơn vị: {unit}", fontsize=10,
            color="#6b7280", va="top", style="italic")

    cur_label = _get(financials, "period", "current", "label") or "Kỳ này"
    prev_label = _get(financials, "period", "previous", "label")
    is_cur = _get(financials, "income_statement", "current") or {}
    is_prev = _get(financials, "income_statement", "previous") or {}

    rows: list[tuple] = []

    def add(label, level, cv, pv):
        rows.append((label, level, cv, pv))

    add("Doanh thu bán hàng và CCDV", 0, is_cur.get("revenue"), is_prev.get("revenue"))
    add("Các khoản giảm trừ doanh thu", 0, is_cur.get("revenue_deductions"), is_prev.get("revenue_deductions"))
    add("Doanh thu thuần", "total", is_cur.get("net_revenue"), is_prev.get("net_revenue"))
    add("Giá vốn hàng bán", 0, is_cur.get("cogs"), is_prev.get("cogs"))
    add("LỢI NHUẬN GỘP", "grand", is_cur.get("gross_profit"), is_prev.get("gross_profit"))
    add("Doanh thu hoạt động tài chính", 0, is_cur.get("financial_income"), is_prev.get("financial_income"))
    add("Chi phí tài chính", 0, is_cur.get("financial_expense"), is_prev.get("financial_expense"))
    add("  Trong đó: Chi phí lãi vay", 1, is_cur.get("interest_expense"), is_prev.get("interest_expense"))
    add("Chi phí bán hàng", 0, is_cur.get("selling_expense"), is_prev.get("selling_expense"))
    add("Chi phí quản lý doanh nghiệp", 0, is_cur.get("admin_expense"), is_prev.get("admin_expense"))
    add("LỢI NHUẬN TỪ HĐKD", "grand", is_cur.get("operating_profit"), is_prev.get("operating_profit"))
    add("Thu nhập khác", 0, is_cur.get("other_income"), is_prev.get("other_income"))
    add("Chi phí khác", 0, is_cur.get("other_expense"), is_prev.get("other_expense"))
    add("LỢI NHUẬN TRƯỚC THUẾ", "grand", is_cur.get("profit_before_tax"), is_prev.get("profit_before_tax"))
    add("Thuế TNDN hiện hành", 0, is_cur.get("current_tax"), is_prev.get("current_tax"))
    add("Thuế TNDN hoãn lại", 0, is_cur.get("deferred_tax"), is_prev.get("deferred_tax"))
    add("LỢI NHUẬN SAU THUẾ", "grand", is_cur.get("net_profit_after_tax"), is_prev.get("net_profit_after_tax"))
    add("Lãi cơ bản trên cổ phiếu (EPS)", 0, is_cur.get("eps"), is_prev.get("eps"))

    _draw_table(ax, rows, x=0, y=0.89, width=1.0, line_height=0.026,
                show_prev=bool(is_prev),
                cur_label=cur_label, prev_label=prev_label or "Kỳ trước")
    return fig


def _page_cash_flow(financials):
    fig = plt.figure(figsize=A4)
    ax = fig.add_axes([0.06, 0.05, 0.88, 0.92])
    ax.axis("off"); ax.set_xlim(0, 1); ax.set_ylim(0, 1)

    ax.text(0, 0.97, "Báo cáo lưu chuyển tiền tệ", fontsize=18,
            fontweight="bold", color="#1f2937", va="top")
    ax.plot([0, 1], [0.945, 0.945], color="#2563eb", linewidth=2)

    unit = financials.get("unit") or "đồng"
    ax.text(0, 0.92, f"Đơn vị: {unit}", fontsize=10,
            color="#6b7280", va="top", style="italic")

    cur_label = _get(financials, "period", "current", "label") or "Kỳ này"
    prev_label = _get(financials, "period", "previous", "label")
    cf_cur = _get(financials, "cash_flow", "current") or {}
    cf_prev = _get(financials, "cash_flow", "previous") or {}

    rows = [
        ("Lưu chuyển từ HĐ kinh doanh", "grand", cf_cur.get("cf_operating"), cf_prev.get("cf_operating")),
        ("Lưu chuyển từ HĐ đầu tư", "grand", cf_cur.get("cf_investing"), cf_prev.get("cf_investing")),
        ("Lưu chuyển từ HĐ tài chính", "grand", cf_cur.get("cf_financing"), cf_prev.get("cf_financing")),
        ("Lưu chuyển tiền thuần trong kỳ", "grand", cf_cur.get("net_cf"), cf_prev.get("net_cf")),
        ("Tiền và tương đương cuối kỳ", "grand", cf_cur.get("ending_cash"), cf_prev.get("ending_cash")),
    ]
    _draw_table(ax, rows, x=0, y=0.88, width=1.0, line_height=0.034,
                show_prev=bool(cf_prev),
                cur_label=cur_label, prev_label=prev_label or "Kỳ trước")
    return fig


def _page_ratios(ratios, insights):
    fig = plt.figure(figsize=A4)
    ax = fig.add_axes([0.06, 0.05, 0.88, 0.92])
    ax.axis("off"); ax.set_xlim(0, 1); ax.set_ylim(0, 1)

    ax.text(0, 0.97, "Tỷ số tài chính", fontsize=18,
            fontweight="bold", color="#1f2937", va="top")
    ax.plot([0, 1], [0.945, 0.945], color="#2563eb", linewidth=2)

    cur_ratios = (ratios or {}).get("current") or {}
    prev_ratios = (ratios or {}).get("previous") or {}
    ratio_comments = (insights or {}).get("ratio_comments") or {}

    y = 0.92
    for cat in ("liquidity", "leverage", "profitability", "efficiency"):
        cat_data = cur_ratios.get(cat) or {}
        if not cat_data:
            continue
        if y < 0.10:
            break
        ax.text(0, y, CATEGORY_LABEL_VI.get(cat, cat).upper(),
                fontsize=12, fontweight="bold", color="#2563eb", va="top")
        y -= 0.025

        ax.text(0, y, "Chỉ tiêu", fontsize=9, fontweight="bold", color="#6b7280", va="top")
        ax.text(0.55, y, "Kỳ này", fontsize=9, fontweight="bold", color="#6b7280", va="top", ha="right")
        ax.text(0.75, y, "Kỳ trước", fontsize=9, fontweight="bold", color="#6b7280", va="top", ha="right")
        ax.text(0.95, y, "Đánh giá", fontsize=9, fontweight="bold", color="#6b7280", va="top", ha="right")
        y -= 0.018
        ax.plot([0, 1], [y + 0.005, y + 0.005], color="#e5e7eb", linewidth=0.5)

        for name, payload in cat_data.items():
            if y < 0.04:
                break
            value = payload.get("value")
            rating = payload.get("rating", "n/a")
            prev_value = ((prev_ratios.get(cat) or {}).get(name) or {}).get("value")

            label = RATIO_LABEL_VI.get(name, name)
            ax.text(0, y, label, fontsize=10, color="#374151", va="top")
            ax.text(0.55, y, _format_ratio(name, value),
                    fontsize=10, color="#111827", va="top", ha="right")
            ax.text(0.75, y, _format_ratio(name, prev_value),
                    fontsize=10, color="#6b7280", va="top", ha="right")

            box = FancyBboxPatch((0.78, y - 0.018), 0.17, 0.022,
                                 boxstyle="round,pad=0.002,rounding_size=0.005",
                                 linewidth=0,
                                 facecolor=RATING_COLOR.get(rating, "#9ca3af"),
                                 alpha=0.85, transform=ax.transAxes)
            ax.add_patch(box)
            ax.text(0.865, y - 0.007, RATING_LABEL_VI.get(rating, rating),
                    fontsize=8, color="#fff", va="center", ha="center", fontweight="bold")
            y -= 0.022

        comment = ratio_comments.get(cat)
        if comment:
            y -= 0.005
            y = _draw_block(ax, f"💡 {comment}", x=0.01, y=y, fontsize=9,
                            color="#6b7280", max_chars=110, max_lines=3,
                            line_height=0.018)
        y -= 0.018
    return fig


def _page_charts(financials, ratios):
    fig = plt.figure(figsize=A4)
    fig.suptitle("Biểu đồ phân tích", fontsize=18, fontweight="bold",
                 color="#1f2937", x=0.08, y=0.96, ha="left")

    ax_pie = fig.add_axes([0.08, 0.55, 0.40, 0.32])
    _draw_asset_pie(ax_pie, financials)

    ax_bar = fig.add_axes([0.55, 0.55, 0.40, 0.32])
    _draw_capital_pie(ax_bar, financials)

    ax_margins = fig.add_axes([0.08, 0.10, 0.40, 0.32])
    _draw_margins_bar(ax_margins, ratios)

    ax_ratios = fig.add_axes([0.55, 0.10, 0.40, 0.32])
    _draw_key_ratios_bar(ax_ratios, ratios)

    return fig


def _draw_asset_pie(ax, financials):
    a = _get(financials, "balance_sheet", "current", "assets") or {}
    parts = [
        ("Tiền & TĐ", _val(a.get("cash_and_equivalents"))),
        ("Đầu tư NH", _val(a.get("short_term_investments"))),
        ("Phải thu NH", _val(a.get("short_term_receivables"))),
        ("Tồn kho", _val(a.get("inventory"))),
        ("TSCĐ", _val(a.get("fixed_assets"))),
        ("BĐS đầu tư", _val(a.get("investment_properties"))),
        ("Đầu tư DH", _val(a.get("long_term_investments"))),
        ("TS khác", _val(a.get("other_current_assets")) + _val(a.get("other_non_current_assets"))),
    ]
    parts = [(l, v) for l, v in parts if v > 0]
    if not parts:
        ax.text(0.5, 0.5, "Không đủ dữ liệu", ha="center", va="center",
                color="#9ca3af", fontsize=11, transform=ax.transAxes)
        ax.set_title("Cơ cấu tài sản", fontsize=12, fontweight="bold")
        ax.axis("off")
        return
    labels = [p[0] for p in parts]
    values = [p[1] for p in parts]
    colors = ["#2563eb", "#3b82f6", "#60a5fa", "#93c5fd", "#10b981", "#34d399", "#6ee7b7", "#9ca3af"]
    ax.pie(values, labels=labels, autopct="%1.1f%%", colors=colors[:len(values)],
           textprops={"fontsize": 8})
    ax.set_title("Cơ cấu tài sản", fontsize=12, fontweight="bold")


def _draw_capital_pie(ax, financials):
    cur = _get(financials, "balance_sheet", "current") or {}
    total_liab = _val(_get(cur, "liabilities", "total_liabilities"))
    total_equity = _val(_get(cur, "equity", "total_equity"))
    if total_liab + total_equity <= 0:
        ax.text(0.5, 0.5, "Không đủ dữ liệu", ha="center", va="center",
                color="#9ca3af", fontsize=11, transform=ax.transAxes)
        ax.set_title("Cơ cấu nguồn vốn", fontsize=12, fontweight="bold")
        ax.axis("off")
        return
    ax.pie([total_liab, total_equity],
           labels=["Nợ phải trả", "Vốn chủ sở hữu"],
           autopct="%1.1f%%", colors=["#ef4444", "#10b981"],
           textprops={"fontsize": 9})
    ax.set_title("Cơ cấu nguồn vốn", fontsize=12, fontweight="bold")


def _draw_margins_bar(ax, ratios):
    prof = (ratios or {}).get("current", {}).get("profitability") or {}
    keys = ["gross_margin", "operating_margin", "net_margin"]
    labels = ["Biên LN gộp", "Biên LN HĐKD", "Biên LN ròng"]
    values = []
    for k in keys:
        v = (prof.get(k) or {}).get("value")
        values.append((v or 0) * 100 if v is not None else 0)
    colors = [RATING_COLOR.get((prof.get(k) or {}).get("rating", "n/a"), "#9ca3af") for k in keys]
    bars = ax.bar(labels, values, color=colors)
    for bar, v in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height(),
                f"{v:.1f}%", ha="center", va="bottom", fontsize=9)
    ax.set_title("Biên lợi nhuận", fontsize=12, fontweight="bold")
    ax.set_ylabel("%")
    ax.tick_params(axis="x", labelsize=8)
    ax.grid(axis="y", linestyle=":", alpha=0.4)


def _draw_key_ratios_bar(ax, ratios):
    cur = (ratios or {}).get("current") or {}
    items = [
        ("Hiện hành", (cur.get("liquidity") or {}).get("current_ratio")),
        ("Nhanh", (cur.get("liquidity") or {}).get("quick_ratio")),
        ("D/E", (cur.get("leverage") or {}).get("debt_to_equity")),
        ("ROA (%)", _scale_pct((cur.get("profitability") or {}).get("roa"))),
        ("ROE (%)", _scale_pct((cur.get("profitability") or {}).get("roe"))),
    ]
    labels = [it[0] for it in items]
    values = []
    colors = []
    for _label, payload in items:
        if not payload:
            values.append(0); colors.append("#9ca3af"); continue
        v = payload.get("value")
        values.append(v if isinstance(v, (int, float)) else 0)
        colors.append(RATING_COLOR.get(payload.get("rating", "n/a"), "#9ca3af"))
    bars = ax.bar(labels, values, color=colors)
    for bar, v in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height(),
                f"{v:.2f}" if abs(v) < 100 else f"{v:.0f}",
                ha="center", va="bottom", fontsize=9)
    ax.set_title("Chỉ số chính", fontsize=12, fontweight="bold")
    ax.tick_params(axis="x", labelsize=8)
    ax.grid(axis="y", linestyle=":", alpha=0.4)


def _scale_pct(payload):
    if not payload:
        return None
    v = payload.get("value")
    if v is None:
        return None
    return {"value": v * 100, "rating": payload.get("rating")}


def _pages_insights(insights):
    blocks = [
        ("✅ Điểm mạnh", insights.get("strengths") or [], "#10b981"),
        ("⚠ Điểm yếu", insights.get("weaknesses") or [], "#f59e0b"),
        ("🚨 Cảnh báo rủi ro", insights.get("red_flags") or [], "#ef4444"),
        ("📈 Xu hướng so với kỳ trước", insights.get("trends") or [], "#3b82f6"),
        ("🎯 Khuyến nghị", insights.get("recommendations") or [], "#8b5cf6"),
    ]

    pages_chunks = [blocks[:2], blocks[2:4], blocks[4:]]
    for chunk in pages_chunks:
        if not any(items for _, items, _ in chunk):
            continue
        yield _insights_page(chunk)


def _insights_page(blocks):
    fig = plt.figure(figsize=A4)
    ax = fig.add_axes([0.06, 0.05, 0.88, 0.92])
    ax.axis("off"); ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    ax.text(0, 0.97, "Phân tích & Khuyến nghị", fontsize=18,
            fontweight="bold", color="#1f2937", va="top")
    ax.plot([0, 1], [0.945, 0.945], color="#2563eb", linewidth=2)

    y = 0.91
    for title, items, color in blocks:
        if y < 0.05:
            break
        ax.text(0, y, title, fontsize=14, fontweight="bold", color=color, va="top")
        y -= 0.034
        if not items:
            ax.text(0.02, y, "(Không có)", fontsize=10, color="#9ca3af",
                    va="top", style="italic")
            y -= 0.030
            continue
        for item in items[:8]:
            if y < 0.05:
                break
            y = _draw_bullet(ax, item, x=0, y=y, fontsize=10,
                             color="#374151", max_chars=98, max_lines=4,
                             line_height=0.020)
            y -= 0.005
        y -= 0.018
    return fig


# ============= Table draw =============

def _draw_table(ax, rows, x, y, width, line_height, show_prev, cur_label, prev_label):
    # Column geometry
    label_x = x + 0.005
    cur_x = x + width * 0.62
    prev_x = x + width * 0.82
    chg_x = x + width * 0.99

    # Header
    ax.text(label_x, y, "Khoản mục", fontsize=9, fontweight="bold",
            color="#6b7280", va="top")
    ax.text(cur_x, y, cur_label, fontsize=9, fontweight="bold",
            color="#6b7280", va="top", ha="right")
    if show_prev:
        ax.text(prev_x, y, prev_label, fontsize=9, fontweight="bold",
                color="#6b7280", va="top", ha="right")
        ax.text(chg_x, y, "Thay đổi %", fontsize=9, fontweight="bold",
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

        ax.text(label_x, y, label, fontsize=fs, fontweight=font_w, color=color, va="top")
        ax.text(cur_x, y, _format_money(cv), fontsize=fs,
                fontweight=font_w, color=color, va="top", ha="right")
        if show_prev:
            ax.text(prev_x, y, _format_money(pv), fontsize=fs,
                    color="#6b7280", va="top", ha="right")
            chg_pct = _percent_change(cv, pv)
            chg_color = "#374151"
            if chg_pct is not None:
                chg_color = "#10b981" if chg_pct > 0 else ("#ef4444" if chg_pct < 0 else "#6b7280")
            ax.text(chg_x, y, _format_percent(chg_pct),
                    fontsize=fs - 0.5, color=chg_color, va="top", ha="right")
        if level == "grand":
            ax.plot([x, x + width], [y - 0.002, y - 0.002],
                    color="#9ca3af", linewidth=0.5)
        y -= line_height


# ============= Number formatting =============

def _format_money(value):
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


def _format_percent(value):
    if value is None:
        return "—"
    return f"{value:+.1f}%"


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


def _format_ratio(name, value):
    if value is None:
        return "—"
    if name in PERCENT_RATIOS:
        return f"{value * 100:.2f}%"
    return f"{value:.2f}"


def _val(x):
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return 0.0


def _get(d, *path):
    cur = d
    for k in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    return cur


# ============= Text wrapping =============

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
    ax.text(x, y, "•", fontsize=fontsize + 1, color=color, va="top", fontweight="bold")
    used = _draw_block(ax, str(text), x=x + 0.018, y=y,
                       fontsize=fontsize, color=color,
                       max_chars=max_chars, max_lines=max_lines,
                       line_height=line_height)
    return used


# ============= Debug report (trace) =============

def _trace_sections(trace: dict) -> list:
    a1 = trace.get("agent1", {}) or {}
    a2 = trace.get("agent2", {}) or {}
    a3 = trace.get("agent3", {}) or {}

    sections = [
        ("Tổng quan", [
            ("Job ID", trace.get("job_id", "?")),
            ("Created", trace.get("created_at", "?")),
            ("Input file", f"{a1.get('input_file','?')} ({a1.get('input_size_bytes',0)} bytes, {a1.get('input_type','?')})"),
            ("Pipeline duration", f"{trace.get('total_elapsed_sec', '?')} s"),
            ("Models", f"A1={a1.get('model')}, A2={a2.get('model')}"),
        ]),
        ("Agent 1 — INPUT", [
            ("File", a1.get("input_file", "?")),
            ("Type", a1.get("input_type", "?")),
            ("Size (bytes)", str(a1.get("input_size_bytes", "?"))),
        ]),
        ("Agent 1 — OUTPUT (raw transcription)", [
            ("Transcription", _get(a1, "financials", "raw_transcription") or "(none)"),
        ]),
        ("Agent 1 — OUTPUT (structured financials)", [
            ("Financials", json.dumps(a1.get("financials", {}), ensure_ascii=False, indent=2)),
        ]),
        ("Agent 1 — meta", [
            ("Model", a1.get("model", "?")),
            ("Elapsed (s)", str(a1.get("elapsed_sec", "?"))),
            ("Input tokens", str((a1.get("usage") or {}).get("input_tokens", "?"))),
            ("Output tokens", str((a1.get("usage") or {}).get("output_tokens", "?"))),
            ("Thinking trace", a1.get("thinking", "") or "(none)"),
        ]),
        ("Agent 2 — INPUT (financials)", [
            ("Financials", json.dumps(a2.get("input_financials", {}), ensure_ascii=False, indent=2)),
        ]),
        ("Agent 2 — OUTPUT (computed ratios — Python)", [
            ("Ratios", json.dumps(a2.get("ratios", {}), ensure_ascii=False, indent=2)),
        ]),
        ("Agent 2 — OUTPUT (qualitative insights — Claude)", [
            ("Insights", json.dumps(a2.get("insights", {}), ensure_ascii=False, indent=2)),
        ]),
        ("Agent 2 — meta", [
            ("Model", a2.get("model", "?")),
            ("Elapsed (s)", str(a2.get("elapsed_sec", "?"))),
            ("Input tokens", str((a2.get("usage") or {}).get("input_tokens", "?"))),
            ("Output tokens", str((a2.get("usage") or {}).get("output_tokens", "?"))),
            ("Thinking trace", a2.get("thinking", "") or "(none)"),
        ]),
        ("Agent 3 — meta", [
            ("Output PDF", a3.get("output_path", "?")),
            ("Pages", str(a3.get("pages", "?"))),
            ("Elapsed (s)", str(a3.get("elapsed_sec", "?"))),
        ]),
    ]
    return sections


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
    return fig


def _section_pages(title: str, fields: list):
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


def _make_section_page(title: str, lines: list):
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


def _wrap_block(text: str, width: int) -> list:
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
