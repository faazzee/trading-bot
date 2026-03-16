"""
analyzer.py — Technical analysis and investment opportunity detection.

Indicators computed
───────────────────
• RSI (14)          – momentum oscillator
• SMA 20 / SMA 50   – trend direction; golden / death cross
• EMA 12 / EMA 26   – MACD line
• Bollinger Bands   – volatility envelope
• Volume ratio      – current vs average volume

Opportunity scoring
───────────────────
Each signal adds or subtracts points from a neutral score of 50.
Scores ≥ 65 → BUY signal; ≤ 35 → SELL signal.
"""

import logging
import pandas as pd
import numpy as np
from tracker import get_price_history

logger = logging.getLogger(__name__)


# ── Indicator helpers ──────────────────────────────────────

def _rsi(prices: pd.Series, period: int = 14) -> float:
    delta = prices.diff()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta.clip(upper=0)).rolling(period).mean()
    rs    = gain / loss
    series = 100 - (100 / (1 + rs))
    val = series.iloc[-1]
    return float(val) if not pd.isna(val) else None


def _sma(prices: pd.Series, period: int) -> float:
    val = prices.rolling(period).mean().iloc[-1]
    return float(val) if not pd.isna(val) else None


def _ema(prices: pd.Series, period: int) -> float:
    val = prices.ewm(span=period, adjust=False).mean().iloc[-1]
    return float(val) if not pd.isna(val) else None


def _bollinger(prices: pd.Series, period: int = 20, k: float = 2.0):
    """Returns (upper, middle, lower)."""
    mid   = prices.rolling(period).mean()
    std   = prices.rolling(period).std()
    upper = (mid + k * std).iloc[-1]
    lower = (mid - k * std).iloc[-1]
    mid   = mid.iloc[-1]
    if any(pd.isna(v) for v in [upper, mid, lower]):
        return None, None, None
    return float(upper), float(mid), float(lower)


# ── Main analysis ──────────────────────────────────────────

def analyze_stock(symbol: str) -> dict:
    """Return a full technical analysis dict for the given symbol."""
    hist = get_price_history(symbol, period="6mo")

    if hist.empty or len(hist) < 20:
        return {"symbol": symbol, "error": "Not enough price history"}

    closes  = hist["Close"]
    volumes = hist["Volume"]

    current_price = float(closes.iloc[-1])

    # ── Indicators ─────────────────────────────────────────
    rsi    = _rsi(closes)
    sma_20 = _sma(closes, 20)
    sma_50 = _sma(closes, 50) if len(closes) >= 50 else None
    ema_12 = _ema(closes, 12)
    ema_26 = _ema(closes, 26)
    macd   = (ema_12 - ema_26) if (ema_12 and ema_26) else None

    bb_upper, bb_mid, bb_lower = _bollinger(closes)

    # ── Price changes ───────────────────────────────────────
    def pct_change(n_days: int):
        if len(closes) > n_days:
            old = float(closes.iloc[-(n_days + 1)])
            return ((current_price - old) / old) * 100 if old else None
        return None

    change_1d = pct_change(1)
    change_1w = pct_change(5)
    change_1m = pct_change(21)

    # ── Range ───────────────────────────────────────────────
    high_period = float(closes.max())
    low_period  = float(closes.min())
    pct_from_high = ((current_price - high_period) / high_period) * 100
    pct_from_low  = ((current_price - low_period)  / low_period)  * 100

    # ── Volume ──────────────────────────────────────────────
    avg_vol    = float(volumes.mean())
    cur_vol    = float(volumes.iloc[-1])
    vol_ratio  = (cur_vol / avg_vol) if avg_vol > 0 else 1.0

    # ── Signal engine ───────────────────────────────────────
    signals = []
    score   = 50          # start neutral

    # RSI
    if rsi is not None:
        if rsi < 30:
            signals.append("🟢 RSI Oversold (<30) — potential reversal buy")
            score += 15
        elif rsi < 40:
            signals.append("🟡 RSI approaching oversold (30–40)")
            score += 5
        elif rsi > 70:
            signals.append("🔴 RSI Overbought (>70) — caution / potential sell")
            score -= 15
        elif rsi > 60:
            signals.append("🟡 RSI approaching overbought (60–70)")
            score -= 5

    # Moving average cross
    if sma_20 and sma_50:
        if sma_20 > sma_50:
            signals.append("🟢 Golden Cross — SMA20 above SMA50 (bullish trend)")
            score += 10
        else:
            signals.append("🔴 Death Cross — SMA20 below SMA50 (bearish trend)")
            score -= 10

    # Price vs SMA
    if sma_20:
        if current_price > sma_20:
            signals.append("🟢 Price above SMA20 — short-term bullish")
            score += 5
        else:
            signals.append("🔴 Price below SMA20 — short-term bearish")
            score -= 5

    # MACD
    if macd is not None:
        if macd > 0:
            signals.append(f"🟢 MACD positive ({macd:+.3f})")
            score += 5
        else:
            signals.append(f"🔴 MACD negative ({macd:+.3f})")
            score -= 5

    # Bollinger Bands
    if bb_lower and bb_upper:
        if current_price < bb_lower:
            signals.append("🟢 Price below lower Bollinger Band — oversold zone")
            score += 10
        elif current_price > bb_upper:
            signals.append("🔴 Price above upper Bollinger Band — overbought zone")
            score -= 10

    # 52-week range proximity
    if pct_from_low < 5:
        signals.append(f"🟢 Near period low (+{pct_from_low:.1f}%) — potential value entry")
        score += 8
    if pct_from_high > -3:
        signals.append(f"🔴 Near period high ({pct_from_high:.1f}%) — limited upside room")
        score -= 5

    # Volume spike
    if vol_ratio > 2.5:
        signals.append(f"📊 High volume spike: {vol_ratio:.1f}× average — strong conviction move")
    elif vol_ratio < 0.3:
        signals.append("📊 Very low volume — low conviction")

    # Weekly drawdown = potential overselling
    if change_1w is not None and change_1w < -8:
        signals.append(f"⚠️ Down {abs(change_1w):.1f}% this week — watch for bounce or further breakdown")
        score += 5   # contrarian positive

    # Overall label
    if score >= 70:
        overall = "🟢 STRONG BUY"
    elif score >= 60:
        overall = "🟢 BUY"
    elif score >= 45:
        overall = "🟡 NEUTRAL / HOLD"
    elif score >= 35:
        overall = "🔴 SELL"
    else:
        overall = "🔴 STRONG SELL"

    return {
        "symbol":         symbol.upper(),
        "current_price":  current_price,
        "rsi":            rsi,
        "sma_20":         sma_20,
        "sma_50":         sma_50,
        "macd":           macd,
        "bb_upper":       bb_upper,
        "bb_lower":       bb_lower,
        "change_1d":      change_1d,
        "change_1w":      change_1w,
        "change_1m":      change_1m,
        "period_high":    high_period,
        "period_low":     low_period,
        "pct_from_high":  pct_from_high,
        "pct_from_low":   pct_from_low,
        "volume_ratio":   vol_ratio,
        "signals":        signals,
        "score":          score,
        "overall_signal": overall,
    }


def is_opportunity(symbol: str) -> tuple:
    """
    Return (True, [reasons]) if the stock shows a buy opportunity,
    else (False, []).
    """
    analysis = analyze_stock(symbol)
    if "error" in analysis:
        return False, []

    reasons  = []
    is_opp   = False

    rsi = analysis.get("rsi")
    if rsi and rsi < 35:
        reasons.append(f"RSI oversold at {rsi:.1f} — momentum may be reversing")
        is_opp = True

    pfl = analysis.get("pct_from_low")
    if pfl is not None and pfl < 5:
        reasons.append(f"Only {pfl:.1f}% above its recent low — possible value zone")
        is_opp = True

    chg1w = analysis.get("change_1w")
    if chg1w is not None and chg1w < -8:
        reasons.append(f"Down {abs(chg1w):.1f}% this week — check for overselling")
        is_opp = True

    bb_lower = analysis.get("bb_lower")
    price    = analysis.get("current_price")
    if bb_lower and price and price < bb_lower:
        reasons.append("Price below Bollinger lower band — statistically oversold")
        is_opp = True

    sma20 = analysis.get("sma_20")
    sma50 = analysis.get("sma_50")
    if sma20 and sma50 and sma20 > sma50:
        # Verify it's a fresh cross (only fire when score is also positive)
        if analysis.get("score", 50) >= 60:
            reasons.append("Golden Cross forming with bullish momentum")
            is_opp = True

    return is_opp, reasons
