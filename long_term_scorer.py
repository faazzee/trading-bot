"""
long_term_scorer.py — Combined long-term investment score.

Combines three pillars into a 0–100 composite score:
  Fundamental score  40%  (P/E, EPS growth, revenue, margins, debt)
  Sentiment score    30%  (FinBERT 30-day news sentiment)
  Technical score    30%  (SMA 50/200, relative strength vs SPY)

Labels
──────
≥ 75  STRONG HOLD 🟢
60–74 HOLD        🟡
45–59 WATCH       ⚠️
< 45  EXIT SIGNAL 🔴
"""

import logging
from fundamental_analyzer import get_fundamentals, score_fundamentals
from sentiment_engine import compute_30day_sentiment
from analyzer import compute_long_term_technicals, score_long_term_technicals

logger = logging.getLogger(__name__)


def compute_long_term_score(symbol: str) -> dict:
    """
    Compute a composite 0–100 long-term investment score for the given symbol.

    Weights: Fundamentals 40%, Sentiment 30%, Technicals 30%.

    Returns a dict with composite_score, label, emoji, per-pillar scores,
    a plain-English summary, and all raw upstream data.
    On any failure returns a safe fallback dict with composite_score=50.0.
    """
    try:
        # --- Fetch data from all three pillars ---
        fundamentals = get_fundamentals(symbol)
        fund_scoring = score_fundamentals(fundamentals)
        sentiment    = compute_30day_sentiment(symbol)
        technicals   = compute_long_term_technicals(symbol)
        tech_score   = score_long_term_technicals(technicals)

        # --- Extract pillar scores ---
        fundamental_score = fund_scoring.get("total_score")
        if fundamental_score is None:
            logger.warning(f"[long_term_scorer] score_fundamentals returned no total_score for {symbol}, using neutral 50")
            fundamental_score = 50.0

        sentiment_score = sentiment.get("score")
        if sentiment_score is None:
            logger.warning(f"[long_term_scorer] compute_30day_sentiment returned no score for {symbol}, using neutral 50")
            sentiment_score = 50.0

        technical_score   = tech_score  # already a float

        # --- Composite ---
        composite = (fundamental_score * 0.40) + (sentiment_score * 0.30) + (technical_score * 0.30)
        composite = round(composite, 1)

        # --- Label & emoji ---
        if composite >= 75:
            label = "STRONG HOLD"
            emoji = "🟢"
        elif composite >= 60:
            label = "HOLD"
            emoji = "🟡"
        elif composite >= 45:
            label = "WATCH"
            emoji = "⚠️"
        else:
            label = "EXIT SIGNAL"
            emoji = "🔴"

        # --- Plain-English summary ---
        summary = _build_summary(fundamentals, fund_scoring, sentiment, technicals, label)

        return {
            "symbol":            symbol.upper(),
            "composite_score":   composite,
            "label":             label,
            "emoji":             emoji,
            "fundamental_score": fundamental_score,
            "sentiment_score":   sentiment_score,
            "technical_score":   technical_score,
            "summary":           summary,
            "fundamentals":      fundamentals,
            "sentiment":         sentiment,
            "technicals":        technicals,
            "fund_scoring":      fund_scoring,
        }

    except Exception as e:
        logger.error(f"[long_term_scorer] compute_long_term_score({symbol}): {e}")
        return {
            "symbol":          symbol.upper(),
            "error":           str(e),
            "composite_score": 50.0,
            "label":           "WATCH",
            "emoji":           "⚠️",
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_summary(fundamentals: dict, fund_scoring: dict, sentiment: dict,
                   technicals: dict, label: str) -> str:
    """
    Build a 1–2 sentence plain-English investment summary.
    Each missing pillar falls back to a neutral phrase.
    """
    parts = []

    # --- Fundamentals pillar ---
    fund_label = fund_scoring.get("label", "")
    forward_pe  = fundamentals.get("forward_pe")
    eps_growth  = fundamentals.get("eps_growth")

    if fund_label:
        detail = ""
        if forward_pe is not None:
            detail = f"P/E {round(forward_pe, 1)}"
        elif eps_growth is not None:
            sign = "+" if eps_growth >= 0 else ""
            detail = f"EPS {sign}{round(eps_growth * 100, 0):.0f}% YoY"

        if detail:
            parts.append(f"{fund_label} fundamentals ({detail})")
        else:
            parts.append(f"{fund_label} fundamentals")
    else:
        parts.append("Fundamentals data unavailable")

    # --- Sentiment pillar ---
    sent_label = sentiment.get("label", "")
    sent_score = sentiment.get("score")
    sent_trend = sentiment.get("trend", "")

    if sent_label:
        score_str = f"score {round(sent_score)}" if sent_score is not None else ""
        trend_str = f"trending {sent_trend.lower()}" if sent_trend else ""
        detail_parts = [s for s in [score_str, trend_str] if s]
        detail = ", ".join(detail_parts)
        if detail:
            parts.append(f"{sent_label.lower()} news sentiment ({detail})")
        else:
            parts.append(f"{sent_label.lower()} news sentiment")
    else:
        parts.append("sentiment data unavailable")

    # --- Technicals pillar ---
    above_sma200 = technicals.get("above_sma200")
    if above_sma200 is True:
        parts.append("price above 200-day MA")
    elif above_sma200 is False:
        parts.append("price below 200-day MA")
    else:
        parts.append("200-day MA data unavailable")

    # --- Closing thesis ---
    thesis_map = {
        "STRONG HOLD": "Thesis intact — hold.",
        "HOLD":        "Thesis holds — continue monitoring.",
        "WATCH":       "Monitor closely before adding exposure.",
        "EXIT SIGNAL": "Consider reducing or exiting position.",
    }
    thesis = thesis_map.get(label, "Review position carefully.")

    sentence = ", ".join(parts) + ". " + thesis
    return sentence


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def format_long_term_report(result: dict) -> str:
    """
    Format the dict returned by compute_long_term_score() as a
    Telegram-ready Markdown message (parse_mode="Markdown").

    Returns a plain error string if the result contains an error key.
    """
    try:
        symbol = result.get("symbol", "?")

        if "error" in result:
            return (
                f"❌ Could not compute long-term score for *{symbol}*: "
                f"{result.get('error', 'Unknown error')}"
            )

        composite    = result.get("composite_score", 50.0)
        label        = result.get("label", "WATCH")
        emoji        = result.get("emoji", "⚠️")
        summary      = result.get("summary", "No summary available.")
        fund_score   = result.get("fundamental_score", 50.0)
        sent_score   = result.get("sentiment_score", 50.0)
        tech_score   = result.get("technical_score", 50.0)

        fundamentals = result.get("fundamentals", {})
        fund_scoring = result.get("fund_scoring", {})
        sentiment    = result.get("sentiment", {})
        technicals   = result.get("technicals", {})

        # ── Helpers ──────────────────────────────────────────────────────────

        def fmt_val(value, decimals=1):
            if value is None:
                return "N/A"
            return f"{round(value, decimals)}"

        # ── Fundamentals section ──────────────────────────────────────────────
        fund_label        = fund_scoring.get("label", "N/A")
        forward_pe        = fundamentals.get("forward_pe")
        eps_growth        = fundamentals.get("eps_growth")
        revenue_growth    = fundamentals.get("revenue_growth")
        analyst_upside    = fund_scoring.get("analyst_upside_pct")
        rec_mean          = fund_scoring.get("recommendation_mean")

        pe_str       = fmt_val(forward_pe) if forward_pe is not None else "N/A"
        eps_str      = f"{eps_growth * 100:+.1f}%" if eps_growth is not None else "N/A"
        rev_str      = f"{revenue_growth * 100:+.1f}%" if revenue_growth is not None else "N/A"
        upside_str   = f"{analyst_upside:+.1f}%" if analyst_upside is not None else "N/A"
        rec_str      = f"{round(rec_mean, 1)}/5.0" if rec_mean is not None else "N/A"

        fundamentals_section = (
            f"*── Fundamentals (40%) ──*\n"
            f"Score: {round(fund_score, 1)}/100 ({fund_label})\n"
            f"• Forward P/E: {pe_str}\n"
            f"• EPS Growth: {eps_str}\n"
            f"• Revenue Growth: {rev_str}\n"
            f"• Analyst Upside: {upside_str}\n"
            f"• Recommendation: {rec_str}"
        )

        # ── Sentiment section ─────────────────────────────────────────────────
        sent_label    = sentiment.get("label", "Neutral")
        sent_trend    = sentiment.get("trend", "Stable")
        top_headlines = sentiment.get("top_headlines", [])[:3]

        headlines_text = ""
        if top_headlines:
            headline_lines = []
            for h in top_headlines:
                title      = h.get("title", "")
                hlabel     = h.get("label", "Neutral")
                headline_lines.append(f"• {title} ({hlabel})")
            headlines_text = "\nTop headlines:\n" + "\n".join(headline_lines)

        sentiment_section = (
            f"*── News Sentiment (30%) ──*\n"
            f"Score: {round(sent_score, 1)}/100 ({sent_label}) — Trend: {sent_trend}"
            f"{headlines_text}"
        )

        # ── Technical section ─────────────────────────────────────────────────
        above_sma200     = technicals.get("above_sma200")
        golden_cross     = technicals.get("golden_cross")
        relative_strength = technicals.get("relative_strength")
        momentum_pct     = technicals.get("momentum_pct")

        if above_sma200 is True:
            trend_str = "Above 200-day MA"
        elif above_sma200 is False:
            trend_str = "Below 200-day MA"
        else:
            trend_str = "N/A"

        if golden_cross is True:
            cross_str = "Golden Cross"
        elif golden_cross is False:
            cross_str = "Death Cross"
        else:
            cross_str = "N/A"

        rs_str  = f"{relative_strength:+.1f}%" if relative_strength is not None else "N/A"
        mom_str = f"{momentum_pct:.1f}%" if momentum_pct is not None else "N/A"

        technical_section = (
            f"*── Technical (30%) ──*\n"
            f"Score: {round(tech_score, 1)}/100\n"
            f"• Trend: {trend_str}\n"
            f"• SMA Cross: {cross_str}\n"
            f"• vs S&P 500 (6mo): {rs_str}\n"
            f"• 52-week position: {mom_str}"
        )

        # ── Assemble full report ──────────────────────────────────────────────
        report = (
            f"📊 *Long-Term Analysis — {symbol}*\n\n"
            f"🎯 *Score: {composite}/100 — {emoji} {label}*\n\n"
            f"{fundamentals_section}\n\n"
            f"{sentiment_section}\n\n"
            f"{technical_section}\n\n"
            f"*Summary*\n"
            f"_{summary}_\n\n"
            f"⚠️ _Not financial advice. Do your own research._"
        )

        return report

    except Exception as e:
        logger.error(f"[long_term_scorer] format_long_term_report() failed: {e}")
        return f"❌ Error formatting long-term report: {e}"
