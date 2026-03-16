"""
tracker.py — Fetch stock prices, metadata, and news via yfinance.
"""

import logging
import yfinance as yf
import pandas as pd

logger = logging.getLogger(__name__)


def get_current_price(symbol: str):
    """Return the latest close price or None on failure."""
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="1d", interval="1m")
        if not hist.empty:
            return float(hist["Close"].iloc[-1])
        # Fallback to info dict
        info = ticker.info
        return info.get("currentPrice") or info.get("regularMarketPrice")
    except Exception as e:
        logger.error(f"[tracker] get_current_price({symbol}): {e}")
        return None


def get_price_history(symbol: str, period: str = "3mo") -> pd.DataFrame:
    """Return a DataFrame with OHLCV columns."""
    try:
        ticker = yf.Ticker(symbol)
        return ticker.history(period=period)
    except Exception as e:
        logger.error(f"[tracker] get_price_history({symbol}): {e}")
        return pd.DataFrame()


def get_quick_summary(symbol: str) -> dict:
    """One-call snapshot: price, change %, key stats."""
    try:
        ticker  = yf.Ticker(symbol)
        info    = ticker.info
        hist    = ticker.history(period="2d")

        current_price = prev_close = change_pct = None

        if not hist.empty:
            current_price = float(hist["Close"].iloc[-1])
            if len(hist) >= 2:
                prev_close = float(hist["Close"].iloc[-2])
            else:
                prev_close = info.get("previousClose")
            if prev_close:
                change_pct = ((current_price - prev_close) / prev_close) * 100

        volume     = hist["Volume"].iloc[-1] if not hist.empty else None
        avg_volume = info.get("averageVolume")

        return {
            "symbol":        symbol.upper(),
            "name":          info.get("shortName", symbol),
            "current_price": current_price,
            "prev_close":    prev_close,
            "change_pct":    change_pct,
            "market_cap":    info.get("marketCap"),
            "volume":        int(volume) if volume else None,
            "avg_volume":    avg_volume,
            "52w_high":      info.get("fiftyTwoWeekHigh"),
            "52w_low":       info.get("fiftyTwoWeekLow"),
            "pe_ratio":      info.get("trailingPE"),
            "sector":        info.get("sector"),
            "exchange":      info.get("exchange"),
            "currency":      info.get("currency", "USD"),
        }
    except Exception as e:
        logger.error(f"[tracker] get_quick_summary({symbol}): {e}")
        return {"symbol": symbol, "error": str(e)}


def get_stock_news(symbol: str, max_items: int = 5) -> list:
    """Return recent news items as list of dicts."""
    try:
        ticker = yf.Ticker(symbol)
        news   = ticker.news or []
        return news[:max_items]
    except Exception as e:
        logger.error(f"[tracker] get_stock_news({symbol}): {e}")
        return []


def validate_symbol(symbol: str) -> bool:
    """Return True if yfinance can find a valid ticker for this symbol."""
    try:
        info = yf.Ticker(symbol).info
        return bool(info.get("symbol") or info.get("shortName") or info.get("longName"))
    except Exception:
        return False
