"""
scheduler.py — Background tasks that run on a timer.

Tasks
─────
• check_price_alerts                      – every N minutes, detect ±threshold% moves
• check_news_alerts                       – every M minutes, find important new headlines
• check_opportunities                     – every H minutes, long-term composite score ≥ 70
• check_fundamental_and_sentiment_alerts  – every 6 hours, fundamental + sentiment alerts
• send_weekly_digest                      – every Sunday 9am UTC, portfolio thesis check
"""

import logging
from collections import defaultdict
from datetime import datetime

from database import (
    get_all_tracked_symbols,
    get_users_tracking_symbol,
    get_user_settings,
    get_last_price_snapshot,
    save_price_snapshot,
    was_alert_sent_recently,
    record_sent_alert,
    was_news_sent,
    record_sent_news,
    save_fundamental_snapshot, get_last_fundamental_snapshot,
    save_sentiment_score,
    was_weekly_digest_sent, record_weekly_digest_sent,
    get_portfolio,
)
from tracker import get_current_price, get_stock_news
from config import IMPORTANT_NEWS_KEYWORDS
from fundamental_analyzer import get_fundamentals, score_fundamentals, detect_fundamental_alert
from sentiment_engine import compute_30day_sentiment, detect_sentiment_flip, detect_high_impact_negative
from long_term_scorer import compute_long_term_score, format_long_term_report
from config import FUNDAMENTAL_SENTIMENT_CHECK_INTERVAL, WEEKLY_DIGEST_DAY, WEEKLY_DIGEST_HOUR

logger = logging.getLogger(__name__)


# ── Formatting helpers (duplicated here to avoid circular imports) ──

def _fmt_price(p):
    return f"${p:,.2f}" if p is not None else "N/A"


def _fmt_pct(p):
    if p is None:
        return "N/A"
    icon = "🟢" if p >= 0 else "🔴"
    return f"{icon} {p:+.2f}%"


# ── Task 1: Price alerts ────────────────────────────────────

async def check_price_alerts(app):
    """
    For every tracked symbol, compare the current price to the last
    saved snapshot.  If the change exceeds a user's threshold, fire an alert.
    """
    symbols = get_all_tracked_symbols()
    if not symbols:
        return

    logger.info(f"[scheduler] Checking prices for {len(symbols)} symbols …")

    for symbol in symbols:
        try:
            current_price = get_current_price(symbol)
            if current_price is None:
                continue

            last = get_last_price_snapshot(symbol)

            if last:
                last_price, _ = last
                change_pct = ((current_price - last_price) / last_price) * 100

                users = get_users_tracking_symbol(symbol)
                for user_id in users:
                    settings  = get_user_settings(user_id)
                    if not settings["notifications_enabled"]:
                        continue

                    threshold = settings["alert_threshold"]
                    if abs(change_pct) < threshold:
                        continue

                    alert_type = "price_up" if change_pct > 0 else "price_down"
                    if was_alert_sent_recently(user_id, symbol, alert_type, hours=1):
                        continue

                    icon      = "🚀" if change_pct > 0 else "📉"
                    direction = "SURGED" if change_pct > 0 else "DROPPED"

                    text = (
                        f"{icon} *PRICE ALERT — {symbol}*\n\n"
                        f"Price {direction} *{abs(change_pct):.2f}%*\n\n"
                        f"💰 Now:    *{_fmt_price(current_price)}*\n"
                        f"📊 Before: *{_fmt_price(last_price)}*\n"
                        f"⏰ {datetime.now().strftime('%H:%M')} UTC"
                    )

                    try:
                        await app.bot.send_message(
                            chat_id=user_id,
                            text=text,
                            parse_mode="Markdown",
                        )
                        record_sent_alert(user_id, symbol, alert_type)
                        logger.info(f"[scheduler] Price alert sent to {user_id} for {symbol} ({change_pct:+.2f}%)")
                    except Exception as e:
                        logger.error(f"[scheduler] Failed to send price alert to {user_id}: {e}")

            # Always update snapshot after processing
            save_price_snapshot(symbol, current_price)

        except Exception as e:
            logger.error(f"[scheduler] check_price_alerts — {symbol}: {e}")


# ── Task 2: News alerts ─────────────────────────────────────

async def check_news_alerts(app):
    """
    Fetch recent news for each tracked symbol.  Send headlines that:
      (a) haven't been sent before, AND
      (b) contain at least one 'important' keyword.
    """
    symbols = get_all_tracked_symbols()
    if not symbols:
        return

    logger.info(f"[scheduler] Checking news for {len(symbols)} symbols …")

    for symbol in symbols:
        try:
            news_items = get_stock_news(symbol, max_items=5)
            users      = get_users_tracking_symbol(symbol)

            for item in news_items:
                url = item.get("link", "")
                if not url:
                    continue

                if was_news_sent(symbol, url):
                    continue

                title     = item.get("title", "No title")
                publisher = item.get("publisher", "Unknown")
                ts        = item.get("providerPublishTime")
                date_str  = datetime.fromtimestamp(ts).strftime("%b %d, %Y %H:%M") if ts else "—"

                # Gate on importance
                title_lower = title.lower()
                important   = any(kw in title_lower for kw in IMPORTANT_NEWS_KEYWORDS)

                if important:
                    text = (
                        f"📰 *NEWS ALERT — {symbol}*\n\n"
                        f"_{title}_\n\n"
                        f"🗞️ {publisher}\n"
                        f"📅 {date_str}\n"
                        f"🔗 [Read more]({url})"
                    )

                    for user_id in users:
                        settings = get_user_settings(user_id)
                        if not settings["notifications_enabled"] or not settings["news_alerts"]:
                            continue

                        try:
                            await app.bot.send_message(
                                chat_id=user_id,
                                text=text,
                                parse_mode="Markdown",
                                disable_web_page_preview=True,
                            )
                            logger.info(f"[scheduler] News alert sent to {user_id} for {symbol}")
                        except Exception as e:
                            logger.error(f"[scheduler] Failed to send news to {user_id}: {e}")

                # Mark as sent regardless of importance (avoid re-scanning)
                record_sent_news(symbol, url)

        except Exception as e:
            logger.error(f"[scheduler] check_news_alerts — {symbol}: {e}")


# ── Task 3: Opportunity scanner ─────────────────────────────

async def check_opportunities(app):
    """
    Run long-term analysis on every tracked symbol.
    Alert users when composite score ≥ 70 (max once per 24 h).
    """
    symbols = get_all_tracked_symbols()
    if not symbols:
        return

    logger.info(f"[scheduler] Scanning {len(symbols)} symbols for long-term opportunities …")

    for symbol in symbols:
        try:
            result = compute_long_term_score(symbol)
            if "error" in result or result.get("composite_score", 0) < 70:
                continue

            users = get_users_tracking_symbol(symbol)
            score = result["composite_score"]
            label = result["label"]
            summary = result.get("summary", "")

            text = (
                f"💡 *LONG-TERM OPPORTUNITY — {symbol}*\n\n"
                f"Score: *{score}/100 — {label}*\n\n"
                f"_{summary}_\n\n"
                f"Use /longterm {symbol} for full analysis.\n"
                f"⚠️ _Not financial advice. Do your own research._"
            )

            for user_id in users:
                settings = get_user_settings(user_id)
                if not settings["notifications_enabled"] or not settings["opportunity_alerts"]:
                    continue
                if was_alert_sent_recently(user_id, symbol, "opportunity", hours=24):
                    continue
                try:
                    await app.bot.send_message(chat_id=user_id, text=text, parse_mode="Markdown")
                    record_sent_alert(user_id, symbol, "opportunity")
                    logger.info(f"[scheduler] Long-term opportunity alert sent to {user_id} for {symbol}")
                except Exception as e:
                    logger.error(f"[scheduler] Failed to send opportunity to {user_id}: {e}")

        except Exception as e:
            logger.error(f"[scheduler] check_opportunities — {symbol}: {e}")


# ── Task 4: Fundamental & sentiment alerts ──────────────────

async def check_fundamental_and_sentiment_alerts(app):
    """
    Every 6 hours: score fundamentals and sentiment for all tracked symbols.
    Fire alerts when:
    - Fundamental metrics deteriorate (revenue negative, debt spike, etc.)
    - Sentiment flips from positive to negative or vice versa
    - A single high-confidence negative headline appears (confidence > 0.92)
    Also saves fresh snapshots to DB for trend tracking.
    """
    symbols = get_all_tracked_symbols()
    if not symbols:
        return

    logger.info(f"[scheduler] Running fundamental/sentiment check for {len(symbols)} symbols …")

    for symbol in symbols:
        try:
            # ── Fundamental alerts ─────────────────────────────
            prev_snapshot = get_last_fundamental_snapshot(symbol)
            fundamentals  = get_fundamentals(symbol)

            if "error" not in fundamentals:
                scoring = score_fundamentals(fundamentals)
                fund_alerts = detect_fundamental_alert(symbol, prev_snapshot) if prev_snapshot else []
                save_fundamental_snapshot(symbol, fundamentals, scoring.get("total_score", 50))

                if fund_alerts:
                    users = get_users_tracking_symbol(symbol)
                    alert_lines = "\n".join(f"• {a}" for a in fund_alerts)
                    text = (
                        f"⚠️ *FUNDAMENTAL ALERT — {symbol}*\n\n"
                        f"{alert_lines}\n\n"
                        f"Use /fundamental {symbol} for full details.\n"
                        f"⚠️ _Not financial advice._"
                    )
                    for user_id in users:
                        settings = get_user_settings(user_id)
                        if not settings["notifications_enabled"]:
                            continue
                        if was_alert_sent_recently(user_id, symbol, "fundamental_alert", hours=24):
                            continue
                        try:
                            await app.bot.send_message(chat_id=user_id, text=text, parse_mode="Markdown")
                            record_sent_alert(user_id, symbol, "fundamental_alert")
                        except Exception as e:
                            logger.error(f"[scheduler] Failed to send fundamental alert to {user_id}: {e}")

            # ── Sentiment alerts ──────────────────────────────
            sentiment = compute_30day_sentiment(symbol)
            sent_score = sentiment.get("score", 50)
            sent_label = sentiment.get("label", "Neutral")
            save_sentiment_score(symbol, sent_score, sent_label)

            users = get_users_tracking_symbol(symbol)

            # Sentiment flip alert
            if detect_sentiment_flip(symbol):
                flip_text = (
                    f"🔄 *SENTIMENT FLIP — {symbol}*\n\n"
                    f"News sentiment has shifted significantly in the last 7 days.\n"
                    f"Current: *{sent_label}* (score {sent_score:.0f}/100)\n\n"
                    f"Use /sentiment {symbol} for details.\n"
                    f"⚠️ _Not financial advice._"
                )
                for user_id in users:
                    settings = get_user_settings(user_id)
                    if not settings["notifications_enabled"]:
                        continue
                    if was_alert_sent_recently(user_id, symbol, "sentiment_flip", hours=24):
                        continue
                    try:
                        await app.bot.send_message(chat_id=user_id, text=flip_text, parse_mode="Markdown")
                        record_sent_alert(user_id, symbol, "sentiment_flip")
                    except Exception as e:
                        logger.error(f"[scheduler] Failed to send sentiment flip to {user_id}: {e}")

            # High-impact negative headline alert
            top_headlines = sentiment.get("top_headlines", [])
            headline_texts = [h.get("title", "") for h in top_headlines if h.get("title")]
            high_impact = detect_high_impact_negative(headline_texts)

            if high_impact:
                neg_lines = "\n".join(f"• _{h}_" for h in high_impact[:3])
                neg_text = (
                    f"🚨 *HIGH-IMPACT NEGATIVE NEWS — {symbol}*\n\n"
                    f"{neg_lines}\n\n"
                    f"⚠️ _Not financial advice. Verify before acting._"
                )
                for user_id in users:
                    settings = get_user_settings(user_id)
                    if not settings["notifications_enabled"]:
                        continue
                    if was_alert_sent_recently(user_id, symbol, "high_impact_news", hours=12):
                        continue
                    try:
                        await app.bot.send_message(chat_id=user_id, text=neg_text, parse_mode="Markdown")
                        record_sent_alert(user_id, symbol, "high_impact_news")
                    except Exception as e:
                        logger.error(f"[scheduler] Failed to send high-impact news to {user_id}: {e}")

        except Exception as e:
            logger.error(f"[scheduler] check_fundamental_and_sentiment_alerts — {symbol}: {e}")


# ── Task 5: Weekly portfolio digest ────────────────────────

async def send_weekly_digest(app):
    """
    Every Sunday at 9am UTC: send a full long-term report for each portfolio stock.
    Rate-limited to once per 7 days per user+symbol.
    """
    logger.info("[scheduler] Sending weekly digest …")

    # Get all users who have a portfolio (digest is portfolio-only, not watchlist)
    symbols = get_all_tracked_symbols()
    if not symbols:
        return

    # Build a map of user_id → list of portfolio symbols
    user_symbols = defaultdict(list)

    for symbol in symbols:
        users = get_users_tracking_symbol(symbol)
        for user_id in users:
            portfolio = get_portfolio(user_id)
            portfolio_symbols = {r["symbol"] for r in portfolio}
            if symbol in portfolio_symbols:
                user_symbols[user_id].append(symbol)

    for user_id, syms in user_symbols.items():
        settings = get_user_settings(user_id)
        if not settings["notifications_enabled"]:
            continue

        # Only process symbols that haven't been digested this week
        pending_syms = [s for s in syms if not was_weekly_digest_sent(user_id, s)]
        if not pending_syms:
            continue

        # Send header only when there are pending symbols
        try:
            await app.bot.send_message(
                chat_id=user_id,
                text=f"📅 *Weekly Portfolio Digest*\n_{datetime.now().strftime('%A, %B %d %Y')}_\n\nRunning long-term analysis on your {len(pending_syms)} stock(s)…",
                parse_mode="Markdown",
            )
        except Exception as e:
            logger.error(f"[scheduler] Failed to send digest header to {user_id}: {e}")
            continue

        for symbol in pending_syms:
            try:
                result = compute_long_term_score(symbol)
                text   = format_long_term_report(result)
                await app.bot.send_message(chat_id=user_id, text=text, parse_mode="Markdown")
                record_weekly_digest_sent(user_id, symbol)
                logger.info(f"[scheduler] Weekly digest sent to {user_id} for {symbol}")
            except Exception as e:
                logger.error(f"[scheduler] Weekly digest failed for {user_id}/{symbol}: {e}")
