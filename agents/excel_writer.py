"""Agent 8b: Xuất dữ liệu định giá ra file Excel (openpyxl).

Sheets:
  1. Tổng quan         - Company / period / fair value summary
  2. KQKD              - Income Statement (current + previous)
  3. BCĐKT             - Balance Sheet (current + previous)
  4. LCTT              - Cash flow (nếu BCTC có)
  5. Tỷ số             - 17 tỷ số (current + previous + tăng trưởng YoY)
  6. Dự phóng 5Y       - Doanh thu / EBITDA / FCFF 5 năm + giả định
  7. Định giá          - DCF + Multiples + fair value
  8. Sensitivity       - Sensitivity matrix WACC × Terminal growth
  9. Phân tích ngành   - TAM/SAM/SOM, đối thủ, drivers, risks
  10. Investment Thesis - Headline / drivers / catalysts / risks / deal

Schemas tương ứng:
  - extractor.py: balance_sheet.{current,previous}.{assets|liabilities|equity}
                  income_statement.{current,previous}.{revenue,...,net_profit_after_tax}
                  cash_flow.{current,previous}.{cf_operating,cf_investing,...}
                  period.{current,previous}.label
  - projector.py:  projection.projections[i].{revenue, growth_pct, ebit, ebitda,
                   net_income, capex, change_in_wc, fcff, ebitda_margin_pct, ...}
  - valuator.py:   valuation.{assumptions, dcf, multiples, sensitivity, summary}
                   sensitivity.matrix = [{wacc_pct, values: [{terminal_growth_pct, equity_value}]}]
                   summary.method_values = [{method, equity_value}]
                   multiples.<key> = {multiple, equity_value, ...}  (NO median/min/max)
  - analyzer.py:   ratios = {current, previous, changes}; growth = {revenue_yoy, ...}
"""
import time
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill, Side
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
BASE_HIGHLIGHT_FILL = PatternFill("solid", fgColor=_hex(COLORS["primary_light"]))

THIN_SIDE = Side(style="thin", color=_hex(COLORS["border"]))


# ---------- Public API ----------
def export_excel(payload: dict, output_path: str) -> dict:
    """Build XLSX from full pipeline payload. Returns metadata dict."""
    t0 = time.time()
    financials = (payload.get("extracted") or {}).get("financials") or {}
    industry = (payload.get("industry") or {}).get("industry") or {}
    business = (payload.get("business") or {}).get("business") or {}
    ratios_payload = payload.get("ratios") or {}
    projection = (payload.get("projection") or {}).get("projection") or {}
    valuation = payload.get("valuation") or {}
    thesis = (payload.get("thesis") or {}).get("thesis") or {}

    wb = Workbook()
    wb.remove(wb.active)

    # Mỗi sheet bị xử lý qua try/except riêng — schema drift sẽ gắn ghi chú vào sheet
    # thay vì sập cả file Excel.
    _safe(_sheet_methodology, wb)
    _safe(_sheet_overview, wb, financials, business, valuation, thesis)
    _safe(_sheet_income_statement, wb, financials)
    _safe(_sheet_balance_sheet, wb, financials)
    _safe(_sheet_cash_flow, wb, financials)
    _safe(_sheet_ratios, wb, ratios_payload)
    _safe(_sheet_projection, wb, projection, financials.get("unit"))
    _safe(_sheet_valuation, wb, valuation, financials.get("unit"))
    _safe(_sheet_sensitivity, wb, valuation)
    _safe(_sheet_industry, wb, industry)
    _safe(_sheet_thesis, wb, thesis)

    # Đảm bảo workbook luôn có ít nhất 1 sheet (openpyxl yêu cầu).
    if not wb.worksheets:
        ws = wb.create_sheet("Empty")
        ws.cell(1, 1, "Không có dữ liệu khả dụng để xuất.").font = MUTED_FONT

    wb.save(output_path)
    return {
        "elapsed_sec": round(time.time() - t0, 2),
        "output_path": output_path,
        "size_bytes": Path(output_path).stat().st_size,
        "sheets": [s.title for s in wb.worksheets],
    }


def _safe(builder, wb, *args, **kwargs):
    """Wrap a sheet builder so a schema-drift error in one sheet doesn't kill the export."""
    try:
        builder(wb, *args, **kwargs)
    except Exception as exc:
        title = builder.__name__.replace("_sheet_", "").replace("_", " ").title()
        ws = wb.create_sheet(f"⚠ {title[:25]}")
        ws.cell(1, 1, f"Sheet '{title}' lỗi khi xuất:").font = LABEL_FONT
        ws.cell(2, 1, repr(exc)).font = MUTED_FONT
        ws.column_dimensions["A"].width = 90


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
    if es.get("headline") or es.get("recommendation"):
        _write_section_title(ws, next_row, 1, "EXECUTIVE SUMMARY", span=2)
        ws.cell(next_row + 2, 1, "Headline").font = LABEL_FONT
        c = ws.cell(next_row + 2, 2, es.get("headline") or "—")
        c.alignment = Alignment(wrap_text=True, vertical="top")
        c.font = BODY_FONT
        ws.cell(next_row + 3, 1, "Khuyến nghị").font = LABEL_FONT
        c = ws.cell(next_row + 3, 2, es.get("recommendation") or "—")
        c.alignment = Alignment(wrap_text=True, vertical="top")
        c.font = BODY_FONT

    ws.column_dimensions["A"].width = 38
    ws.column_dimensions["B"].width = 80
    ws.freeze_panes = "A2"


def _sheet_income_statement(wb, financials):
    ws = wb.create_sheet("KQKD")
    is_data = financials.get("income_statement") or {}
    cur = is_data.get("current") or {}
    prev = is_data.get("previous") if isinstance(is_data.get("previous"), dict) else {}
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
        ("operating_profit", "Lợi nhuận thuần từ HĐKD (EBIT)"),
        ("other_income", "Thu nhập khác"),
        ("other_expense", "Chi phí khác"),
        ("profit_before_tax", "Tổng lợi nhuận kế toán trước thuế"),
        ("current_tax", "Chi phí thuế TNDN hiện hành"),
        ("deferred_tax", "Chi phí thuế TNDN hoãn lại"),
        ("net_profit_after_tax", "Lợi nhuận sau thuế TNDN"),
        ("eps", "EPS"),
    ]
    _write_financial_table(ws, fields, cur, prev, cur_label, prev_label)
    ws.freeze_panes = "B2"


def _sheet_balance_sheet(wb, financials):
    ws = wb.create_sheet("BCĐKT")
    bs = financials.get("balance_sheet") or {}
    cur = bs.get("current") or {}
    prev = bs.get("previous") if isinstance(bs.get("previous"), dict) else {}
    period = financials.get("period") or {}
    cur_label = (period.get("current") or {}).get("label") or "Kỳ này"
    prev_label = (period.get("previous") or {}).get("label") or "Kỳ trước"

    a_cur = cur.get("assets") or {}
    a_prev = prev.get("assets") or {} if isinstance(prev, dict) else {}
    l_cur = cur.get("liabilities") or {}
    l_prev = prev.get("liabilities") or {} if isinstance(prev, dict) else {}
    e_cur = cur.get("equity") or {}
    e_prev = prev.get("equity") or {} if isinstance(prev, dict) else {}

    sections = [
        ("TÀI SẢN", [
            ("Tài sản ngắn hạn", "subheader"),
            ("Tiền và TĐ tiền", a_cur.get("cash_and_equivalents"), a_prev.get("cash_and_equivalents")),
            ("Đầu tư TC ngắn hạn", a_cur.get("short_term_investments"), a_prev.get("short_term_investments")),
            ("Phải thu ngắn hạn", a_cur.get("short_term_receivables"), a_prev.get("short_term_receivables")),
            ("Hàng tồn kho", a_cur.get("inventory"), a_prev.get("inventory")),
            ("TS ngắn hạn khác", a_cur.get("other_current_assets"), a_prev.get("other_current_assets")),
            ("Tổng tài sản ngắn hạn", a_cur.get("current_assets_total"), a_prev.get("current_assets_total"), "total"),
            ("Tài sản dài hạn", "subheader"),
            ("Phải thu dài hạn", a_cur.get("long_term_receivables"), a_prev.get("long_term_receivables")),
            ("Tài sản cố định", a_cur.get("fixed_assets"), a_prev.get("fixed_assets")),
            ("Bất động sản đầu tư", a_cur.get("investment_properties"), a_prev.get("investment_properties")),
            ("Đầu tư TC dài hạn", a_cur.get("long_term_investments"), a_prev.get("long_term_investments")),
            ("TS dài hạn khác", a_cur.get("other_non_current_assets"), a_prev.get("other_non_current_assets")),
            ("Tổng tài sản dài hạn", a_cur.get("non_current_assets_total"), a_prev.get("non_current_assets_total"), "total"),
            ("TỔNG CỘNG TÀI SẢN", a_cur.get("total_assets"), a_prev.get("total_assets"), "grand"),
        ]),
        ("NGUỒN VỐN", [
            ("Nợ phải trả ngắn hạn", "subheader"),
            ("Vay & nợ ngắn hạn", l_cur.get("short_term_debt"), l_prev.get("short_term_debt")),
            ("Phải trả người bán", l_cur.get("accounts_payable"), l_prev.get("accounts_payable")),
            ("Nợ ngắn hạn khác", l_cur.get("other_current_liabilities"), l_prev.get("other_current_liabilities")),
            ("Tổng nợ ngắn hạn", l_cur.get("current_liabilities_total"), l_prev.get("current_liabilities_total"), "total"),
            ("Nợ phải trả dài hạn", "subheader"),
            ("Vay & nợ dài hạn", l_cur.get("long_term_debt"), l_prev.get("long_term_debt")),
            ("Nợ dài hạn khác", l_cur.get("other_non_current_liabilities"), l_prev.get("other_non_current_liabilities")),
            ("Tổng nợ dài hạn", l_cur.get("non_current_liabilities_total"), l_prev.get("non_current_liabilities_total"), "total"),
            ("TỔNG NỢ PHẢI TRẢ", l_cur.get("total_liabilities"), l_prev.get("total_liabilities"), "grand"),
            ("Vốn chủ sở hữu", "subheader"),
            ("Vốn góp CSH", e_cur.get("share_capital"), e_prev.get("share_capital")),
            ("LN sau thuế chưa phân phối", e_cur.get("retained_earnings"), e_prev.get("retained_earnings")),
            ("VCSH khác", e_cur.get("other_equity"), e_prev.get("other_equity")),
            ("TỔNG VỐN CHỦ SỞ HỮU", e_cur.get("total_equity"), e_prev.get("total_equity"), "grand"),
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
            label = item[0]
            if len(item) == 2 and item[1] == "subheader":
                cell = ws.cell(row, 1, label)
                cell.font = Font(name="Calibri", size=10, bold=True, italic=True,
                                 color=_hex(COLORS["text_muted"]))
                row += 1
                continue
            cv = item[1]; pv = item[2]
            level = item[3] if len(item) > 3 else "leaf"
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

    ws.column_dimensions["A"].width = 50
    ws.column_dimensions["B"].width = 18
    ws.column_dimensions["C"].width = 18
    ws.column_dimensions["D"].width = 18
    ws.column_dimensions["E"].width = 12
    ws.freeze_panes = "B2"


def _sheet_cash_flow(wb, financials):
    cf = financials.get("cash_flow") or {}
    cur = cf.get("current") or {}
    prev = cf.get("previous") if isinstance(cf.get("previous"), dict) else {}
    if not cur and not prev:
        return  # bỏ sheet nếu không có LCTT trong BCTC

    ws = wb.create_sheet("LCTT")
    period = financials.get("period") or {}
    cur_label = (period.get("current") or {}).get("label") or "Kỳ này"
    prev_label = (period.get("previous") or {}).get("label") or "Kỳ trước"
    fields = [
        ("cf_operating", "Lưu chuyển tiền thuần từ HĐKD"),
        ("cf_investing", "Lưu chuyển tiền thuần từ HĐ đầu tư"),
        ("cf_financing", "Lưu chuyển tiền thuần từ HĐ tài chính"),
        ("net_cf", "Lưu chuyển tiền thuần trong kỳ"),
        ("ending_cash", "Tiền và tương đương tiền cuối kỳ"),
    ]
    _write_financial_table(ws, fields, cur, prev, cur_label, prev_label)
    ws.freeze_panes = "B2"


def _sheet_ratios(wb, ratios_payload):
    """Tỷ số tài chính + cột công thức để kế toán audit dễ.

    LƯU Ý: analyzer.py phát ratios theo cấu trúc nested:
      ratios.current = {liquidity: {current_ratio: {value, rating}, ...},
                        leverage: {...}, profitability: {...}, efficiency: {...}}
    Cần flatten về {ratio_name: value} trước khi tra cứu.
    """
    ws = wb.create_sheet("Tỷ số")
    ratios = ratios_payload.get("ratios") or {}
    cur_flat = _flatten_ratios(ratios.get("current"))
    prev_flat = _flatten_ratios(ratios.get("previous") or ratios.get("prior"))
    growth = ratios_payload.get("growth") or {}

    # (key, label_VI, kind, formula_text). kind: "pct_frac" = fraction → display as %.
    categories = [
        ("Thanh khoản", [
            ("current_ratio", "Hệ số TT hiện hành", "ratio",
             "= current_assets_total / current_liabilities_total"),
            ("quick_ratio", "Hệ số TT nhanh", "ratio",
             "= (current_assets_total − inventory) / current_liabilities_total"),
            ("cash_ratio", "Hệ số TT tiền mặt", "ratio",
             "= (cash + short_term_investments) / current_liabilities_total"),
        ]),
        ("Đòn bẩy / Cơ cấu vốn", [
            ("debt_ratio", "Hệ số nợ / TS", "pct_frac",
             "= total_liabilities / total_assets"),
            ("debt_to_equity", "Nợ / VCSH", "ratio",
             "= total_liabilities / total_equity"),
            ("equity_multiplier", "Hệ số nhân VCSH", "ratio",
             "= total_assets / total_equity"),
            ("interest_coverage", "Khả năng trả lãi vay", "ratio",
             "= operating_profit / interest_expense"),
            ("debt_to_ebitda", "Nợ / EBITDA", "ratio",
             "= total_liabilities / EBITDA*  (* EBIT proxy nếu thiếu D&A)"),
        ]),
        ("Khả năng sinh lời", [
            ("gross_margin", "Biên LN gộp", "pct_frac",
             "= gross_profit / net_revenue"),
            ("operating_margin", "Biên LN HĐKD", "pct_frac",
             "= operating_profit / net_revenue"),
            ("ebitda_margin", "Biên EBITDA", "pct_frac",
             "= EBITDA* / net_revenue  (* EBIT proxy nếu thiếu D&A)"),
            ("net_margin", "Biên LN ròng", "pct_frac",
             "= net_profit_after_tax / net_revenue"),
            ("roa", "ROA", "pct_frac",
             "= net_profit_after_tax / total_assets"),
            ("roe", "ROE", "pct_frac",
             "= net_profit_after_tax / total_equity"),
        ]),
        ("Hiệu quả hoạt động", [
            ("asset_turnover", "Vòng quay tổng TS", "ratio",
             "= net_revenue / total_assets"),
            ("inventory_turnover", "Vòng quay HTK", "ratio",
             "= cogs / inventory"),
            ("receivables_turnover", "Vòng quay phải thu", "ratio",
             "= net_revenue / short_term_receivables"),
        ]),
    ]

    headers = ["Tỷ số", "Kỳ này", "Kỳ trước", "Δ", "Công thức"]
    for col, h in enumerate(headers, 1):
        c = ws.cell(1, col, h)
        c.font = HEADER_FONT
        c.fill = HEADER_FILL
        c.alignment = Alignment(horizontal="center" if col > 1 and col < 5 else "left")

    row = 2
    for cat_name, items in categories:
        c = ws.cell(row, 1, cat_name)
        c.font = SECTION_FONT; c.fill = SECTION_FILL
        for col in range(2, 6):
            ws.cell(row, col).fill = SECTION_FILL
        row += 1
        for key, label, kind, formula in items:
            cv = cur_flat.get(key)
            pv = prev_flat.get(key)
            ws.cell(row, 1, label).font = BODY_FONT
            fmt = "0.00%" if kind == "pct_frac" else "0.00"
            for col, v in enumerate([cv, pv], 2):
                if isinstance(v, (int, float)):
                    cc = ws.cell(row, col, float(v))
                    cc.number_format = fmt
                    cc.font = BODY_FONT
            if isinstance(cv, (int, float)) and isinstance(pv, (int, float)) and pv:
                ws.cell(row, 4, (cv - pv) / abs(pv)).number_format = "+0.0%;-0.0%;0.0%"
            f_cell = ws.cell(row, 5, formula)
            f_cell.font = Font(name="Consolas", size=9, color=_hex(COLORS["primary"]))
            f_cell.alignment = Alignment(wrap_text=True, vertical="center")
            row += 1
        row += 1

    # Growth block: analyzer._compute_growth output, fields đã ở dạng fraction.
    if growth:
        c = ws.cell(row, 1, "Tăng trưởng YoY")
        c.font = SECTION_FONT; c.fill = SECTION_FILL
        for col in range(2, 6):
            ws.cell(row, col).fill = SECTION_FILL
        row += 1
        growth_items = [
            ("revenue_yoy", "Tăng trưởng doanh thu",
             "= (revenue_current − revenue_previous) / |revenue_previous|"),
            ("gross_profit_yoy", "Tăng trưởng LN gộp",
             "= (gross_profit_current − gross_profit_previous) / |…|"),
            ("ebit_yoy", "Tăng trưởng EBIT",
             "= (operating_profit_current − operating_profit_previous) / |…|"),
            ("net_income_yoy", "Tăng trưởng LNST",
             "= (net_profit_after_tax_current − …_previous) / |…_previous|"),
            ("total_assets_yoy", "Tăng trưởng tổng tài sản",
             "= (total_assets_current − total_assets_previous) / |…|"),
            ("total_equity_yoy", "Tăng trưởng VCSH",
             "= (total_equity_current − total_equity_previous) / |…|"),
        ]
        for k, label, formula in growth_items:
            v = growth.get(k)
            ws.cell(row, 1, label).font = BODY_FONT
            if isinstance(v, (int, float)):
                cc = ws.cell(row, 2, float(v))
                cc.number_format = "+0.0%;-0.0%;0.0%"
                cc.font = BODY_FONT
            f_cell = ws.cell(row, 5, formula)
            f_cell.font = Font(name="Consolas", size=9, color=_hex(COLORS["primary"]))
            f_cell.alignment = Alignment(wrap_text=True, vertical="center")
            row += 1
        row += 1

    # Footer pointer to source file.
    ws.cell(row + 1, 1, "📁 Sửa công thức tại: agents/analyzer.py · _compute_period_ratios (line 84) · _compute_growth (line 200)").font = MUTED_FONT
    ws.merge_cells(start_row=row + 1, start_column=1, end_row=row + 1, end_column=5)

    ws.column_dimensions["A"].width = 36
    ws.column_dimensions["B"].width = 14
    ws.column_dimensions["C"].width = 14
    ws.column_dimensions["D"].width = 12
    ws.freeze_panes = "B2"


def _sheet_projection(wb, projection, unit):
    ws = wb.create_sheet("Dự phóng 5Y")
    projections = projection.get("projections") or []
    if not projections:
        ws.cell(1, 1, "Không có dữ liệu dự phóng.").font = MUTED_FONT
        ws.column_dimensions["A"].width = 60
        return

    headers = ["Khoản mục"] + [
        p.get("year_label") or f"Y{p.get('year_index') or i+1}"
        for i, p in enumerate(projections)
    ]
    for col, h in enumerate(headers, 1):
        c = ws.cell(1, col, h)
        c.font = HEADER_FONT; c.fill = HEADER_FILL
        c.alignment = Alignment(horizontal="center" if col > 1 else "left")

    # (key trong projector.py output, label hiển thị, kiểu format)
    fields = [
        ("revenue",            "Doanh thu",           "money"),
        ("growth_pct",         "Tăng trưởng DT (%)",  "pct_already"),
        ("cogs",               "Giá vốn",             "money"),
        ("gross_profit",       "Lợi nhuận gộp",       "money"),
        ("operating_expense",  "OPEX",                "money"),
        ("ebit",               "EBIT",                "money"),
        ("depreciation",       "Khấu hao (D&A)",      "money"),
        ("ebitda",             "EBITDA",              "money"),
        ("ebitda_margin_pct",  "Biên EBITDA (%)",     "pct_already"),
        ("interest_expense",   "Chi phí lãi vay",     "money"),
        ("profit_before_tax",  "LN trước thuế",       "money"),
        ("tax",                "Thuế TNDN",           "money"),
        ("net_income",         "LNST",                "money"),
        ("net_margin_pct",     "Biên LN ròng (%)",    "pct_already"),
        ("capex",              "Capex",               "money"),
        ("change_in_wc",       "Δ Vốn lưu động",      "money"),
        ("fcff",               "FCFF (Free CF firm)", "money"),
    ]
    row = 2
    for key, label, kind in fields:
        ws.cell(row, 1, label).font = LABEL_FONT
        for i, p in enumerate(projections):
            v = p.get(key)
            if isinstance(v, (int, float)):
                cc = ws.cell(row, i + 2, float(v))
                cc.number_format = "0.00\"%\"" if kind == "pct_already" else "#,##0"
                cc.font = BODY_FONT
        row += 1

    if unit:
        ws.cell(row + 1, 1, f"(Đơn vị: {unit}, trừ %)").font = MUTED_FONT
    ws.column_dimensions["A"].width = 32
    for i in range(len(projections)):
        ws.column_dimensions[get_column_letter(i + 2)].width = 16
    ws.freeze_panes = "B2"

    # Assumptions block.
    asum = projection.get("assumptions") or {}
    if asum:
        ws.cell(row + 3, 1, "GIẢ ĐỊNH DỰ PHÓNG").font = SECTION_FONT
        rr = row + 4
        for k, v in asum.items():
            ws.cell(rr, 1, str(k)).font = LABEL_FONT
            display = ", ".join(map(str, v)) if isinstance(v, list) else str(v) if v is not None else "—"
            ws.cell(rr, 2, display).font = BODY_FONT
            ws.cell(rr, 2).alignment = Alignment(wrap_text=True, vertical="top")
            rr += 1

    # Summary block.
    summary = projection.get("summary_5y") or {}
    if summary:
        ws.cell(rr + 1, 1, "TÓM TẮT 5 NĂM").font = SECTION_FONT
        rr += 2
        for k, label in [
            ("revenue_cagr_pct", "CAGR doanh thu (%)"),
            ("ebitda_cagr_pct", "CAGR EBITDA (%)"),
            ("fcff_cumulative", "FCFF cộng dồn"),
            ("comments", "Nhận xét"),
        ]:
            v = summary.get(k)
            ws.cell(rr, 1, label).font = LABEL_FONT
            if isinstance(v, (int, float)):
                cc = ws.cell(rr, 2, float(v))
                cc.number_format = "0.00\"%\"" if "pct" in k else "#,##0"
                cc.font = BODY_FONT
            elif v:
                ws.cell(rr, 2, str(v)).font = BODY_FONT
                ws.cell(rr, 2).alignment = Alignment(wrap_text=True, vertical="top")
            rr += 1


def _sheet_valuation(wb, valuation, unit):
    ws = wb.create_sheet("Định giá")
    summary = valuation.get("summary") or {}
    methods = summary.get("method_values") or []
    dcf = valuation.get("dcf") or {}
    multiples = valuation.get("multiples") or {}
    assumptions = valuation.get("assumptions") or {}

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
    _write_section_title(ws, row, 1, "GIÁ TRỊ THEO PHƯƠNG PHÁP", span=2)
    row += 2
    for col, h in enumerate(["Phương pháp", "Equity Value"], 1):
        c = ws.cell(row, col, h); c.font = LABEL_FONT
        c.fill = TOTAL_FILL
    row += 1
    if methods:
        for m in methods:
            ws.cell(row, 1, m.get("method") or "—").font = BODY_FONT
            ev = m.get("equity_value")
            if isinstance(ev, (int, float)):
                cc = ws.cell(row, 2, float(ev))
                cc.number_format = "#,##0"
                cc.font = BODY_FONT
            row += 1
    else:
        ws.cell(row, 1, "(Không có)").font = MUTED_FONT
        row += 1

    # DCF detail — tổng quan.
    row += 2
    _write_section_title(ws, row, 1, "DCF (FCFF) — Tổng quan + Công thức", span=3)
    row += 1
    ws.cell(row, 1, "📁 Sửa công thức tại: agents/valuator.py · _dcf_valuation (line 157)").font = MUTED_FONT
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=3)
    row += 1
    formula_font = Font(name="Consolas", size=9, color=_hex(COLORS["primary"]))
    dcf_rows = [
        ("WACC (%)", dcf.get("wacc_pct"), "0.00\"%\"",
         "AI đề xuất (valuator._claude_assumptions)"),
        ("Terminal growth g (%)", dcf.get("terminal_growth_pct"), "0.00\"%\"",
         "AI đề xuất, thường ~ inflation (3-4%)"),
        ("Σ PV(FCFF) — 5 năm explicit", dcf.get("pv_explicit_fcff"), "#,##0",
         "= Σ FCFF_t / (1+WACC)^t,  t=1..5"),
        ("Terminal Value (TV)", dcf.get("terminal_value"), "#,##0",
         "= FCFF_5 × (1+g) / (WACC − g)"),
        ("PV(Terminal Value)", dcf.get("pv_terminal"), "#,##0",
         "= TV / (1+WACC)^5"),
        ("Enterprise Value (EV)", dcf.get("enterprise_value"), "#,##0",
         "= Σ PV(FCFF) + PV(TV)"),
        ("Trừ Total Debt", dcf.get("debt_subtracted"), "#,##0",
         "Mặc định = total_liabilities. Sửa tại valuator.py line 28."),
        ("Equity Value (DCF)  ⭐", dcf.get("equity_value"), "#,##0",
         "= EV − Total_Debt"),
    ]
    for label, val, fmt, formula in dcf_rows:
        ws.cell(row, 1, label).font = LABEL_FONT
        if isinstance(val, (int, float)):
            cc = ws.cell(row, 2, float(val))
            cc.number_format = fmt
            cc.font = BODY_FONT
        f_cell = ws.cell(row, 3, formula)
        f_cell.font = formula_font
        f_cell.alignment = Alignment(wrap_text=True, vertical="center")
        row += 1
    if dcf.get("note"):
        ws.cell(row, 1, "Ghi chú").font = LABEL_FONT
        c = ws.cell(row, 2, dcf["note"])
        c.alignment = Alignment(wrap_text=True, vertical="top")
        c.font = MUTED_FONT
        row += 1

    # PV breakdown table — bước tính từng năm.
    pv_breakdown = dcf.get("pv_breakdown") or []
    if pv_breakdown:
        row += 1
        _write_section_title(ws, row, 1, "DCF — Bước tính PV từng năm (audit-friendly)", span=5)
        row += 1
        ws.cell(row, 1,
                "Mỗi dòng: lấy FCFF của năm × (1/(1+WACC)^t) = PV. Cộng dồn cột PV ra Σ PV(FCFF) ở trên.").font = MUTED_FONT
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=5)
        row += 1
        wacc_pct = dcf.get("wacc_pct")
        wacc_decimal_str = f"{wacc_pct/100:.4f}" if isinstance(wacc_pct, (int, float)) else "WACC"
        for col, h in enumerate(
                ["Năm (t)", "FCFF", "Discount factor (1/(1+WACC)^t)", "PV = FCFF / (1+WACC)^t",
                 "Diễn giải bước tính"], 1):
            c = ws.cell(row, col, h)
            c.font = LABEL_FONT
            c.fill = TOTAL_FILL
        row += 1
        for it in pv_breakdown:
            t = it.get("year")
            fcff = it.get("fcff")
            df = it.get("discount_factor")
            pv = it.get("pv")
            ws.cell(row, 1, t).font = BODY_FONT
            for col, v, fmt in [(2, fcff, "#,##0"), (3, df, "0.0000"), (4, pv, "#,##0")]:
                if isinstance(v, (int, float)):
                    cc = ws.cell(row, col, float(v))
                    cc.number_format = fmt
                    cc.font = BODY_FONT
            # Bước tính bằng số cụ thể.
            if isinstance(fcff, (int, float)) and isinstance(df, (int, float)) and isinstance(t, int):
                explain = (f"= {int(fcff):,} ÷ (1+{wacc_decimal_str})^{t} "
                           f"= {int(fcff):,} × {df:.4f}")
            else:
                explain = ""
            f_cell = ws.cell(row, 5, explain)
            f_cell.font = formula_font
            f_cell.alignment = Alignment(wrap_text=True, vertical="center")
            row += 1

        # Sum row.
        ws.cell(row, 1, "Σ").font = LABEL_FONT
        ws.cell(row, 1).fill = TOTAL_FILL
        if isinstance(dcf.get("pv_explicit_fcff"), (int, float)):
            cc = ws.cell(row, 4, float(dcf["pv_explicit_fcff"]))
            cc.number_format = "#,##0"
            cc.font = LABEL_FONT
            cc.fill = TOTAL_FILL
        ws.cell(row, 5, "Σ PV(FCFF) các năm = số ở dòng 'Σ PV(FCFF) — 5 năm explicit' phía trên").font = MUTED_FONT
        row += 1

    # Sensitivity pointer.
    row += 1
    ws.cell(row, 1, "📁 Xem sheet 'Sensitivity' để biết equity value thay đổi thế nào "
                    "khi WACC/g sai khác base case.").font = MUTED_FONT
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=4)
    row += 1

    # Multiples block.
    row += 2
    _write_section_title(ws, row, 1, "MULTIPLES — chi tiết", span=4)
    row += 2
    for col, h in enumerate(["Multiple", "Giá trị multiple", "Input cơ sở", "Equity Value"], 1):
        c = ws.cell(row, col, h); c.font = LABEL_FONT
    row += 1
    multiple_keys = [
        ("ev_ebitda", "EV/EBITDA", "ebitda_input"),
        ("pe", "P/E", "net_income_input"),
        ("pb", "P/B", "book_value_input"),
    ]
    for key, label, input_key in multiple_keys:
        block = multiples.get(key) or {}
        ws.cell(row, 1, label).font = BODY_FONT
        if isinstance(block.get("multiple"), (int, float)):
            ws.cell(row, 2, float(block["multiple"])).number_format = "0.0\"x\""
        if isinstance(block.get(input_key), (int, float)):
            cc = ws.cell(row, 3, float(block[input_key]))
            cc.number_format = "#,##0"
        ev = block.get("equity_value")
        if isinstance(ev, (int, float)):
            cc = ws.cell(row, 4, float(ev))
            cc.number_format = "#,##0"
        if block.get("note"):
            cc = ws.cell(row, 4, block["note"])
            cc.font = MUTED_FONT
        row += 1

    # Assumptions block (top-level valuation.assumptions).
    if assumptions:
        row += 2
        _write_section_title(ws, row, 1, "GIẢ ĐỊNH ĐỊNH GIÁ", span=2)
        row += 2
        for k, v in assumptions.items():
            ws.cell(row, 1, str(k)).font = LABEL_FONT
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                cc = ws.cell(row, 2, float(v))
                cc.number_format = "0.00\"%\"" if "pct" in str(k) else "0.00"
                cc.font = BODY_FONT
            elif isinstance(v, dict):
                cc = ws.cell(row, 2, ", ".join(f"{kk}={vv}" for kk, vv in v.items()))
                cc.alignment = Alignment(wrap_text=True, vertical="top")
                cc.font = BODY_FONT
            elif isinstance(v, list):
                cc = ws.cell(row, 2, "; ".join(map(_summarize_item, v)))
                cc.alignment = Alignment(wrap_text=True, vertical="top")
                cc.font = BODY_FONT
            elif v is not None:
                cc = ws.cell(row, 2, str(v))
                cc.alignment = Alignment(wrap_text=True, vertical="top")
                cc.font = BODY_FONT
            row += 1

    if unit:
        ws.cell(row + 2, 1, f"(Đơn vị giá trị: {unit})").font = MUTED_FONT
    ws.column_dimensions["A"].width = 38
    ws.column_dimensions["B"].width = 22
    ws.column_dimensions["C"].width = 50
    ws.column_dimensions["D"].width = 22
    ws.column_dimensions["E"].width = 60


def _sheet_sensitivity(wb, valuation):
    sens = valuation.get("sensitivity") or {}
    matrix = sens.get("matrix") or []
    growth_axis = sens.get("growth_axis_pct") or []
    if not matrix or not growth_axis:
        return

    ws = wb.create_sheet("Sensitivity")
    ws.cell(1, 1, "Sensitivity matrix — Equity Value theo WACC × Terminal growth").font = SECTION_FONT
    ws.cell(2, 1, f"Base case: WACC={sens.get('base_wacc_pct')}%, g={sens.get('base_growth_pct')}%").font = MUTED_FONT
    base_w = sens.get("base_wacc_pct")
    base_g = sens.get("base_growth_pct")

    # Header row: g axis.
    ws.cell(4, 1, "WACC \\ g").font = HEADER_FONT
    ws.cell(4, 1).fill = HEADER_FILL
    for col, g in enumerate(growth_axis, 2):
        c = ws.cell(4, col, f"g={g}%")
        c.font = HEADER_FONT; c.fill = HEADER_FILL
        c.alignment = Alignment(horizontal="center")

    # Body rows.
    for r_idx, mrow in enumerate(matrix):
        if not isinstance(mrow, dict):
            continue
        wacc = mrow.get("wacc_pct")
        ws_row = 5 + r_idx
        wacc_cell = ws.cell(ws_row, 1, f"WACC={wacc}%" if wacc is not None else "—")
        wacc_cell.font = LABEL_FONT
        wacc_cell.fill = HEADER_FILL
        wacc_cell.font = HEADER_FONT
        values = mrow.get("values") or []
        for c_idx, val in enumerate(values):
            if not isinstance(val, dict):
                continue
            ev = val.get("equity_value")
            g_val = val.get("terminal_growth_pct")
            cell = ws.cell(ws_row, 2 + c_idx)
            if isinstance(ev, (int, float)):
                cell.value = float(ev)
                cell.number_format = "#,##0"
                cell.font = BODY_FONT
            else:
                cell.value = "—"
                cell.font = MUTED_FONT
            # Highlight base case.
            if (isinstance(wacc, (int, float)) and isinstance(base_w, (int, float)) and abs(wacc - base_w) < 0.01
                    and isinstance(g_val, (int, float)) and isinstance(base_g, (int, float)) and abs(g_val - base_g) < 0.01):
                cell.fill = BASE_HIGHLIGHT_FILL
                cell.font = LABEL_FONT

    ws.column_dimensions["A"].width = 16
    for i in range(len(growth_axis)):
        ws.column_dimensions[get_column_letter(2 + i)].width = 18
    ws.freeze_panes = "B5"


def _sheet_industry(wb, industry):
    ws = wb.create_sheet("Phân tích ngành")
    rows = [
        ("Ngành xác định", industry.get("industry_name")),
        ("Cơ sở phân loại", industry.get("industry_classification_basis")),
        ("Tổng quan ngành", industry.get("industry_overview")),
        ("Triển vọng 3 năm", industry.get("industry_outlook_3y")),
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
            c.fill = TOTAL_FILL
        next_row += 1
        for cp in competitors:
            ws.cell(next_row, 1, cp.get("name") or "—").font = BODY_FONT
            v = cp.get("estimated_revenue_vnd_billion")
            if isinstance(v, (int, float)):
                ws.cell(next_row, 2, float(v)).number_format = "#,##0.0"
            v = cp.get("market_share_pct")
            if isinstance(v, (int, float)):
                ws.cell(next_row, 3, float(v)).number_format = "0.0\"%\""
            cc = ws.cell(next_row, 4, cp.get("note") or "")
            cc.alignment = Alignment(wrap_text=True, vertical="top")
            cc.font = BODY_FONT
            next_row += 1

    next_row += 2
    drivers = industry.get("industry_growth_drivers") or []
    risks = industry.get("industry_risks") or []
    barriers = industry.get("barriers_to_entry") or []
    trends = industry.get("industry_trends") or []
    for title, items in [
        ("DRIVER TĂNG TRƯỞNG", drivers),
        ("XU HƯỚNG", trends),
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
            c = ws.cell(next_row, col, h); c.font = LABEL_FONT; c.fill = TOTAL_FILL
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
            c = ws.cell(next_row, col, h); c.font = LABEL_FONT; c.fill = TOTAL_FILL
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
            c = ws.cell(next_row, col, h); c.font = LABEL_FONT; c.fill = TOTAL_FILL
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
            if isinstance(v, (int, float)):
                cc = ws.cell(i, col, float(v))
                cc.number_format = "#,##0"
                cc.font = BODY_FONT
        if isinstance(cv, (int, float)) and isinstance(pv, (int, float)):
            ws.cell(i, 4, cv - pv).number_format = "#,##0"
            if pv:
                ws.cell(i, 5, (cv - pv) / abs(pv)).number_format = "+0.0%;-0.0%;0.0%"
    ws.column_dimensions["A"].width = 50
    ws.column_dimensions["B"].width = 18
    ws.column_dimensions["C"].width = 18
    ws.column_dimensions["D"].width = 18
    ws.column_dimensions["E"].width = 12


def _summarize_item(item):
    if isinstance(item, dict):
        # Most common: comparable companies — show name only.
        for key in ("name", "title", "label"):
            if item.get(key):
                return str(item[key])
        return ", ".join(f"{k}={v}" for k, v in item.items() if v is not None)[:80]
    return str(item)


def _flatten_ratios(rated):
    """Convert analyzer's nested {category: {name: {value, rating}}} → flat {name: value}.

    analyzer.py emits ratios under 4 categories (liquidity / leverage / profitability /
    efficiency). This sheet displays them by category but accesses values flatly.
    """
    flat: dict = {}
    if not isinstance(rated, dict):
        return flat
    for cat, items in rated.items():
        if not isinstance(items, dict):
            continue
        for name, payload in items.items():
            if isinstance(payload, dict):
                flat[name] = payload.get("value")
            else:
                flat[name] = payload
    return flat


# ---------- Methodology sheet ----------
# (Calculation, Type, Formula, Source file:function — line gần đúng).
# Sửa file/line ở đây nếu code Python được di chuyển sau này.
_METHODOLOGY_ROWS = [
    ("AGENT 1 — TRÍCH XUẤT BCTC", None, None, None),
    ("Đọc PDF/ảnh BCTC → JSON", "AI",
     "Multimodal Claude Opus 4.7 + extended thinking. Không có phép tính.",
     "agents/extractor.py · _PROMPT (line 22)"),

    ("AGENT 2 — PHÂN TÍCH NGÀNH", None, None, None),
    ("Industry name, TAM/SAM/SOM, đối thủ", "AI",
     "Phán đoán dựa trên kiến thức ngành. Không có công thức.",
     "agents/industry.py · user_prompt"),

    ("AGENT 3 — TỔNG QUAN DN", None, None, None),
    ("Business model, value chain, vị thế", "AI",
     "Suy luận từ BCTC + ngành.",
     "agents/business_profile.py · user_prompt"),

    ("AGENT 4 — TỶ SỐ TÀI CHÍNH", None, None, None),
    ("current_ratio", "PYTHON",
     "= current_assets_total / current_liabilities_total",
     "agents/analyzer.py · _compute_period_ratios (line 125)"),
    ("quick_ratio", "PYTHON",
     "= (current_assets_total − inventory) / current_liabilities_total",
     "agents/analyzer.py · _compute_period_ratios (line 126)"),
    ("cash_ratio", "PYTHON",
     "= (cash_and_equivalents + short_term_investments) / current_liabilities_total",
     "agents/analyzer.py · _compute_period_ratios (line 127)"),
    ("debt_ratio", "PYTHON",
     "= total_liabilities / total_assets",
     "agents/analyzer.py · _compute_period_ratios (line 130)"),
    ("debt_to_equity", "PYTHON",
     "= total_liabilities / total_equity",
     "agents/analyzer.py · _compute_period_ratios (line 131)"),
    ("equity_multiplier", "PYTHON",
     "= total_assets / total_equity",
     "agents/analyzer.py · _compute_period_ratios (line 132)"),
    ("interest_coverage", "PYTHON",
     "= operating_profit / interest_expense  (EBIT/Interest)",
     "agents/analyzer.py · _compute_period_ratios (line 133)"),
    ("debt_to_ebitda", "PYTHON",
     "= total_liabilities / EBITDA   (EBIT proxy nếu BCTC thiếu D&A — sửa biến `ebitda_proxy`)",
     "agents/analyzer.py · _compute_period_ratios (line 113, 134)"),
    ("gross_margin", "PYTHON",
     "= gross_profit / net_revenue",
     "agents/analyzer.py · _compute_period_ratios (line 137)"),
    ("operating_margin", "PYTHON",
     "= operating_profit / net_revenue",
     "agents/analyzer.py · _compute_period_ratios (line 138)"),
    ("ebitda_margin", "PYTHON",
     "= EBITDA / net_revenue   (EBIT proxy nếu thiếu D&A)",
     "agents/analyzer.py · _compute_period_ratios (line 139)"),
    ("net_margin", "PYTHON",
     "= net_profit_after_tax / net_revenue",
     "agents/analyzer.py · _compute_period_ratios (line 140)"),
    ("roa", "PYTHON",
     "= net_profit_after_tax / total_assets   (cuối kỳ, không trung bình)",
     "agents/analyzer.py · _compute_period_ratios (line 141)"),
    ("roe", "PYTHON",
     "= net_profit_after_tax / total_equity   (cuối kỳ)",
     "agents/analyzer.py · _compute_period_ratios (line 142)"),
    ("asset_turnover", "PYTHON",
     "= net_revenue / total_assets",
     "agents/analyzer.py · _compute_period_ratios (line 145)"),
    ("inventory_turnover", "PYTHON",
     "= cogs / inventory",
     "agents/analyzer.py · _compute_period_ratios (line 146)"),
    ("receivables_turnover", "PYTHON",
     "= net_revenue / short_term_receivables",
     "agents/analyzer.py · _compute_period_ratios (line 147)"),
    ("Tăng trưởng YoY (mọi chỉ tiêu)", "PYTHON",
     "= (current − previous) / |previous|",
     "agents/analyzer.py · _yoy (line 188), _compute_growth (line 200)"),
    ("Ngưỡng đánh giá tốt/cảnh báo/kém", "PYTHON",
     "Bảng ngưỡng cho từng tỷ số (cao tốt / thấp tốt). Sửa để đổi rating.",
     "agents/analyzer.py · _THRESHOLDS (line 43)"),

    ("AGENT 5 — DỰ PHÓNG 5 NĂM", None, None, None),
    ("revenue Y_t", "AI có ràng buộc",
     "= revenue_{t-1} × (1 + revenue_growth_pct[t])",
     "agents/projector.py · prompt line 62"),
    ("gross_profit Y_t", "AI có ràng buộc",
     "= revenue × gross_margin_pct[t]",
     "agents/projector.py · prompt line 64"),
    ("EBIT Y_t", "AI có ràng buộc",
     "= gross_profit − operating_expense  (operating_expense = revenue × OPEX%)",
     "agents/projector.py · prompt line 65"),
    ("EBITDA Y_t", "AI có ràng buộc",
     "= EBIT + Depreciation",
     "agents/projector.py · prompt line 92"),
    ("net_income Y_t", "AI có ràng buộc",
     "= (EBIT − interest_expense) × (1 − tax_rate_pct/100)",
     "agents/projector.py · prompt line 87-88"),
    ("FCFF Y_t   ⭐ quan trọng cho DCF", "AI có ràng buộc",
     "= EBIT × (1 − tax%) + D&A − CAPEX − ΔWC",
     "agents/projector.py · prompt line 110 (ràng buộc bắt buộc)"),
    ("Tăng trưởng giảm dần (S-curve)", "AI có ràng buộc",
     "Y1 cao nhất, Y5 thấp nhất, hội tụ về CAGR ngành",
     "agents/projector.py · prompt line 108"),

    ("AGENT 6 — ĐỊNH GIÁ", None, None, None),
    ("WACC, terminal_growth, multiples", "AI",
     "Claude đề xuất giá trị + rationale. Sửa prompt để force range khác (vd 12-18%).",
     "agents/valuator.py · _claude_assumptions (line 68)"),
    ("DCF: PV(FCFF_t)   ⭐", "PYTHON",
     "= FCFF_t / (1 + WACC)^t      với t = 1..5",
     "agents/valuator.py · _dcf_valuation (line 174-178)"),
    ("DCF: Terminal Value", "PYTHON",
     "= FCFF_5 × (1 + g) / (WACC − g)     [Gordon Growth Model]",
     "agents/valuator.py · _dcf_valuation (line 180-182)"),
    ("DCF: PV(Terminal Value)", "PYTHON",
     "= TV / (1 + WACC)^5",
     "agents/valuator.py · _dcf_valuation (line 183)"),
    ("DCF: Enterprise Value", "PYTHON",
     "= Σ PV(FCFF_t) + PV(TV)",
     "agents/valuator.py · _dcf_valuation (line 188)"),
    ("DCF: Equity Value", "PYTHON",
     "= Enterprise_Value − Total_Debt",
     "agents/valuator.py · _dcf_valuation (line 189)"),
    ("Total_Debt định nghĩa", "PYTHON",
     "= total_liabilities (toàn bộ nợ phải trả). Đổi sang chỉ short_term_debt + long_term_debt nếu muốn 'nợ có lãi vay' thuần.",
     "agents/valuator.py · line 28"),
    ("Multiples — EV/EBITDA", "PYTHON",
     "Equity = (EBITDA_Y1 × ev_ebitda_multiple) − Total_Debt",
     "agents/valuator.py · _multiples_valuation (line 208-216)"),
    ("Multiples — P/E", "PYTHON",
     "Equity = Net_Income_current × pe_multiple",
     "agents/valuator.py · _multiples_valuation (line 219-224)"),
    ("Multiples — P/B", "PYTHON",
     "Equity = Total_Equity_book × pb_multiple",
     "agents/valuator.py · _multiples_valuation (line 227-232)"),
    ("Fair Value low/mid/high", "PYTHON",
     "low = min(equity_values), high = max, mid = mean (TRUNG BÌNH CỘNG, không trọng số)",
     "agents/valuator.py · _build_summary (line 286-289)"),
    ("Chiết khấu thiểu số", "PYTHON",
     "fair_value_after_md = fair_value_mid × (1 − minority_discount_pct/100)",
     "agents/valuator.py · _build_summary (line 291-293)"),
    ("Sensitivity matrix (5×5)", "PYTHON",
     "Re-run DCF với WACC ± 1%, ±2% và g ± 1%, ±2%. Step size sửa được.",
     "agents/valuator.py · _sensitivity (line 240-261)"),

    ("AGENT 7 — INVESTMENT THESIS", None, None, None),
    ("Headline, drivers, catalysts, risks", "AI",
     "Claude tổng hợp output A1-A6 thành memo. Không có phép tính.",
     "agents/thesis_writer.py · user_prompt"),

    ("AGENT 8 — RENDER", None, None, None),
    ("PDF (matplotlib) + Excel (openpyxl)", "PYTHON (vẽ)",
     "Không tạo số mới — chỉ vẽ output. Style tokens tách riêng.",
     "agents/renderer.py · agents/excel_writer.py · style: agents/report_style.py"),
]


def _sheet_methodology(wb):
    """First sheet: bảng tra cứu mọi phép tính trong báo cáo."""
    ws = wb.create_sheet("Phương pháp tính")
    ws.cell(1, 1, "BẢNG TRA CỨU PHƯƠNG PHÁP TÍNH").font = Font(
        name="Calibri", size=14, bold=True, color=_hex(COLORS["primary"]))
    ws.cell(2, 1, "Mỗi dòng = 1 phép tính. Cột 'File nguồn' chỉ ra chỗ sửa nếu cần.").font = MUTED_FONT
    ws.cell(3, 1, "PYTHON = công thức cố định, kế toán có thể audit.   "
                  "AI = phán đoán bởi Claude — đọc rationale trong trace.json.").font = MUTED_FONT

    headers = ["Phép tính / Chỉ tiêu", "Loại", "Công thức / Diễn giải", "File nguồn (Sửa tại đây)"]
    for col, h in enumerate(headers, 1):
        c = ws.cell(5, col, h)
        c.font = HEADER_FONT
        c.fill = HEADER_FILL
        c.alignment = Alignment(horizontal="left", vertical="center")

    row = 6
    formula_font = Font(name="Consolas", size=9, color=_hex(COLORS["primary"]))
    source_font = Font(name="Consolas", size=9, color=_hex(COLORS["accent"]))
    for entry in _METHODOLOGY_ROWS:
        name, kind, formula, source = entry
        if kind is None:
            # Section header.
            c = ws.cell(row, 1, name)
            c.font = SECTION_FONT
            c.fill = SECTION_FILL
            ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=4)
            for k in range(2, 5):
                ws.cell(row, k).fill = SECTION_FILL
            row += 1
            continue
        ws.cell(row, 1, name).font = LABEL_FONT
        kind_cell = ws.cell(row, 2, kind)
        kind_cell.font = LABEL_FONT
        if kind == "PYTHON":
            kind_cell.fill = GOOD_FILL
        elif kind.startswith("AI"):
            kind_cell.fill = PatternFill("solid", fgColor=_hex(COLORS.get("primary_band") or "DBEAFE"))
        else:
            kind_cell.fill = TOTAL_FILL
        f_cell = ws.cell(row, 3, formula or "")
        f_cell.font = formula_font
        f_cell.alignment = Alignment(wrap_text=True, vertical="top")
        s_cell = ws.cell(row, 4, source or "")
        s_cell.font = source_font
        s_cell.alignment = Alignment(wrap_text=True, vertical="top")
        ws.row_dimensions[row].height = 28
        row += 1

    ws.column_dimensions["A"].width = 38
    ws.column_dimensions["B"].width = 16
    ws.column_dimensions["C"].width = 70
    ws.column_dimensions["D"].width = 56
    ws.freeze_panes = "A6"
