"""Analyzer: deterministic Python computation of ratios + growth metrics."""
import time


# --------------------- Public ---------------------

def analyze(financials: dict) -> dict:
    t0 = time.time()
    ratios = _compute_all_ratios(financials)
    growth = _compute_growth(financials)
    return {
        "elapsed_sec": round(time.time() - t0, 2),
        "ratios": ratios,
        "growth": growth,
    }


# --------------------- Helpers ---------------------

def _safe_div(a, b):
    if a is None or b is None:
        return None
    try:
        b = float(b)
        if b == 0:
            return None
        return float(a) / b
    except (TypeError, ValueError):
        return None


def _get(d, *path):
    cur = d
    for k in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    return cur


# --------------------- Ratios ---------------------

_THRESHOLDS = {
    "current_ratio": ("higher", 1.0, 2.0),
    "quick_ratio": ("higher", 0.5, 1.0),
    "cash_ratio": ("higher", 0.1, 0.3),
    "debt_ratio": ("lower", 0.7, 0.5),
    "debt_to_equity": ("lower", 2.0, 1.0),
    "equity_multiplier": ("lower", 3.0, 2.0),
    "gross_margin": ("higher", 0.10, 0.25),
    "operating_margin": ("higher", 0.05, 0.15),
    "net_margin": ("higher", 0.03, 0.10),
    "ebitda_margin": ("higher", 0.08, 0.18),
    "roa": ("higher", 0.03, 0.08),
    "roe": ("higher", 0.08, 0.15),
    "asset_turnover": ("higher", 0.5, 1.0),
    "inventory_turnover": ("higher", 4.0, 8.0),
    "receivables_turnover": ("higher", 4.0, 10.0),
    "interest_coverage": ("higher", 2.0, 5.0),
    "debt_to_ebitda": ("lower", 4.0, 2.5),
}


def _rate(name: str, value):
    if value is None:
        return "n/a"
    spec = _THRESHOLDS.get(name)
    if not spec:
        return "n/a"
    direction, t_warn, t_good = spec
    if direction == "higher":
        if value >= t_good:
            return "good"
        if value >= t_warn:
            return "warning"
        return "poor"
    if value <= t_good:
        return "good"
    if value <= t_warn:
        return "warning"
    return "poor"


def _compute_period_ratios(financials: dict, which: str) -> dict:
    bs = _get(financials, "balance_sheet", which) or {}
    is_ = _get(financials, "income_statement", which) or {}

    assets = bs.get("assets") or {}
    liab = bs.get("liabilities") or {}
    equity = bs.get("equity") or {}

    cash = assets.get("cash_and_equivalents")
    short_inv = assets.get("short_term_investments")
    receivables = assets.get("short_term_receivables")
    inventory = assets.get("inventory")
    current_assets = assets.get("current_assets_total")
    total_assets = assets.get("total_assets")
    current_liab = liab.get("current_liabilities_total")
    total_liab = liab.get("total_liabilities")
    total_equity = equity.get("total_equity")

    revenue = is_.get("net_revenue") or is_.get("revenue")
    cogs = is_.get("cogs")
    gross_profit = is_.get("gross_profit")
    operating_profit = is_.get("operating_profit")
    interest_expense = is_.get("interest_expense")
    profit_before_tax = is_.get("profit_before_tax")
    net_income = is_.get("net_profit_after_tax")

    ebit = operating_profit
    if ebit is None and profit_before_tax is not None and interest_expense is not None:
        ebit = profit_before_tax + interest_expense
    ebitda_proxy = ebit  # If depreciation unavailable, ebit serves as proxy

    cash_like = None
    if cash is not None or short_inv is not None:
        cash_like = (cash or 0) + (short_inv or 0)

    quick_assets = None
    if current_assets is not None and inventory is not None:
        quick_assets = current_assets - inventory

    raw = {
        "liquidity": {
            "current_ratio": _safe_div(current_assets, current_liab),
            "quick_ratio": _safe_div(quick_assets, current_liab),
            "cash_ratio": _safe_div(cash_like, current_liab),
        },
        "leverage": {
            "debt_ratio": _safe_div(total_liab, total_assets),
            "debt_to_equity": _safe_div(total_liab, total_equity),
            "equity_multiplier": _safe_div(total_assets, total_equity),
            "interest_coverage": _safe_div(ebit, interest_expense),
            "debt_to_ebitda": _safe_div(total_liab, ebitda_proxy),
        },
        "profitability": {
            "gross_margin": _safe_div(gross_profit, revenue),
            "operating_margin": _safe_div(operating_profit, revenue),
            "ebitda_margin": _safe_div(ebitda_proxy, revenue),
            "net_margin": _safe_div(net_income, revenue),
            "roa": _safe_div(net_income, total_assets),
            "roe": _safe_div(net_income, total_equity),
        },
        "efficiency": {
            "asset_turnover": _safe_div(revenue, total_assets),
            "inventory_turnover": _safe_div(cogs, inventory),
            "receivables_turnover": _safe_div(revenue, receivables),
        },
    }

    rated: dict = {}
    for cat, items in raw.items():
        rated[cat] = {}
        for name, value in items.items():
            rated[cat][name] = {
                "value": value,
                "rating": _rate(name, value),
            }
    return rated


def _compute_all_ratios(financials: dict) -> dict:
    cur = _compute_period_ratios(financials, "current")

    prev_bs = _get(financials, "balance_sheet", "previous")
    prev = None
    if isinstance(prev_bs, dict):
        prev = _compute_period_ratios(financials, "previous")

    changes = None
    if prev is not None:
        changes = {}
        for cat, items in cur.items():
            changes[cat] = {}
            for name, payload in items.items():
                cv = payload.get("value")
                pv = (prev.get(cat, {}).get(name, {}) or {}).get("value")
                if cv is None or pv is None:
                    changes[cat][name] = None
                else:
                    changes[cat][name] = round(cv - pv, 4)

    return {"current": cur, "previous": prev, "changes": changes}


# --------------------- Growth (CAGR / YoY) ---------------------

def _yoy(current, previous):
    if current is None or previous is None:
        return None
    try:
        c = float(current); p = float(previous)
    except (TypeError, ValueError):
        return None
    if p == 0:
        return None
    return (c - p) / abs(p)


def _compute_growth(financials: dict) -> dict:
    is_cur = _get(financials, "income_statement", "current") or {}
    is_prev = _get(financials, "income_statement", "previous") or {}
    bs_cur = _get(financials, "balance_sheet", "current") or {}
    bs_prev = _get(financials, "balance_sheet", "previous") or {}

    growth = {
        "revenue_yoy": _yoy(is_cur.get("net_revenue") or is_cur.get("revenue"),
                            is_prev.get("net_revenue") or is_prev.get("revenue")),
        "gross_profit_yoy": _yoy(is_cur.get("gross_profit"), is_prev.get("gross_profit")),
        "ebit_yoy": _yoy(is_cur.get("operating_profit"), is_prev.get("operating_profit")),
        "net_income_yoy": _yoy(is_cur.get("net_profit_after_tax"), is_prev.get("net_profit_after_tax")),
        "total_assets_yoy": _yoy(_get(bs_cur, "assets", "total_assets"),
                                  _get(bs_prev, "assets", "total_assets")),
        "total_equity_yoy": _yoy(_get(bs_cur, "equity", "total_equity"),
                                  _get(bs_prev, "equity", "total_equity")),
    }
    return growth
