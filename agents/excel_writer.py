"""Agent 8b: Xuất dữ liệu định giá ra file Excel (openpyxl).

Sheets:
  1. Tổng quan         - Company / period / fair value summary
  2. KQKD              - Income Statement (current + prior)
  3. BCĐKT             - Balance Sheet (current + prior)
  4. LCTT              - Cash flow (nếu có)
  5. Tỷ số             - 17 tỷ số (current + prior + tăng trưởng YoY)
  6. Dự phóng 5Y       - Doanh thu / EBITDA / FCF 5 năm
  7. Định giá          - DCF assumptions + multiples + fair value
  8. Sensitivity       - Sensitivity matrix WACC / Growth
  9. Đối thủ ngành     - Competitors list
  10. Investment Thesis - Headline / drivers / catalysts / risks
"""
import time
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from agents.report_style import COLORS

# ---------- Styles (đồng bộ với report_style) ----------
def _hex(c: str) -> str:
    return c.lstrip("#").upper()


HEADER_FONT = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
HEADER_FILL = PatternFill("solid", fgColor=_hex(COLORS["primary"]))
SECTION_FONT = Font(name="Calibri", size=11, bold=True, color=_hex(COLORS["primary"]))
SECTION_FILL = PatternFill("solid", fgColor=_hex(COLORS["primary_light"]))
LABEL_FONT = Font(name="Calibri", size=10, bold=True, color=_hex(COLORS["text_strong"]))
BODY_FONT = Font(name="Calibri", size=10, color=_hex(COLORS["text"]))
MUTED_FONT = Font(name="Calibri", size=9, italic=True, color=_hex(COLORS["text_muted"]))
TOTAL_FILL = PatternFill("solid", fgColor=_hex(COLORS["surface_alt"]))
GOOD_FILL = PatternFill("solid", fgColor=_hex(COLORS["good_light"]))
WARN_FILL = PatternFill("solid", fgColor=_hex(COLORS["warning_light"]))
POOR_FILL = PatternFill("solid", fgColor=_hex(COLORS["poor_light"]))

THIN = Side(style="thin", color=_hex(COLORS["border"]))
ALL_BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
BOTTOM_BORDER = Border(bottom=THIN)


# ---------- Public API ----------
def export_excel(payload: dict, output_path: str) -> dict:
    """Build XLSX file from full pipeline payload."""
    t0 = time.time()
    financials = (payload.get("extracted") or {}).get("financials") or {}
    industry = (payload.get("industry") or {}).get("industry") or {}
    business = (payload.get("business") or {}).get("business") or {}
    ratios = payload.get("ratios") or {}
    projection = (payload.get("projection") or {}).get("projection") or {}
    valuation = payload.get("valuation") or {}
    thesis = (payload.get("thesis") or {}).get("thesis") or {}

    wb = Workbook()
    wb.remove(wb.active)

    _sheet_overview(wb, financials, business, valuation, thesis)
    _sheet_income_statement(wb, financials)
    _sheet_balance_sheet(wb, financials)
    _sheet_cash_flow(wb, financials)
    _sheet_ratios(wb, ratios)
    _sheet_projection(wb, projection, financials.get("unit"))
    _sheet_valuation(wb, valuation, financials.get("unit"))
    _sheet_sensitivity(wb, valuation)
    _sheet_industry(wb, industry)
    _sheet_thesis(wb, thesis)

    wb.save(output_path)
    return {
        "elapsed_sec": round(time.time() - t0, 2),
        "output_path": output_path,
        "size_bytes": Path(output_path).stat().st_size,
        "sheets": [s.title for s in wb.worksheets],
    }


# ---------- Sheet builders ----------
def _sheet_overview(wb, financials, business, valuation, thesis):
    ws = wb.create_sheet("Tổng quan")
    company = financials.get("company") or {}
    period = financials.get("period") or {}
    cur_label = (period.get("current") or {}).get("label") or "—"
    prev_label = (period.get("previous") or {}).get("label") or "—"
    summary = valuation.get("summary") or {}
    es = thesis.get("executive_summary") or {}

    rows = [
        ("Tên doanh nghiệp", company.get("name")),
        ("Mã số thuế", company.get("tax_code")),
        ("Địa chỉ", company.get("address")),
        ("Ngành (BCTC)", company.get("industry")),
        ("Loại báo cáo", company.get("report_type")),
        ("Đơn vị", financials.get("unit") or "đồng"),
        ("Kỳ hiện tại", cur_label),
        ("Kỳ trước", prev_label),
        ("Vị thế cạnh tranh", business.get("competitive_position")),
        ("Giai đoạn tăng trưởng", business.get("growth_stage")),
    ]
    _write_section_title(ws, 1, 1, "THÔNG TIN DOANH NGHIỆP", span=2)
    _write_kv_block(ws, rows, start_row=3)

    next_row = 3 + len(rows) + 1
    _write_section_title(ws, next_row, 1, "TÓM TẮT ĐỊNH GIÁ", span=2)
    val_rows = [
        ("Fair value low", summary.get("fair_value_low")),
        ("Fair value mid", summary.get("fair_value_mid")),
        ("Fair value high", summary.get("fair_value_high")),
        (f"Sau chiết khấu thiểu số ({summary.get('minority_discount_pct') or 0}%)",
         summary.get("fair_value_after_minority_discount")),
    ]
    _write_kv_block(ws, val_rows, start_row=next_row + 2, value_format="#,##0")

    next_row = next_row + 2 + len(val_rows) + 1
    if es.get("headline"):
        _write_section_title(ws, next_row, 1, "EXECUTIVE SUMMARY", span=2)
        ws.cell(next_row + 2, 1, "Headline").font = LABEL_FONT
        c = ws.cell(next_row + 2, 2, es.get("headline"))
        c.alignment = Alignment(wrap_text=True, vertical="top")
        c.font = BODY_FONT
        ws.cell(next_row + 3, 1, "Khuyến nghị").font = LABEL_FONT
        c = ws.cell(next_row + 3, 2, es.get("recommendation"))
        c.alignment = Alignment(wrap_text=True, vertical="top")
        c.font = BODY_FONT

    ws.column_dimensions["A"].width = 38
    ws.column_dimensions["B"].width = 80
    ws.freeze_panes = "A2"


def _sheet_income_statement(wb, financials):
    ws = wb.create_sheet("KQKD")
    is_data = financials.get("income_statement") or {}
    cur = is_data.get("current") or {}
    prev = is_data.get("previous") or {}
    period = financials.get("period") or {}
    cur_label = (period.get("current") or {}).get("label") or "Kỳ này"
    prev_label = (period.get("previous") or {}).get("label") or "Kỳ trước"

    fields = [
        ("revenue", "Doanh thu bán hàng và cung cấp dịch vụ"),
        ("revenue_deductions", "Các khoản giảm trừ doanh thu"),
        ("net_revenue", "Doanh thu thuần"),
        ("cogs", "Giá vốn hàng bán"),
        ("gross_profit", "Lợi nhuận gộp"),
        ("financial_income", "Doanh thu hoạt động tài chính"),
        ("financial_expense", "Chi phí tài chính"),
        ("interest_expense", "  Trong đó: Chi phí lãi vay"),
        ("selling_expense", "Chi phí bán hàng"),
        ("admin_expense", "Chi phí quản lý doanh nghiệp"),
        ("operating_profit", "Lợi nhuận thuần từ HĐKD"),
        ("other_income", "Thu nhập khác"),
        ("other_expense", "Chi phí khác"),
        ("other_profit", "Lợi nhuận khác"),
        ("profit_before_tax", "Tổng lợi nhuận kế toán trước thuế"),
        ("current_tax", "Chi phí thuế TNDN hiện hành"),
        ("deferred_tax", "Chi phí thuế TNDN hoãn lại"),
        ("net_profit_after_tax", "Lợi nhuận sau thuế TNDN"),
        ("ebitda", "EBITDA"),
    ]
    _write_financial_table(ws, fields, cur, prev, cur_label, prev_label)
    ws.freeze_panes = "B2"


def _sheet_balance_sheet(wb, financials):
    ws = wb.create_sheet("BCĐKT")
    bs = financials.get("balance_sheet") or {}
    cur = bs.get("current") or {}
    prev = bs.get("previous") or {}
    period = financials.get("period") or {}
    cur_label = (period.get("current") or {}).get("label") or "Kỳ này"
    prev_label = (period.get("previous") or {}).get("label") or "Kỳ trước"

    sections = [
        ("TÀI SẢN", [
            ("assets.current_assets.cash", "Tiền và tương đương tiền"),
            ("assets.current_assets.short_term_investments", "Đầu tư tài chính ngắn hạn"),
            ("assets.current_assets.receivables", "Các khoản phải thu ngắn hạn"),
            ("assets.current_assets.inventory", "Hàng tồn kho"),
            ("assets.current_assets.other_current_assets", "TS ngắn hạn khác"),
            ("assets.current_assets.total_current_assets", "Tổng tài sản ngắn hạn", "total"),
            ("assets.non_current_assets.long_term_receivables", "Phải thu dài hạn"),
            ("assets.non_current_assets.fixed_assets", "Tài sản cố định"),
            ("assets.non_current_assets.investment_property", "Bất động sản đầu tư"),
            ("assets.non_current_assets.long_term_investments", "Đầu tư tài chính dài hạn"),
            ("assets.non_current_assets.other_non_current_assets", "TS dài hạn khác"),
            ("assets.non_current_assets.total_non_current_assets", "Tổng tài sản dài hạn", "total"),
            ("assets.total_assets", "TỔNG CỘNG TÀI SẢN", "grand"),
        ]),
        ("NGUỒN VỐN", [
            ("liabilities.current_liabilities.short_term_debt", "Vay & nợ ngắn hạn"),
            ("liabilities.current_liabilities.payables", "Phải trả người bán"),
            ("liabilities.current_liabilities.other_current_liabilities", "Nợ ngắn hạn khác"),
            ("liabilities.current_liabilities.total_current_liabilities", "Tổng nợ ngắn hạn", "total"),
            ("liabilities.non_current_liabilities.long_term_debt", "Vay & nợ dài hạn"),
            ("liabilities.non_current_liabilities.other_non_current_liabilities", "Nợ dài hạn khác"),
            ("liabilities.non_current_liabilities.total_non_current_liabilities", "Tổng nợ dài hạn", "total"),
            ("liabilities.total_liabilities", "TỔNG NỢ PHẢI TRẢ", "total"),
            ("equity.contributed_capital", "Vốn góp"),
            ("equity.retained_earnings", "Lợi nhuận sau thuế chưa phân phối"),
            ("equity.other_equity", "Quỹ và VCSH khác"),
            ("equity.total_equity", "TỔNG VỐN CHỦ SỞ HỮU", "total"),
        ]),
    ]

    headers = ["Khoản mục", cur_label, prev_label, "Δ tuyệt đối", "Δ %"]
    for col, h in enumerate(headers, 1):
        c = ws.cell(1, col, h)
        c.font = HEADER_FONT
        c.fill = HEADER_FILL
        c.alignment = Alignment(horizontal="center" if col > 1 else "left")
    row = 2
    for section_title, items in sections:
        c = ws.cell(row, 1, section_title)
        c.font = SECTION_FONT
        c.fill = SECTION_FILL
        for col in range(2, 6):
            ws.cell(row, col).fill = SECTION_FILL
        row += 1
        for item in items:
            path = item[0]
            label = item[1]
            level = item[2] if len(item) > 2 else "leaf"
            cv = _deep_get(cur, path)
            pv = _deep_get(prev, path)
            ws.cell(row, 1, label).font = LABEL_FONT if level in ("total", "grand") else BODY_FONT
            for col, v in enumerate([cv, pv], 2):
                if v is not None:
                    cc = ws.cell(row, col, float(v))
                    cc.number_format = "#,##0"
                    cc.font = LABEL_FONT if level in ("total", "grand") else BODY_FONT
            if cv is not None and pv is not None:
                diff = cv - pv
                ws.cell(row, 4, diff).number_format = "#,##0"
                if pv:
                    ws.cell(row, 5, diff / abs(pv)).number_format = "+0.0%;-0.0%;0.0%"
            if level == "grand":
                for col in range(1, 6):
                    cell = ws.cell(row, col)
                    cell.fill = TOTAL_FILL
                    cell.font = LABEL_FONT
            row += 1
        row += 1
    _autosize(ws, [None, 18, 18, 18, 12])
    ws.column_dimensions["A"].width = 50
    ws.freeze_panes = "B2"


def _sheet_cash_flow(wb, financials):
    cf = financials.get("cash_flow") or {}
    cur = cf.get("current") or {}
    if not cur and not (cf.get("previous") or {}):
        return  # bỏ sheet nếu không có LCTT

    ws = wb.create_sheet("LCTT")
    prev = cf.get("previous") or {}
    period = financials.get("period") or {}
    cur_label = (period.get("current") or {}).get("label") or "Kỳ này"
    prev_label = (period.get("previous") or {}).get("label") or "Kỳ trước"
    fields = [
        ("operating_cash_flow", "Lưu chuyển tiền thuần từ HĐKD"),
        ("investing_cash_flow", "Lưu chuyển tiền thuần từ HĐ đầu tư"),
        ("financing_cash_flow", "Lưu chuyển tiền thuần từ HĐ tài chính"),
        ("net_cash_flow", "Lưu chuyển tiền thuần trong kỳ"),
        ("free_cash_flow", "Free cash flow (FCF)"),
        ("capex", "Capex (đầu tư TSCĐ)"),
    ]
    _write_financial_table(ws, fields, cur, prev, cur_label, prev_label)
    ws.freeze_panes = "B2"


def _sheet_ratios(wb, ratios_payload):
    ws = wb.create_sheet("Tỷ số")
    ratios = ratios_payload.get("ratios") or {}
    cur = ratios.get("current") or {}
    prev = ratios.get("prior") or ratios.get("previous") or {}
    growth = ratios_payload.get("growth") or {}

    categories = [
        ("Thanh khoản", [
            ("current_ratio", "Hệ số TT hiện hành", "ratio"),
            ("quick_ratio", "Hệ số TT nhanh", "ratio"),
            ("cash_ratio", "Hệ số TT tiền mặt", "ratio"),
        ]),
        ("Đòn bẩy / Cơ cấu vốn", [
            ("debt_ratio", "Hệ số nợ / TS", "pct"),
            ("debt_to_equity", "Nợ / VCSH", "ratio"),
            ("equity_multiplier", "Hệ số nhân VCSH", "ratio"),
            ("interest_coverage", "Khả năng trả lãi vay", "ratio"),
            ("debt_to_ebitda", "Nợ / EBITDA", "ratio"),
        ]),
        ("Khả năng sinh lời", [
            ("gross_margin", "Biên LN gộp", "pct"),
            ("operating_margin", "Biên LN HĐKD", "pct"),
            ("ebitda_margin", "Biên EBITDA", "pct"),
            ("net_margin", "Biên LN ròng", "pct"),
            ("roa", "ROA", "pct"),
            ("roe", "ROE", "pct"),
        ]),
        ("Hiệu quả hoạt động", [
            ("asset_turnover", "Vòng quay tổng TS", "ratio"),
            ("inventory_turnover", "Vòng quay HTK", "ratio"),
            ("receivables_turnover", "Vòng quay phải thu", "ratio"),
        ]),
    ]

    for col, h in enumerate(["Tỷ số", "Kỳ này", "Kỳ trước", "Δ"], 1):
        c = ws.cell(1, col, h)
        c.font = HEADER_FONT
        c.fill = HEADER_FILL
        c.alignment = Alignment(horizontal="center" if col > 1 else "left")

    row = 2
    for cat_name, items in categories:
        c = ws.cell(row, 1, cat_name)
        c.font = SECTION_FONT; c.fill = SECTION_FILL
        for col in range(2, 5):
            ws.cell(row, col).fill = SECTION_FILL
        row += 1
        for key, label, kind in items:
            cv = cur.get(key)
            pv = prev.get(key)
            ws.cell(row, 1, label).font = BODY_FONT
            fmt = "0.00%" if kind == "pct" else "0.00"
            for col, v in enumerate([cv, pv], 2):
                if v is not None:
                    cc = ws.cell(row, col, float(v))
                    cc.number_format = fmt
                    cc.font = BODY_FONT
            if cv is not None and pv is not None and pv:
                ws.cell(row, 4, (cv - pv) / abs(pv)).number_format = "+0.0%;-0.0%;0.0%"
            row += 1
        row += 1

    # Growth block
    yoy = growth.get("yoy") or {}
    if yoy:
        c = ws.cell(row, 1, "Tăng trưởng YoY")
        c.font = SECTION_FONT; c.fill = SECTION_FILL
        for col in range(2, 5):
            ws.cell(row, col).fill = SECTION_FILL
        row += 1
        for k, label in [
            ("revenue_growth", "Tăng trưởng doanh thu"),
            ("net_profit_growth", "Tăng trưởng LNST"),
            ("ebitda_growth", "Tăng trưởng EBITDA"),
            ("asset_growth", "Tăng trưởng tổng tài sản"),
            ("equity_growth", "Tăng trưởng VCSH"),
        ]:
            v = yoy.get(k)
            ws.cell(row, 1, label).font = BODY_FONT
            if v is not None:
                cc = ws.cell(row, 2, float(v))
                cc.number_format = "+0.0%;-0.0%;0.0%"
                cc.font = BODY_FONT
            row += 1

    ws.column_dimensions["A"].width = 36
    ws.column_dimensions["B"].width = 14
    ws.column_dimensions["C"].width = 14
    ws.column_dimensions["D"].width = 12
    ws.freeze_panes = "B2"


def _sheet_projection(wb, projection, unit):
    ws = wb.create_sheet("Dự phóng 5Y")
    years = projection.get("years") or []
    if not years:
        ws.cell(1, 1, "Không có dữ liệu dự phóng.").font = MUTED_FONT
        return
    headers = ["Khoản mục"] + [str(y.get("year") or f"Y{i+1}") for i, y in enumerate(years)]
    for col, h in enumerate(headers, 1):
        c = ws.cell(1, col, h)
        c.font = HEADER_FONT; c.fill = HEADER_FILL
        c.alignment = Alignment(horizontal="center" if col > 1 else "left")
    fields = [
        ("revenue", "Doanh thu"),
        ("revenue_growth", "Tăng trưởng DT (%)", "pct"),
        ("gross_profit", "Lợi nhuận gộp"),
        ("ebitda", "EBITDA"),
        ("ebitda_margin", "Biên EBITDA (%)", "pct"),
        ("operating_profit", "EBIT"),
        ("net_profit", "LNST"),
        ("capex", "Capex"),
        ("working_capital_change", "Δ Vốn lưu động"),
        ("free_cash_flow", "Free Cash Flow"),
    ]
    row = 2
    for item in fields:
        key = item[0]; label = item[1]
        kind = item[2] if len(item) > 2 else "money"
        ws.cell(row, 1, label).font = LABEL_FONT
        for i, y in enumerate(years):
            v = y.get(key)
            if v is not None:
                cc = ws.cell(row, i + 2, float(v))
                cc.number_format = "0.00%" if kind == "pct" else "#,##0"
                cc.font = BODY_FONT
        row += 1

    if unit:
        ws.cell(row + 1, 1, f"(Đơn vị: {unit}, trừ %)").font = MUTED_FONT
    ws.column_dimensions["A"].width = 32
    for i in range(len(years)):
        ws.column_dimensions[get_column_letter(i + 2)].width = 16
    ws.freeze_panes = "B2"

    # assumptions block
    asum = projection.get("assumptions") or {}
    if asum:
        ws.cell(row + 3, 1, "GIẢ ĐỊNH DỰ PHÓNG").font = SECTION_FONT
        rr = row + 4
        for k, v in asum.items():
            ws.cell(rr, 1, str(k)).font = LABEL_FONT
            ws.cell(rr, 2, v if isinstance(v, (int, float, str)) else str(v)).font = BODY_FONT
            rr += 1


def _sheet_valuation(wb, valuation, unit):
    ws = wb.create_sheet("Định giá")
    summary = valuation.get("summary") or {}
    methods = summary.get("method_values") or []
    dcf = valuation.get("dcf") or {}
    multiples = valuation.get("multiples") or {}

    _write_section_title(ws, 1, 1, "FAIR VALUE SUMMARY", span=2)
    rows = [
        ("Fair value low", summary.get("fair_value_low")),
        ("Fair value mid", summary.get("fair_value_mid")),
        ("Fair value high", summary.get("fair_value_high")),
        (f"Sau chiết khấu thiểu số ({summary.get('minority_discount_pct') or 0}%)",
         summary.get("fair_value_after_minority_discount")),
    ]
    _write_kv_block(ws, rows, start_row=3, value_format="#,##0")

    row = 3 + len(rows) + 2
    _write_section_title(ws, row, 1, "GIÁ TRỊ THEO PHƯƠNG PHÁP", span=3)
    row += 2
    for col, h in enumerate(["Phương pháp", "Equity Value", "Trọng số"], 1):
        c = ws.cell(row, col, h); c.font = LABEL_FONT
    row += 1
    for m in methods:
        ws.cell(row, 1, m.get("method") or "—").font = BODY_FONT
        if m.get("equity_value") is not None:
            ws.cell(row, 2, float(m["equity_value"])).number_format = "#,##0"
        if m.get("weight") is not None:
            ws.cell(row, 3, float(m["weight"])).number_format = "0.0%"
        row += 1

    row += 2
    _write_section_title(ws, row, 1, "DCF ASSUMPTIONS", span=2)
    row += 2
    dcf_a = dcf.get("assumptions") or {}
    for k, v in dcf_a.items():
        ws.cell(row, 1, str(k)).font = LABEL_FONT
        ws.cell(row, 2, v if isinstance(v, (int, float, str)) else str(v)).font = BODY_FONT
        if isinstance(v, float) and abs(v) < 1:
            ws.cell(row, 2).number_format = "0.00%"
        row += 1

    row += 2
    _write_section_title(ws, row, 1, "MULTIPLES", span=4)
    row += 2
    for col, h in enumerate(["Multiple", "Median", "Min", "Max"], 1):
        c = ws.cell(row, col, h); c.font = LABEL_FONT
    row += 1
    for mtype in ("ev_ebitda", "pe", "pb", "ps"):
        block = multiples.get(mtype) or {}
        if not block:
            continue
        ws.cell(row, 1, mtype.upper()).font = BODY_FONT
        for col, k in enumerate(["median", "min", "max"], 2):
            v = block.get(k)
            if v is not None:
                ws.cell(row, col, float(v)).number_format = "0.0"
        row += 1

    if unit:
        ws.cell(row + 2, 1, f"(Đơn vị: {unit})").font = MUTED_FONT
    ws.column_dimensions["A"].width = 38
    ws.column_dimensions["B"].width = 18
    ws.column_dimensions["C"].width = 14
    ws.column_dimensions["D"].width = 14


def _sheet_sensitivity(wb, valuation):
    sens = valuation.get("sensitivity") or {}
    matrix = sens.get("wacc_growth_matrix") or sens.get("matrix") or []
    if not matrix:
        return
    ws = wb.create_sheet("Sensitivity")
    ws.cell(1, 1, "Sensitivity matrix (WACC × Terminal growth)").font = SECTION_FONT
    headers = sens.get("growth_headers") or sens.get("col_headers") or []
    waccs = sens.get("wacc_headers") or sens.get("row_headers") or []
    for col, h in enumerate(headers, 2):
        c = ws.cell(3, col, _fmt_pct_label(h))
        c.font = HEADER_FONT; c.fill = HEADER_FILL
        c.alignment = Alignment(horizontal="center")
    for r_idx, wacc in enumerate(waccs):
        ws.cell(4 + r_idx, 1, _fmt_pct_label(wacc)).font = LABEL_FONT
    for r_idx, row in enumerate(matrix):
        for c_idx, val in enumerate(row):
            if val is not None:
                cc = ws.cell(4 + r_idx, 2 + c_idx, float(val))
                cc.number_format = "#,##0"
                cc.font = BODY_FONT
    ws.column_dimensions["A"].width = 14
    for i in range(len(headers)):
        ws.column_dimensions[get_column_letter(2 + i)].width = 16
    ws.freeze_panes = "B4"


def _sheet_industry(wb, industry):
    ws = wb.create_sheet("Phân tích ngành")
    rows = [
        ("Ngành xác định", industry.get("industry_name")),
        ("Cơ sở phân loại", industry.get("industry_classification_basis")),
        ("Tổng quan ngành", industry.get("industry_overview")),
        ("CAGR ngành 5Y (%)", industry.get("industry_cagr_5y_pct")),
    ]
    ms = industry.get("market_size") or {}
    rows += [
        ("TAM (tỷ VND)", ms.get("tam_vnd_billion")),
        ("SAM (tỷ VND)", ms.get("sam_vnd_billion")),
        ("SOM (tỷ VND)", ms.get("som_vnd_billion")),
        ("Thị phần DN (%)", ms.get("company_market_share_pct")),
        ("Giả định market size", ms.get("assumptions")),
    ]
    _write_section_title(ws, 1, 1, "TỔNG QUAN NGÀNH", span=2)
    _write_kv_block(ws, rows, start_row=3)
    next_row = 3 + len(rows) + 2

    competitors = industry.get("key_competitors") or []
    if competitors:
        _write_section_title(ws, next_row, 1, "ĐỐI THỦ CẠNH TRANH", span=4)
        next_row += 2
        for col, h in enumerate(["Tên", "Doanh thu ước (tỷ)", "Thị phần (%)", "Ghi chú"], 1):
            c = ws.cell(next_row, col, h); c.font = LABEL_FONT
        next_row += 1
        for cp in competitors:
            ws.cell(next_row, 1, cp.get("name") or "—").font = BODY_FONT
            if cp.get("estimated_revenue_vnd_billion") is not None:
                ws.cell(next_row, 2, float(cp["estimated_revenue_vnd_billion"])).number_format = "#,##0.0"
            if cp.get("market_share_pct") is not None:
                ws.cell(next_row, 3, float(cp["market_share_pct"])).number_format = "0.0\"%\""
            ws.cell(next_row, 4, cp.get("note") or "").font = BODY_FONT
            next_row += 1

    next_row += 2
    drivers = industry.get("industry_growth_drivers") or []
    risks = industry.get("industry_risks") or []
    barriers = industry.get("barriers_to_entry") or []
    for title, items in [
        ("DRIVER TĂNG TRƯỞNG", drivers),
        ("RỦI RO NGÀNH", risks),
        ("RÀO CẢN GIA NHẬP", barriers),
    ]:
        if not items:
            continue
        _write_section_title(ws, next_row, 1, title, span=2)
        next_row += 1
        for it in items:
            ws.cell(next_row, 1, "•").font = BODY_FONT
            c = ws.cell(next_row, 2, str(it))
            c.alignment = Alignment(wrap_text=True, vertical="top")
            c.font = BODY_FONT
            next_row += 1
        next_row += 1

    ws.column_dimensions["A"].width = 30
    ws.column_dimensions["B"].width = 70
    ws.column_dimensions["C"].width = 16
    ws.column_dimensions["D"].width = 50


def _sheet_thesis(wb, thesis):
    ws = wb.create_sheet("Investment Thesis")
    es = thesis.get("executive_summary") or {}
    it = thesis.get("investment_thesis") or {}
    deal = thesis.get("deal_recommendation") or {}

    _write_section_title(ws, 1, 1, "EXECUTIVE SUMMARY", span=2)
    rows = [
        ("Headline", es.get("headline")),
        ("Khuyến nghị", es.get("recommendation")),
        ("Driver chính", "; ".join(es.get("key_drivers") or [])),
    ]
    _write_kv_block(ws, rows, start_row=3)
    next_row = 3 + len(rows) + 2

    points = it.get("thesis_points") or []
    if points:
        _write_section_title(ws, next_row, 1, "LUẬN ĐIỂM ĐẦU TƯ", span=3)
        next_row += 2
        for col, h in enumerate(["#", "Tiêu đề", "Luận điểm + Bằng chứng"], 1):
            c = ws.cell(next_row, col, h); c.font = LABEL_FONT
        next_row += 1
        for i, p in enumerate(points, 1):
            ws.cell(next_row, 1, i).font = BODY_FONT
            ws.cell(next_row, 2, p.get("title") or "").font = LABEL_FONT
            body = p.get("thesis") or ""
            if p.get("evidence"):
                body += f"\n\nBằng chứng: {p['evidence']}"
            c = ws.cell(next_row, 3, body)
            c.alignment = Alignment(wrap_text=True, vertical="top")
            c.font = BODY_FONT
            ws.row_dimensions[next_row].height = 80
            next_row += 1
        next_row += 1

    cats = it.get("catalysts") or []
    if cats:
        _write_section_title(ws, next_row, 1, "CATALYSTS", span=3)
        next_row += 2
        for col, h in enumerate(["Loại", "Mô tả", "Horizon"], 1):
            c = ws.cell(next_row, col, h); c.font = LABEL_FONT
        next_row += 1
        for c in cats:
            ws.cell(next_row, 1, (c.get("type") or "").upper()).font = LABEL_FONT
            cc = ws.cell(next_row, 2, c.get("description") or "")
            cc.alignment = Alignment(wrap_text=True, vertical="top"); cc.font = BODY_FONT
            ws.cell(next_row, 3, c.get("horizon") or "").font = BODY_FONT
            ws.cell(next_row, 1).fill = GOOD_FILL
            next_row += 1
        next_row += 1

    risks = it.get("risks") or []
    if risks:
        _write_section_title(ws, next_row, 1, "RỦI RO", span=4)
        next_row += 2
        for col, h in enumerate(["Loại", "Mức độ", "Mô tả", "Mitigation"], 1):
            c = ws.cell(next_row, col, h); c.font = LABEL_FONT
        next_row += 1
        for r in risks:
            sev = (r.get("severity") or "").upper()
            ws.cell(next_row, 1, (r.get("type") or "").upper()).font = LABEL_FONT
            sev_cell = ws.cell(next_row, 2, sev)
            sev_cell.font = LABEL_FONT
            if sev == "HIGH":
                sev_cell.fill = POOR_FILL
            elif sev == "MEDIUM":
                sev_cell.fill = WARN_FILL
            elif sev == "LOW":
                sev_cell.fill = GOOD_FILL
            cc = ws.cell(next_row, 3, r.get("description") or "")
            cc.alignment = Alignment(wrap_text=True, vertical="top"); cc.font = BODY_FONT
            cc = ws.cell(next_row, 4, r.get("mitigation") or "")
            cc.alignment = Alignment(wrap_text=True, vertical="top"); cc.font = BODY_FONT
            next_row += 1
        next_row += 1

    if deal:
        _write_section_title(ws, next_row, 1, "KHUYẾN NGHỊ DEAL", span=2)
        next_row += 2
        deal_rows = [
            ("Mục tiêu", deal.get("primary_objective")),
            ("Khoảng giá trị", deal.get("fair_value_range_text")),
            ("Entry price", deal.get("entry_price_recommendation")),
            ("Cấu trúc deal", deal.get("deal_structure")),
            ("Bước tiếp theo", "\n".join(f"{i}. {s}" for i, s in enumerate(deal.get("next_steps") or [], 1))),
        ]
        _write_kv_block(ws, deal_rows, start_row=next_row)

    ws.column_dimensions["A"].width = 26
    ws.column_dimensions["B"].width = 36
    ws.column_dimensions["C"].width = 64
    ws.column_dimensions["D"].width = 40


# ---------- Helpers ----------
def _deep_get(d: dict, dotted_path: str):
    cur = d
    for k in dotted_path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    return cur


def _write_section_title(ws, row, col, text, span=1):
    c = ws.cell(row, col, text)
    c.font = HEADER_FONT
    c.fill = HEADER_FILL
    c.alignment = Alignment(horizontal="left", vertical="center")
    if span > 1:
        ws.merge_cells(start_row=row, start_column=col, end_row=row, end_column=col + span - 1)
        for k in range(1, span):
            ws.cell(row, col + k).fill = HEADER_FILL


def _write_kv_block(ws, rows, start_row, value_format=None):
    for i, (k, v) in enumerate(rows):
        ws.cell(start_row + i, 1, k).font = LABEL_FONT
        if v is None or v == "":
            ws.cell(start_row + i, 2, "—").font = MUTED_FONT
        elif isinstance(v, (int, float)) and not isinstance(v, bool):
            cc = ws.cell(start_row + i, 2, float(v))
            cc.number_format = value_format or "#,##0.00"
            cc.font = BODY_FONT
        else:
            cc = ws.cell(start_row + i, 2, str(v))
            cc.alignment = Alignment(wrap_text=True, vertical="top")
            cc.font = BODY_FONT


def _write_financial_table(ws, fields, cur, prev, cur_label, prev_label):
    headers = ["Khoản mục", cur_label, prev_label, "Δ tuyệt đối", "Δ %"]
    for col, h in enumerate(headers, 1):
        c = ws.cell(1, col, h)
        c.font = HEADER_FONT
        c.fill = HEADER_FILL
        c.alignment = Alignment(horizontal="center" if col > 1 else "left")
    for i, (key, label) in enumerate(fields, 2):
        cv = cur.get(key)
        pv = prev.get(key)
        ws.cell(i, 1, label).font = BODY_FONT
        for col, v in enumerate([cv, pv], 2):
            if v is not None:
                cc = ws.cell(i, col, float(v))
                cc.number_format = "#,##0"
                cc.font = BODY_FONT
        if cv is not None and pv is not None:
            ws.cell(i, 4, cv - pv).number_format = "#,##0"
            if pv:
                ws.cell(i, 5, (cv - pv) / abs(pv)).number_format = "+0.0%;-0.0%;0.0%"
    ws.column_dimensions["A"].width = 50
    ws.column_dimensions["B"].width = 18
    ws.column_dimensions["C"].width = 18
    ws.column_dimensions["D"].width = 18
    ws.column_dimensions["E"].width = 12


def _autosize(ws, widths):
    for i, w in enumerate(widths, 1):
        if w:
            ws.column_dimensions[get_column_letter(i)].width = w


def _fmt_pct_label(v):
    if v is None:
        return ""
    try:
        f = float(v)
        return f"{f * 100:.1f}%" if abs(f) < 1 else f"{f:.1f}%"
    except (TypeError, ValueError):
        return str(v)
