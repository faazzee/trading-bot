"""
sentiment_engine.py — FinBERT-based news sentiment analysis.

Uses ProsusAI/finbert (HuggingFace) — a transformer model trained on
financial news text. Loaded once at startup as a module-level singleton.

Key functions
─────────────
load_finbert()               — initialise the pipeline (called once at startup)
score_headline(text)         — score a single headline → {label, confidence, score}
score_headlines_batch(texts) — score a list of headlines efficiently
compute_30day_sentiment(sym) — aggregate 30-day sentiment for a symbol
detect_sentiment_flip(sym)   — check if sentiment flipped in the last 7 days
detect_high_impact_negative(headlines) — filter very high-confidence negative items
"""

import logging
from transformers import pipeline
from tracker import get_stock_news
from database import get_sentiment_history

logger = logging.getLogger(__name__)

_finbert_pipeline = None   # loaded once via load_finbert()

FINBERT_MODEL = "ProsusAI/finbert"


def load_finbert():
    """Initialise the FinBERT pipeline. Call once at bot startup."""
    global _finbert_pipeline
    try:
        _finbert_pipeline = pipeline("text-classification", model=FINBERT_MODEL)
        logger.info("FinBERT model loaded")
    except Exception as e:
        logger.error(f"Failed to load FinBERT model: {e}")
        _finbert_pipeline = None


def score_headline(text: str) -> dict:
    """
    Score a single headline with FinBERT.

    Returns a dict with keys:
        label      — "Positive", "Negative", or "Neutral"
        confidence — float in [0, 1]
        score      — weighted numeric score in [-1, +1]
    """
    if _finbert_pipeline is None:
        logger.warning("FinBERT pipeline is not loaded; returning neutral score.")
        return {"label": "Neutral", "confidence": 0.0, "score": 0.0}

    try:
        text = text[:512]
        result = _finbert_pipeline(text, truncation=True, max_length=512)[0]

        label = result["label"]          # "positive" / "negative" / "neutral"
        confidence = result["score"]     # float confidence

        label_map = {"positive": 1, "negative": -1, "neutral": 0}
        numeric = label_map.get(label.lower(), 0)
        weighted_score = numeric * confidence

        return {
            "label": label.capitalize(),
            "confidence": confidence,
            "score": weighted_score,
        }
    except Exception as e:
        logger.error(f"score_headline error: {e}")
        return {"label": "Neutral", "confidence": 0.0, "score": 0.0}


def score_headlines_batch(headlines: list) -> list:
    """
    Score a list of headline strings with FinBERT in one batched call.

    Returns a list of dicts matching the format of score_headline(), in the
    same order as the input list. Returns [] if the pipeline is not loaded or
    the input list is empty.
    """
    if _finbert_pipeline is None:
        logger.warning("FinBERT pipeline is not loaded; returning empty batch results.")
        return []
    if not headlines:
        return []

    try:
        truncated = [h[:512] for h in headlines]
        raw_results = _finbert_pipeline(
            truncated, truncation=True, max_length=512, batch_size=8
        )

        label_map = {"positive": 1, "negative": -1, "neutral": 0}
        scored = []
        for result in raw_results:
            label = result["label"]
            confidence = result["score"]
            numeric = label_map.get(label.lower(), 0)
            weighted_score = numeric * confidence
            scored.append(
                {
                    "label": label.capitalize(),
                    "confidence": confidence,
                    "score": weighted_score,
                }
            )
        return scored
    except Exception as e:
        logger.error(f"score_headlines_batch error: {e}")
        return []


def compute_30day_sentiment(symbol: str) -> dict:
    """
    Aggregate 30-day news sentiment for the given symbol.

    Returns a dict with keys:
        score           — 0–100 aggregate sentiment score
        label           — "Positive", "Neutral", or "Negative"
        trend           — "Improving", "Stable", or "Declining"
        top_headlines   — list of up to 5 dicts {title, label, confidence}
        headline_count  — total number of headlines scored
    """
    _neutral_default = {
        "score": 50,
        "label": "Neutral",
        "trend": "Stable",
        "top_headlines": [],
        "headline_count": 0,
    }

    try:
        news_items = get_stock_news(symbol, max_items=20)
        titles = [item["title"] for item in news_items if item.get("title")]

        if not titles:
            return {**_neutral_default, "headline_count": 0}

        scored_results = score_headlines_batch(titles)

        if not scored_results:
            return {**_neutral_default, "headline_count": len(titles)}

        # Map raw scores (−1 to +1) to 0–100 scale
        scaled_scores = [(r["score"] + 1) / 2 * 100 for r in scored_results]

        aggregate_score = sum(scaled_scores) / len(scaled_scores)

        # Label based on aggregate
        if aggregate_score >= 60:
            label = "Positive"
        elif aggregate_score <= 40:
            label = "Negative"
        else:
            label = "Neutral"

        # Trend: compare last 7 items vs the rest
        last_7 = scaled_scores[-7:]
        rest = scaled_scores[:-7]

        last_7_avg = sum(last_7) / len(last_7) if last_7 else aggregate_score
        rest_avg = sum(rest) / len(rest) if rest else aggregate_score

        if last_7_avg > rest_avg + 5:
            trend = "Improving"
        elif last_7_avg < rest_avg - 5:
            trend = "Declining"
        else:
            trend = "Stable"

        # Top 5 headlines
        top_headlines = [
            {
                "title": title,
                "label": result["label"],
                "confidence": result["confidence"],
            }
            for title, result in zip(titles[:5], scored_results[:5])
        ]

        return {
            "score": round(aggregate_score, 1),
            "label": label,
            "trend": trend,
            "top_headlines": top_headlines,
            "headline_count": len(titles),
        }
    except Exception as e:
        logger.error(f"compute_30day_sentiment({symbol}) error: {e}")
        return {**_neutral_default, "headline_count": 0}


def detect_sentiment_flip(symbol: str) -> bool:
    """
    Return True if the sentiment for *symbol* has crossed the 60/40 boundary
    (positive→negative or negative→positive) within the last 7 days.

    Requires at least 2 rows of stored history; returns False otherwise.
    """
    try:
        history = get_sentiment_history(symbol, days=7)
        if len(history) < 2:
            return False

        first_score = history[0]["score"]
        last_score = history[-1]["score"]

        if (first_score >= 60 and last_score <= 40) or (
            first_score <= 40 and last_score >= 60
        ):
            return True

        return False
    except Exception as e:
        logger.error(f"detect_sentiment_flip({symbol}) error: {e}")
        return False


def detect_high_impact_negative(headlines: list) -> list:
    """
    Filter headlines that FinBERT classifies as Negative with high confidence.

    Args:
        headlines: list of headline strings

    Returns:
        List of headline strings where label == "Negative" AND confidence > 0.92.
    """
    try:
        scored_results = score_headlines_batch(headlines)
        high_impact = [
            title
            for title, result in zip(headlines, scored_results)
            if result["label"] == "Negative" and result["confidence"] > 0.92
        ]
        return high_impact
    except Exception as e:
        logger.error(f"detect_high_impact_negative error: {e}")
        return []
