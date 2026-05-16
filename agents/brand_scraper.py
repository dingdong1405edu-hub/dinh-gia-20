"""Agent Brand: Scrape company website → extract brand color palette → style override for PDF.

Flow:
  1. If user provides URL → use it directly.
  2. If no URL → ask Claude to suggest the most likely company website.
  3. Fetch HTML, parse inline <style> blocks + linked CSS files (first 2).
  4. Extract hex colors via CSS custom-property heuristics + meta theme-color.
  5. Return style_override dict (keys matching report_style.COLORS) for renderer.

Failures are non-fatal: brand_colors=None → renderer uses default IB-navy style.
"""
import re
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

from anthropic import Anthropic

_MODEL = "claude-opus-4-7"
_CLIENT: Anthropic | None = None


def _client() -> Anthropic:
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = Anthropic()
    return _CLIENT


# ── HTTP helpers ─────────────────────────────────────────────────────────────

def _fetch(url: str, timeout: int = 8) -> str | None:
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 Chrome/120 Safari/537.36"
                ),
                "Accept": "text/html,text/css,*/*;q=0.8",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            charset = "utf-8"
            ct = resp.headers.get("Content-Type", "")
            if "charset=" in ct:
                charset = ct.split("charset=")[-1].strip().split(";")[0].strip()
            return resp.read().decode(charset, errors="ignore")
    except Exception:
        return None


def _fetch_with_fallback(url: str) -> str | None:
    """Try https first, then http."""
    if url.startswith("http://"):
        return _fetch(url) or _fetch(url.replace("http://", "https://"))
    https_url = url if url.startswith("https://") else "https://" + url
    result = _fetch(https_url)
    if result is None:
        result = _fetch(https_url.replace("https://", "http://"))
    return result


# ── Color extraction ─────────────────────────────────────────────────────────

_HEX6_RE = re.compile(r'#([0-9A-Fa-f]{6})\b')
_HEX3_RE = re.compile(r'#([0-9A-Fa-f]{3})\b')
_CSSVAR_RE = re.compile(r'--([\w-]+)\s*:\s*(#[0-9A-Fa-f]{3,6})\b')
_THEME_COLOR_RE = re.compile(
    r'<meta[^>]+name=["\']theme-color["\'][^>]+content=["\']([^"\']+)["\']'
    r'|<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']theme-color["\']',
    re.I,
)
_LINK_CSS_RE = re.compile(
    r'<link[^>]+rel=["\']stylesheet["\'][^>]+href=["\']([^"\']+)["\']'
    r'|<link[^>]+href=["\']([^"\']+)["\'][^>]+rel=["\']stylesheet["\']',
    re.I,
)

# CSS var name fragments that indicate brand/primary color
_PRIMARY_HINTS = [
    "primary", "brand", "main-color", "color-main", "header", "navbar",
    "nav-bg", "main-bg", "primary-color", "color-primary", "brand-color",
    "color-brand", "theme", "key-color",
]
_ACCENT_HINTS = [
    "accent", "secondary", "highlight", "cta", "button", "link-color",
    "color-accent", "color-secondary", "secondary-color",
]

# Colors to ignore (too dark/light to be meaningful brand colors)
_IGNORE = {
    "#ffffff", "#000000", "#fff", "#000",
    "#ffffffff", "#00000000",
    "#f8f8f8", "#f9f9f9", "#fafafa", "#f5f5f5",
    "#111111", "#222222", "#333333",
    "#e0e0e0", "#dddddd", "#cccccc",
    "#eeeeee", "#e5e7eb",
}


def _normalize_hex(raw: str) -> str:
    """Normalize 3-char or 6-char hex to lowercase 6-char with #."""
    raw = raw.lstrip("#").lower()
    if len(raw) == 3:
        raw = raw[0]*2 + raw[1]*2 + raw[2]*2
    return "#" + raw


def _is_useful_color(hex6: str) -> bool:
    if hex6 in _IGNORE:
        return False
    r = int(hex6[1:3], 16)
    g = int(hex6[3:5], 16)
    b = int(hex6[5:7], 16)
    brightness = (r * 299 + g * 587 + b * 114) / 1000
    # Skip near-white (>230) and near-black (<20)
    return 20 < brightness < 230


def _all_hex_colors(text: str) -> list[str]:
    colors = []
    for m in _HEX6_RE.finditer(text):
        colors.append(_normalize_hex(m.group(1)))
    for m in _HEX3_RE.finditer(text):
        colors.append(_normalize_hex(m.group(1)))
    return colors


def _css_vars(text: str) -> dict[str, str]:
    result = {}
    for m in _CSSVAR_RE.finditer(text):
        result[m.group(1).lower()] = _normalize_hex(m.group(2))
    return result


def _theme_color(html: str) -> str | None:
    m = _THEME_COLOR_RE.search(html)
    if m:
        val = (m.group(1) or m.group(2) or "").strip()
        if re.match(r'^#[0-9A-Fa-f]{3,6}$', val):
            return _normalize_hex(val.lstrip("#"))
    return None


def _linked_css_urls(html: str, base_url: str) -> list[str]:
    parsed = urlparse(base_url)
    base_origin = f"{parsed.scheme}://{parsed.netloc}"
    urls = []
    for m in _LINK_CSS_RE.finditer(html):
        href = (m.group(1) or m.group(2) or "").strip()
        if not href or href.startswith("data:"):
            continue
        if href.startswith("http"):
            urls.append(href)
        elif href.startswith("//"):
            urls.append(parsed.scheme + ":" + href)
        elif href.startswith("/"):
            urls.append(base_origin + href)
        else:
            urls.append(base_origin + "/" + href)
    return urls


def _pick_color_for_hints(css_vars_map: dict[str, str], hints: list[str]) -> str | None:
    for hint in hints:
        for var_name, color in css_vars_map.items():
            if hint in var_name and _is_useful_color(color):
                return color
    return None


def _most_common_useful_colors(text: str, top_n: int = 5) -> list[str]:
    from collections import Counter
    counts: Counter = Counter()
    for c in _all_hex_colors(text):
        if _is_useful_color(c):
            counts[c] += 1
    return [c for c, _ in counts.most_common(top_n)]


# ── Color derivation ─────────────────────────────────────────────────────────

def _darken(hex_color: str, factor: float) -> str:
    """Make color darker by factor (0=black, 1=unchanged)."""
    r = int(hex_color[1:3], 16)
    g = int(hex_color[3:5], 16)
    b = int(hex_color[5:7], 16)
    return "#{:02x}{:02x}{:02x}".format(
        max(0, int(r * factor)),
        max(0, int(g * factor)),
        max(0, int(b * factor)),
    )


def _lighten(hex_color: str, amount: float) -> str:
    """Mix color toward white by amount (0=unchanged, 1=white)."""
    r = int(hex_color[1:3], 16)
    g = int(hex_color[3:5], 16)
    b = int(hex_color[5:7], 16)
    return "#{:02x}{:02x}{:02x}".format(
        min(255, int(r + (255 - r) * amount)),
        min(255, int(g + (255 - g) * amount)),
        min(255, int(b + (255 - b) * amount)),
    )


def _build_style_override(primary: str, accent: str | None) -> dict:
    """Derive a full COLORS-compatible override dict from a primary (and optional accent) hex."""
    acc = accent if (accent and _is_useful_color(accent)) else _darken(primary, 0.65)
    return {
        "primary":       _darken(primary, 0.85),
        "primary_mid":   primary,
        "primary_dark":  _darken(primary, 0.65),
        "primary_light": _lighten(primary, 0.92),
        "primary_band":  _lighten(primary, 0.82),
        "accent":        acc,
        "accent_light":  _lighten(acc, 0.88),
    }


# ── URL discovery via Claude ─────────────────────────────────────────────────

def _find_url_via_claude(company_info: dict) -> str | None:
    name = (company_info.get("name") or "").strip()
    tax  = (company_info.get("tax_code") or "").strip()
    ind  = (company_info.get("industry") or "").strip()
    if not name:
        return None
    prompt = (
        f"Tìm website chính thức của công ty Việt Nam này.\n"
        f"Tên công ty: {name}\n"
        f"Mã số thuế: {tax or '(không có)'}\n"
        f"Ngành: {ind or '(không có)'}\n\n"
        "Chỉ trả lời đúng 1 dòng: URL đầy đủ bắt đầu bằng https:// hoặc http://.\n"
        "Nếu không biết chắc, trả lời: NONE"
    )
    try:
        resp = _client().messages.create(
            model=_MODEL,
            max_tokens=100,
            messages=[{"role": "user", "content": prompt}],
        )
        text = (resp.content[0].text or "").strip().split()[0]
        if text.upper() == "NONE":
            return None
        if re.match(r'^https?://[\w.-]', text):
            return text
    except Exception:
        pass
    return None


# ── Public API ───────────────────────────────────────────────────────────────

def scrape_brand(company_url: str | None, company_info: dict) -> dict:
    """
    Fetch company website, extract brand colors, build style override.

    Args:
        company_url:  URL provided by user (may be None).
        company_info: dict from extractor — expects keys: name, tax_code, industry.

    Returns dict with:
        url_used        — final URL fetched (or None)
        url_source      — 'user_provided' | 'claude_detected' | 'none'
        brand_colors    — {'primary': '#...', 'accent': '#...'} or None
        style_override  — COLORS-compatible dict or None
        notes           — human-readable summary
        elapsed_sec
    """
    t0 = time.time()

    url = (company_url or "").strip() or None
    url_source = "user_provided" if url else "claude_detected"

    if not url:
        url = _find_url_via_claude(company_info)

    if not url:
        return {
            "elapsed_sec": round(time.time() - t0, 2),
            "url_used": None,
            "url_source": "none",
            "brand_colors": None,
            "style_override": None,
            "notes": "Không có website — báo cáo dùng style mặc định (IB navy)",
        }

    # Normalize scheme
    if not url.startswith("http"):
        url = "https://" + url

    html = _fetch_with_fallback(url)
    if not html:
        return {
            "elapsed_sec": round(time.time() - t0, 2),
            "url_used": url,
            "url_source": url_source,
            "brand_colors": None,
            "style_override": None,
            "notes": f"Không thể kết nối {url} — dùng style mặc định",
        }

    # ── Collect CSS text ──────────────────────────────────────────────────────
    inline_css_blocks = re.findall(r'<style[^>]*>(.*?)</style>', html, re.DOTALL | re.I)
    css_text = "\n".join(inline_css_blocks)

    # Fetch up to 2 external CSS files
    for css_url in _linked_css_urls(html, url)[:2]:
        extra = _fetch(css_url, timeout=5)
        if extra:
            css_text += "\n" + extra

    combined = html + "\n" + css_text

    # ── Extract colors ────────────────────────────────────────────────────────
    vars_map   = _css_vars(combined)
    theme_clr  = _theme_color(html)
    top_colors = _most_common_useful_colors(css_text or combined, top_n=6)

    primary = (
        _pick_color_for_hints(vars_map, _PRIMARY_HINTS)
        or theme_clr
        or (top_colors[0] if top_colors else None)
    )
    accent = (
        _pick_color_for_hints(vars_map, _ACCENT_HINTS)
        or (top_colors[1] if len(top_colors) > 1 and top_colors[1] != primary else None)
    )

    if not primary:
        return {
            "elapsed_sec": round(time.time() - t0, 2),
            "url_used": url,
            "url_source": url_source,
            "brand_colors": None,
            "style_override": None,
            "notes": f"Kết nối được {url} nhưng không tìm thấy màu brand trong CSS — dùng style mặc định",
        }

    brand_colors   = {"primary": primary, "accent": accent}
    style_override = _build_style_override(primary, accent)

    return {
        "elapsed_sec": round(time.time() - t0, 2),
        "url_used": url,
        "url_source": url_source,
        "brand_colors": brand_colors,
        "style_override": style_override,
        "notes": (
            f"Đã trích xuất màu brand từ {url} — "
            f"primary={primary}"
            + (f", accent={accent}" if accent else "")
        ),
    }
