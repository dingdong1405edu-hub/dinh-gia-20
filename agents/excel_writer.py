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
    ws = wb.create_sheet("Tỷ số")
    ratios = ratios_payload.get("ratios") or {}
    cur = ratios.get("current") or {}
    prev = ratios.get("previous") or ratios.get("prior") or {}
    growth = ratios_payload.get("growth") or {}

    categories = [
        ("Thanh khoản", [
            ("current_ratio", "Hệ số TT hiện hành", "ratio"),
            ("quick_ratio", "Hệ số TT nhanh", "ratio"),
            ("cash_ratio", "Hệ số TT tiền mặt", "ratio"),
        ]),
        ("Đòn bẩy / Cơ cấu vốn", [
            ("debt_ratio", "Hệ số nợ / TS", "pct_frac"),
            ("debt_to_equity", "Nợ / VCSH", "ratio"),
            ("equity_multiplier", "Hệ số nhân VCSH", "ratio"),
            ("interest_coverage", "Khả năng trả lãi vay", "ratio"),
            ("debt_to_ebitda", "Nợ / EBITDA", "ratio"),
        ]),
        ("Khả năng sinh lời", [
            ("gross_margin", "Biên LN gộp", "pct_frac"),
            ("operating_margin", "Biên LN HĐKD", "pct_frac"),
            ("ebitda_margin", "Biên EBITDA", "pct_frac"),
            ("net_margin", "Biên LN ròng", "pct_frac"),
            ("roa", "ROA", "pct_frac"),
            ("roe", "ROE", "pct_frac"),
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
            # pct_frac: ratio in fraction form (0.08 = 8%); ratio: number as-is.
            fmt = "0.00%" if kind == "pct_frac" else "0.00"
            for col, v in enumerate([cv, pv], 2):
                if v is not None:
                    try:
                        cc = ws.cell(row, col, float(v))
                        cc.number_format = fmt
                        cc.font = BODY_FONT
                    except (TypeError, ValueError):
                        pass
            if isinstance(cv, (int, float)) and isinstance(pv, (int, float)) and pv:
                ws.cell(row, 4, (cv - pv) / abs(pv)).number_format = "+0.0%;-0.0%;0.0%"
            row += 1
        row += 1

    # Growth block (analyzer.py output: revenue_yoy, gross_profit_yoy, ebit_yoy,
    # net_income_yoy, total_assets_yoy, total_equity_yoy — fractions, not %).
    if growth:
        c = ws.cell(row, 1, "Tăng trưởng YoY")
        c.font = SECTION_FONT; c.fill = SECTION_FILL
        for col in range(2, 5):
            ws.cell(row, col).fill = SECTION_FILL
        row += 1
        for k, label in [
            ("revenue_yoy", "Tăng trưởng doanh thu"),
            ("gross_profit_yoy", "Tăng trưởng LN gộp"),
            ("ebit_yoy", "Tăng trưởng EBIT"),
            ("net_income_yoy", "Tăng trưởng LNST"),
            ("total_assets_yoy", "Tăng trưởng tổng tài sản"),
            ("total_equity_yoy", "Tăng trưởng VCSH"),
        ]:
            v = growth.get(k)
            ws.cell(row, 1, label).font = BODY_FONT
            if isinstance(v, (int, float)):
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

    # DCF detail.
    row += 2
    _write_section_title(ws, row, 1, "DCF (FCFF) — chi tiết", span=2)
    row += 2
    dcf_rows = [
        ("WACC (%)", dcf.get("wacc_pct"), "0.00\"%\""),
        ("Terminal growth (%)", dcf.get("terminal_growth_pct"), "0.00\"%\""),
        ("PV của FCFF (5Y)", dcf.get("pv_explicit_fcff"), "#,##0"),
        ("Terminal value", dcf.get("terminal_value"), "#,##0"),
        ("PV(Terminal value)", dcf.get("pv_terminal"), "#,##0"),
        ("Enterprise value", dcf.get("enterprise_value"), "#,##0"),
        ("Trừ nợ", dcf.get("debt_subtracted"), "#,##0"),
        ("Equity value (DCF)", dcf.get("equity_value"), "#,##0"),
    ]
    for label, val, fmt in dcf_rows:
        ws.cell(row, 1, label).font = LABEL_FONT
        if isinstance(val, (int, float)):
            cc = ws.cell(row, 2, float(val))
            cc.number_format = fmt
            cc.font = BODY_FONT
        row += 1
    if dcf.get("note"):
        ws.cell(row, 1, "Ghi chú").font = LABEL_FONT
        c = ws.cell(row, 2, dcf["note"])
        c.alignment = Alignment(wrap_text=True, vertical="top")
        c.font = MUTED_FONT
        row += 1

    # PV breakdown table.
    pv_breakdown = dcf.get("pv_breakdown") or []
    if pv_breakdown:
        row += 1
        _write_section_title(ws, row, 1, "DCF — PV breakdown từng năm", span=4)
        row += 2
        for col, h in enumerate(["Năm", "FCFF", "Discount factor", "PV"], 1):
            c = ws.cell(row, col, h); c.font = LABEL_FONT
        row += 1
        for it in pv_breakdown:
            ws.cell(row, 1, it.get("year")).font = BODY_FONT
            for col, k, fmt in [(2, "fcff", "#,##0"), (3, "discount_factor", "0.0000"), (4, "pv", "#,##0")]:
                v = it.get(k)
                if isinstance(v, (int, float)):
                    cc = ws.cell(row, col, float(v))
                    cc.number_format = fmt
                    cc.font = BODY_FONT
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
    ws.column_dimensions["A"].width = 40
    ws.column_dimensions["B"].width = 22
    ws.column_dimensions["C"].width = 18
    ws.column_dimensions["D"].width = 22


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
