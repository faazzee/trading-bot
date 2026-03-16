"""
scheduler.py — Background tasks that run on a timer.

Tasks
─────
• check_price_alerts   – every N minutes, detect ±threshold% moves
• check_news_alerts    – every M minutes, find important new headlines
• check_opportunities  – every H minutes, scan for buy opportunities
"""

import logging
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
)
from tracker import get_current_price, get_stock_news
from analyzer import is_opportunity
from config import IMPORTANT_NEWS_KEYWORDS

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
    Run technical analysis on every tracked symbol.
    Alert users when a buy opportunity is detected (max once per 24 h).
    """
    symbols = get_all_tracked_symbols()
    if not symbols:
        return

    logger.info(f"[scheduler] Scanning {len(symbols)} symbols for opportunities …")

    for symbol in symbols:
        try:
            is_opp, reasons = is_opportunity(symbol)
            if not is_opp:
                continue

            users = get_users_tracking_symbol(symbol)
            price = get_current_price(symbol)

            reason_lines = "\n".join(f"• {r}" for r in reasons)
            text = (
                f"💡 *OPPORTUNITY ALERT — {symbol}*\n\n"
                f"Current price: *{_fmt_price(price)}*\n\n"
                f"*Why now:*\n{reason_lines}\n\n"
                f"Use /analyze {symbol} for full technical analysis.\n"
                f"⚠️ _Not financial advice. Do your own research._"
            )

            for user_id in users:
                settings = get_user_settings(user_id)
                if not settings["notifications_enabled"] or not settings["opportunity_alerts"]:
                    continue

                if was_alert_sent_recently(user_id, symbol, "opportunity", hours=24):
                    continue

                try:
                    await app.bot.send_message(
                        chat_id=user_id,
                        text=text,
                        parse_mode="Markdown",
                    )
                    record_sent_alert(user_id, symbol, "opportunity")
                    logger.info(f"[scheduler] Opportunity alert sent to {user_id} for {symbol}")
                except Exception as e:
                    logger.error(f"[scheduler] Failed to send opportunity to {user_id}: {e}")

        except Exception as e:
            logger.error(f"[scheduler] check_opportunities — {symbol}: {e}")
