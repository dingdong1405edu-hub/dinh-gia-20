"""
Design tokens cho báo cáo PDF.

Sửa file này để đổi màu / font / khoảng cách / style của báo cáo PDF.
Mọi tham số đều được renderer.py đọc qua biến STYLE.

Hai loại token:
  - COLORS  : bảng màu (hex). Đổi được toàn bộ "tông" báo cáo.
  - FONTS   : tên font. Phải có file TTF tương ứng trong fonts/ nếu đổi.
  - SIZES   : font size cho từng cấp tiêu đề.
  - LAYOUT  : margin trang, line-height, kích thước table.

Để đổi font: bỏ TTF mới vào fonts/, đổi PRIMARY_FONT bên dưới.
"""

# ===================== COLORS =====================
COLORS = {
    # Tông chính — tiêu đề, accent header, fair value box.
    "primary": "#1e3a8a",          # navy
    "primary_dark": "#1e40af",
    "primary_light": "#eff6ff",     # bg callout box
    "primary_band": "#dbeafe",

    # Accent — đường gạch chân nhỏ, nhấn nhẹ.
    "accent": "#dc2626",            # red
    "accent_light": "#fee2e2",

    # Trạng thái (dùng cho rủi ro, catalyst, rating).
    "good": "#10b981",              # green
    "good_light": "#d1fae5",
    "warning": "#f59e0b",           # amber
    "warning_light": "#fef3c7",
    "poor": "#ef4444",              # red
    "poor_light": "#fee2e2",
    "info": "#3b82f6",              # blue
    "info_light": "#dbeafe",

    # Text scale.
    "text_strong": "#1f2937",       # body strong
    "text": "#374151",              # body
    "text_muted": "#6b7280",        # caption / hint
    "text_dim": "#9ca3af",          # placeholder

    # Surface (nền, viền, chia mục).
    "border": "#e5e7eb",
    "border_strong": "#d1d5db",
    "surface_alt": "#f9fafb",       # row alt bg
    "surface_card": "#ffffff",

    # Bảng tỷ số / grade.
    "grade_A": "#10b981",
    "grade_B": "#22c55e",
    "grade_C": "#f59e0b",
    "grade_D": "#f97316",
    "grade_F": "#ef4444",
}


# ===================== FONTS =====================
PRIMARY_FONT = "Be Vietnam Pro"
FONT_FALLBACKS = ["DejaVu Sans", "Arial"]

# Header / body weight (matplotlib accepts "normal","bold","light").
WEIGHT_HEADER = "bold"
WEIGHT_BODY = "normal"
WEIGHT_LABEL = "bold"


# ===================== SIZES =====================
SIZES = {
    # Cover.
    "cover_title": 22,
    "cover_subtitle": 13,
    "cover_company": 20,
    "cover_period": 13,
    "cover_value_label": 12,
    "cover_value_amount": 24,

    # Page (non-cover).
    "page_title": 15,
    "section_title": 12,
    "subsection_title": 11,
    "label": 9,

    # Body.
    "body": 10,
    "body_small": 9,
    "caption": 8.5,
    "footnote": 8,
}


# ===================== LAYOUT =====================
LAYOUT = {
    # A4 figure size in inches.
    "page_size": (8.27, 11.69),

    # Page margins inside the matplotlib axes (0–1 normalized).
    "margin_left": 0.07,
    "margin_right": 0.07,
    "margin_top": 0.05,
    "margin_bottom": 0.05,

    # Table.
    "row_height_default": 0.024,
    "row_height_compact": 0.022,
    "table_rule_width": 0.7,

    # Header & footer.
    "header_rule_width": 1.2,
    "header_accent_block": 0.012,    # square width on title left
    "footer_rule_width": 0.6,
}


# ===================== RATING TEXT (vi) =====================
RATING_LABEL_VI = {"good": "Tốt", "warning": "TB", "poor": "Kém", "n/a": "—"}
GRADE_LABEL_VI = {"A": "Xuất sắc", "B": "Tốt", "C": "Trung bình", "D": "Yếu", "F": "Kém"}


# ===================== Helpers =====================
def grade_color(grade: str) -> str:
    return COLORS.get(f"grade_{grade}", COLORS["text_muted"])


def rating_color(rating: str) -> str:
    return {
        "good": COLORS["good"],
        "warning": COLORS["warning"],
        "poor": COLORS["poor"],
        "n/a": COLORS["text_dim"],
    }.get(rating, COLORS["text_muted"])
