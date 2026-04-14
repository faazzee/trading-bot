"""
fundamental_analyzer.py — Fundamental data fetching and scoring.

Pulls financial metrics from yfinance's .info dict (free, no API key needed).
Scores each metric 0–10 and produces a weighted composite score 0–100.

Scoring weights
───────────────
EPS Growth       20%
Revenue Growth   15%
Forward P/E      15%
PEG Ratio        15%
Profit Margin    10%
Return on Equity 10%
Debt-to-Equity   10%
Free Cash Flow    5%
"""

import logging
import yfinance as yf
from tracker import get_current_price

logger = logging.getLogger(__name__)


def get_fundamentals(symbol: str) -> dict:
    """
    Fetches fundamental data for a symbol from yfinance's .info dict.

    Returns a dict of fundamental metrics (values may be None if unavailable).
    On failure, returns {"symbol": symbol.upper(), "error": str(e)}.
    """
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info

        current_price = get_current_price(symbol)

        return {
            "symbol": symbol.upper(),
            "name": info.get("shortName"),
            "sector": info.get("sector"),
            "current_price": current_price,
            "forward_pe": info.get("forwardPE"),
            "peg_ratio": info.get("pegRatio"),
            "eps_growth": info.get("earningsGrowth"),
            "revenue_growth": info.get("revenueGrowth"),
            "profit_margin": info.get("profitMargins"),
            "debt_to_equity": info.get("debtToEquity"),
            "free_cashflow": info.get("freeCashflow"),
            "return_on_equity": info.get("returnOnEquity"),
            "target_mean_price": info.get("targetMeanPrice"),
            "recommendation_mean": info.get("recommendationMean"),
            "insider_ownership": info.get("heldPercentInsiders"),
            "institutional_ownership": info.get("heldPercentInstitutions"),
        }
    except Exception as e:
        logger.error("get_fundamentals(%s) failed: %s", symbol, e)
        return {"symbol": symbol.upper(), "error": str(e)}


def _score_metric(value, low_bad, low_ok, high_ok, high_great, reverse=False) -> float:
    """
    Scores a single metric on a 0–10 scale using piecewise linear interpolation.

    If value is None, returns 5.0 (neutral — don't penalize missing data).

    reverse=False (higher is better):
      value <= low_bad  → 0
      low_bad < value <= low_ok   → linear 0–5
      low_ok  < value <= high_ok  → linear 5–8
      high_ok < value <= high_great → linear 8–10
      value > high_great → 10

    reverse=True (lower is better): the scale is flipped.
    """
    if value is None:
        return 5.0

    if not reverse:
        if value <= low_bad:
            return 0.0
        elif value <= low_ok:
            denom = low_ok - low_bad
            return 5.0 * (value - low_bad) / denom if denom != 0 else 0.0
        elif value <= high_ok:
            denom = high_ok - low_ok
            return 5.0 + 3.0 * (value - low_ok) / denom if denom != 0 else 5.0
        elif value <= high_great:
            denom = high_great - high_ok
            return 8.0 + 2.0 * (value - high_ok) / denom if denom != 0 else 8.0
        else:
            return 10.0
    else:
        if value <= low_bad:
            return 10.0
        elif value <= low_ok:
            denom = low_ok - low_bad
            return 10.0 - 2.0 * (value - low_bad) / denom if denom != 0 else 10.0
        elif value <= high_ok:
            denom = high_ok - low_ok
            return 8.0 - 3.0 * (value - low_ok) / denom if denom != 0 else 8.0
        elif value <= high_great:
            denom = high_great - high_ok
            return 5.0 - 5.0 * (value - high_ok) / denom if denom != 0 else 5.0
        else:
            return 0.0


def score_fundamentals(fundamentals: dict) -> dict:
    """
    Scores the fundamental data dict returned by get_fundamentals().

    Returns a dict with total_score (0–100), label, sub_scores (each 0–10),
    analyst_upside_pct, and recommendation_mean.
    On error, returns a neutral fallback dict.
    """
    _fallback = {
        "total_score": 50.0,
        "label": "Fair",
        "sub_scores": {},
        "analyst_upside_pct": None,
        "recommendation_mean": None,
    }

    try:
        # --- Sub-scores ---
        eps_v = fundamentals.get("eps_growth")
        rev_v = fundamentals.get("revenue_growth")
        pe_v = fundamentals.get("forward_pe")
        peg_v = fundamentals.get("peg_ratio")
        pm_v = fundamentals.get("profit_margin")
        roe_v = fundamentals.get("return_on_equity")
        dte_v = fundamentals.get("debt_to_equity")
        fcf_v = fundamentals.get("free_cashflow")

        sub_scores = {
            "eps_growth": _score_metric(
                eps_v * 100 if eps_v is not None else None,
                -10, 0, 15, 30
            ),
            "revenue_growth": _score_metric(
                rev_v * 100 if rev_v is not None else None,
                -5, 0, 10, 25
            ),
            "forward_pe": _score_metric(pe_v, 5, 12, 25, 40, reverse=True),
            "peg_ratio": _score_metric(peg_v, 0.5, 1.0, 2.0, 3.0, reverse=True),
            "profit_margin": _score_metric(
                pm_v * 100 if pm_v is not None else None,
                -5, 0, 15, 30
            ),
            "return_on_equity": _score_metric(
                roe_v * 100 if roe_v is not None else None,
                0, 5, 15, 30
            ),
            "debt_to_equity": _score_metric(dte_v, 0, 0.5, 1.5, 3.0, reverse=True),
            "free_cashflow": (
                10.0 if (fcf_v is not None and fcf_v > 0)
                else 3.0 if fcf_v is None
                else 0.0
            ),
        }

        # --- Weighted total (0–100) ---
        weights = {
            "eps_growth":       0.20,
            "revenue_growth":   0.15,
            "forward_pe":       0.15,
            "peg_ratio":        0.15,
            "profit_margin":    0.10,
            "return_on_equity": 0.10,
            "debt_to_equity":   0.10,
            "free_cashflow":    0.05,
        }

        total_score = sum(
            sub_scores[metric] * weight * 10
            for metric, weight in weights.items()
        )

        # --- Analyst upside ---
        target = fundamentals.get("target_mean_price")
        current = fundamentals.get("current_price")
        analyst_upside_pct = (
            round(((target - current) / current) * 100, 1)
            if (target and current and current > 0)
            else None
        )

        # --- Label ---
        if total_score >= 75:
            label = "Excellent"
        elif total_score >= 60:
            label = "Good"
        elif total_score >= 45:
            label = "Fair"
        else:
            label = "Weak"

        return {
            "total_score": round(total_score, 1),
            "label": label,
            "sub_scores": {k: round(v, 2) for k, v in sub_scores.items()},
            "analyst_upside_pct": analyst_upside_pct,
            "recommendation_mean": fundamentals.get("recommendation_mean"),
        }

    except Exception as e:
        logger.error("score_fundamentals() failed: %s", e)
        return _fallback


def detect_fundamental_alert(symbol: str, prev_snapshot: dict) -> list:
    """
    Compares current fundamentals against a previous snapshot and returns a
    list of plain-English alert strings for significant deterioration.

    prev_snapshot format (from database.get_last_fundamental_snapshot):
        {"data": {...}, "score": float, "recorded_at": str}

    Returns [] on error or if no meaningful comparison can be made.
    """
    try:
        current = get_fundamentals(symbol)

        if "error" in current or not prev_snapshot:
            return []

        prev_data = prev_snapshot.get("data", {})
        if not prev_data:
            return []

        alerts = []

        # 1. Revenue growth turned negative
        cur_rev = current.get("revenue_growth")
        prev_rev = prev_data.get("revenue_growth")
        if cur_rev is not None and prev_rev is not None:
            if cur_rev < 0 and prev_rev >= 0:
                alerts.append(
                    f"Revenue growth turned negative "
                    f"(was +{prev_rev * 100:.1f}%, now {cur_rev * 100:.1f}%)"
                )

        # 2. Debt-to-equity crossed 2.0
        cur_dte = current.get("debt_to_equity")
        prev_dte = prev_data.get("debt_to_equity")
        if cur_dte is not None and prev_dte is not None:
            if cur_dte > 2.0 and prev_dte <= 2.0:
                alerts.append(
                    f"Debt-to-equity crossed danger threshold of 2.0 (now {cur_dte:.1f})"
                )

        # 3. Analyst recommendation worsened by >= 1.0 point
        cur_rec = current.get("recommendation_mean")
        prev_rec = prev_data.get("recommendation_mean")
        if cur_rec is not None and prev_rec is not None:
            if cur_rec - prev_rec >= 1.0:
                alerts.append(
                    f"Analyst recommendation worsened: {prev_rec:.1f} → {cur_rec:.1f}"
                )

        # 4. EPS growth dropped > 10 percentage points
        cur_eps = current.get("eps_growth")
        prev_eps = prev_data.get("eps_growth")
        if cur_eps is not None and prev_eps is not None:
            if (prev_eps - cur_eps) * 100 > 10:
                alerts.append(
                    f"EPS growth dropped significantly: "
                    f"{prev_eps * 100:+.0f}% → {cur_eps * 100:+.0f}%"
                )

        return alerts

    except Exception as e:
        logger.error("detect_fundamental_alert(%s) failed: %s", symbol, e)
        return []
