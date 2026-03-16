"""
bot.py — Telegram bot entry point.

Commands
────────
/start           – welcome + help
/add  SYM [shares] [avg_price]  – add to portfolio
/remove SYM      – remove from portfolio
/watch SYM       – add to watchlist
/unwatch SYM     – remove from watchlist
/portfolio       – show portfolio with live P&L
/watchlist       – show watchlist with live prices
/price SYM       – price snapshot + inline buttons
/analyze SYM     – full technical analysis
/news SYM        – latest headlines
/opportunities   – scan tracked stocks for buy signals
/setalert [pct]  – set price alert threshold
/togglenews      – toggle news notifications
/toggleopps      – toggle opportunity notifications
/settings        – view current settings
/help            – full command reference
"""

import logging
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import (
    TELEGRAM_BOT_TOKEN,
    PRICE_CHECK_INTERVAL,
    NEWS_CHECK_INTERVAL,
    OPPORTUNITY_CHECK_INTERVAL,
    LOG_LEVEL,
)
from database import (
    init_db,
    add_to_portfolio, remove_from_portfolio, get_portfolio, is_in_portfolio,
    add_to_watchlist, remove_from_watchlist, get_watchlist, is_in_watchlist,
    get_user_settings, update_user_settings,
)
from tracker import get_current_price, get_quick_summary, get_stock_news, validate_symbol
from analyzer import analyze_stock, is_opportunity
from scheduler import check_price_alerts, check_news_alerts, check_opportunities

logging.basicConfig(
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    level=getattr(logging, LOG_LEVEL, logging.INFO),
)
logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
#  Formatting helpers
# ═══════════════════════════════════════════════════════════

def fmt_price(p):
    return f"${p:,.2f}" if p is not None else "N/A"


def fmt_change(pct):
    if pct is None:
        return "N/A"
    icon = "🟢" if pct >= 0 else "🔴"
    return f"{icon} {pct:+.2f}%"


def fmt_large(n):
    if n is None:
        return "N/A"
    if n >= 1e12:
        return f"${n/1e12:.2f}T"
    if n >= 1e9:
        return f"${n/1e9:.2f}B"
    if n >= 1e6:
        return f"${n/1e6:.2f}M"
    return f"${n:,.0f}"


def fmt_vol(v):
    if v is None:
        return "N/A"
    if v >= 1_000_000:
        return f"{v/1_000_000:.1f}M"
    if v >= 1_000:
        return f"{v/1_000:.0f}K"
    return str(v)


# ═══════════════════════════════════════════════════════════
#  /start  &  /help
# ═══════════════════════════════════════════════════════════

HELP_TEXT = """
👋 *Stock Tracker Bot* — your personal market assistant 📈

━━━ *Portfolio & Watchlist* ━━━
/add `SYMBOL` `[shares]` `[avg_price]`
  _Add a stock to your portfolio_
/remove `SYMBOL` — Remove from portfolio
/watch `SYMBOL`  — Add stock to watchlist
/unwatch `SYMBOL` — Remove from watchlist
/portfolio       — Live portfolio overview & P\\&L
/watchlist       — Watchlist with live prices

━━━ *Market Data* ━━━
/price `SYMBOL`   — Price snapshot & quick stats
/analyze `SYMBOL` — Full technical analysis
/news `SYMBOL`    — Latest headlines
/opportunities   — Scan your stocks for buy signals

━━━ *Settings & Alerts* ━━━
/setalert `[%]`  — Price alert threshold \\(default 3%\\)
/togglenews      — Turn news alerts on/off
/toggleopps      — Turn opportunity alerts on/off
/settings        — View current settings
/help            — This message

━━━ *Auto Notifications* ━━━
🔔 Price moves beyond your threshold
📰 Important breaking news
💡 Investment opportunity signals
"""


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.effective_user.first_name
    await update.message.reply_text(
        f"Welcome, {name}! 🎉\n" + HELP_TEXT,
        parse_mode="MarkdownV2",
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_TEXT, parse_mode="MarkdownV2")


# ═══════════════════════════════════════════════════════════
#  Portfolio commands
# ═══════════════════════════════════════════════════════════

async def add_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    args    = context.args

    if not args:
        await update.message.reply_text(
            "❌ Usage: /add SYMBOL [shares] [avg\\_price]\n"
            "Example: `/add AAPL 10 175.50`",
            parse_mode="Markdown",
        )
        return

    symbol    = args[0].upper()
    shares    = float(args[1]) if len(args) > 1 else 0.0
    avg_price = float(args[2]) if len(args) > 2 else 0.0

    msg = await update.message.reply_text(f"🔍 Validating *{symbol}*…", parse_mode="Markdown")

    if not validate_symbol(symbol):
        await msg.edit_text(f"❌ *{symbol}* is not a recognised ticker symbol.", parse_mode="Markdown")
        return

    add_to_portfolio(user_id, symbol, shares, avg_price)
    summary = get_quick_summary(symbol)

    lines = [f"✅ *{symbol}* added to portfolio!"]
    if summary and summary.get("current_price"):
        lines.append(f"💰 Current price: *{fmt_price(summary['current_price'])}*")
        lines.append(f"📊 Today: {fmt_change(summary.get('change_pct'))}")
    if shares > 0:
        lines.append(f"📦 Shares tracked: *{shares}*")
    if avg_price > 0:
        lines.append(f"💵 Your avg price: *{fmt_price(avg_price)}*")

    await msg.edit_text("\n".join(lines), parse_mode="Markdown")


async def remove_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not context.args:
        await update.message.reply_text("❌ Usage: /remove SYMBOL")
        return
    symbol = context.args[0].upper()
    remove_from_portfolio(user_id, symbol)
    await update.message.reply_text(f"✅ *{symbol}* removed from portfolio.", parse_mode="Markdown")


async def portfolio_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id   = update.effective_user.id
    portfolio = get_portfolio(user_id)

    if not portfolio:
        await update.message.reply_text(
            "📭 Your portfolio is empty.\nUse /add SYMBOL to start tracking."
        )
        return

    msg = await update.message.reply_text("⏳ Loading portfolio…")

    total_value = total_cost = 0.0
    lines = ["📊 *Your Portfolio*\n"]

    for row in portfolio:
        symbol    = row["symbol"]
        shares    = row["shares"]
        avg_price = row["avg_price"]

        summary = get_quick_summary(symbol)
        price   = summary.get("current_price") if summary else None

        if price:
            line = f"*{symbol}* — {fmt_price(price)} {fmt_change(summary.get('change_pct'))}"

            if shares > 0:
                cur_val = shares * price
                total_value += cur_val
                line += f"\n  📦 {shares} shares · value: *{fmt_price(cur_val)}*"

                if avg_price > 0:
                    cost    = shares * avg_price
                    total_cost += cost
                    pnl     = cur_val - cost
                    pnl_pct = (pnl / cost) * 100
                    icon    = "🟢" if pnl >= 0 else "🔴"
                    line   += f"\n  {icon} P&L: {fmt_price(pnl)} ({pnl_pct:+.1f}%)"
        else:
            line = f"*{symbol}* — ❌ unavailable"

        lines.append(line)

    if total_value > 0:
        lines.append(f"\n💼 *Total Value:* {fmt_price(total_value)}")
        if total_cost > 0:
            total_pnl     = total_value - total_cost
            total_pnl_pct = (total_pnl / total_cost) * 100
            icon          = "🟢" if total_pnl >= 0 else "🔴"
            lines.append(f"{icon} *Total P&L:* {fmt_price(total_pnl)} ({total_pnl_pct:+.1f}%)")

    await msg.edit_text("\n".join(lines), parse_mode="Markdown")


# ═══════════════════════════════════════════════════════════
#  Watchlist commands
# ═══════════════════════════════════════════════════════════

async def watch_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not context.args:
        await update.message.reply_text("❌ Usage: /watch SYMBOL")
        return

    symbol = context.args[0].upper()
    msg    = await update.message.reply_text(f"🔍 Validating *{symbol}*…", parse_mode="Markdown")

    if not validate_symbol(symbol):
        await msg.edit_text(f"❌ *{symbol}* is not a recognised ticker symbol.", parse_mode="Markdown")
        return

    add_to_watchlist(user_id, symbol)
    await msg.edit_text(
        f"✅ *{symbol}* added to watchlist.\n"
        f"You'll receive price, news & opportunity alerts for it.",
        parse_mode="Markdown",
    )


async def unwatch_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not context.args:
        await update.message.reply_text("❌ Usage: /unwatch SYMBOL")
        return
    symbol = context.args[0].upper()
    remove_from_watchlist(user_id, symbol)
    await update.message.reply_text(f"✅ *{symbol}* removed from watchlist.", parse_mode="Markdown")


async def watchlist_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id   = update.effective_user.id
    watchlist = get_watchlist(user_id)

    if not watchlist:
        await update.message.reply_text("📭 Watchlist is empty. Use /watch SYMBOL.")
        return

    msg   = await update.message.reply_text("⏳ Loading watchlist…")
    lines = ["👀 *Your Watchlist*\n"]

    for row in watchlist:
        symbol  = row["symbol"]
        summary = get_quick_summary(symbol)
        price   = summary.get("current_price") if summary else None
        if price:
            lines.append(f"*{symbol}* — {fmt_price(price)} {fmt_change(summary.get('change_pct'))}")
        else:
            lines.append(f"*{symbol}* — ❌ unavailable")

    await msg.edit_text("\n".join(lines), parse_mode="Markdown")


# ═══════════════════════════════════════════════════════════
#  /price
# ═══════════════════════════════════════════════════════════

async def price_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ Usage: /price SYMBOL\nExample: `/price AAPL`", parse_mode="Markdown")
        return

    symbol  = context.args[0].upper()
    msg     = await update.message.reply_text(f"🔍 Fetching *{symbol}*…", parse_mode="Markdown")
    summary = get_quick_summary(symbol)

    if not summary or "error" in summary:
        await msg.edit_text(f"❌ Could not fetch data for *{symbol}*.", parse_mode="Markdown")
        return

    vol     = summary.get("volume")
    avg_vol = summary.get("avg_volume")
    vol_str = f"{fmt_vol(vol)} (avg {fmt_vol(avg_vol)})" if vol else "N/A"

    text = (
        f"📈 *{summary.get('name', symbol)}* (`{symbol}`)\n\n"
        f"💰 Price:      *{fmt_price(summary.get('current_price'))}*\n"
        f"📊 Change:     {fmt_change(summary.get('change_pct'))}\n"
        f"📉 52W Low:    {fmt_price(summary.get('52w_low'))}\n"
        f"📈 52W High:   {fmt_price(summary.get('52w_high'))}\n"
        f"🏢 Mkt Cap:    {fmt_large(summary.get('market_cap'))}\n"
        f"📊 Volume:     {vol_str}\n"
        f"💹 P/E:        {summary.get('pe_ratio') or 'N/A'}\n"
        f"🏷️  Sector:     {summary.get('sector') or 'N/A'}\n"
        f"🌐 Exchange:   {summary.get('exchange') or 'N/A'}"
    )

    keyboard = [
        [
            InlineKeyboardButton("📊 Analyze", callback_data=f"analyze|{symbol}"),
            InlineKeyboardButton("📰 News",    callback_data=f"news|{symbol}"),
        ],
        [
            InlineKeyboardButton("💡 Opportunities", callback_data=f"opps|{symbol}"),
        ],
    ]

    await msg.edit_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))


# ═══════════════════════════════════════════════════════════
#  /analyze
# ═══════════════════════════════════════════════════════════

async def analyze_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ Usage: /analyze SYMBOL\nExample: `/analyze TSLA`", parse_mode="Markdown")
        return

    symbol = context.args[0].upper()
    msg    = await update.message.reply_text(f"🔬 Analysing *{symbol}*…", parse_mode="Markdown")

    a = analyze_stock(symbol)

    if "error" in a:
        await msg.edit_text(f"❌ Cannot analyse *{symbol}*: {a['error']}", parse_mode="Markdown")
        return

    signals_block = "\n".join(a.get("signals") or ["No clear signals detected"])

    # ── Fix: extract formatted values before building the f-string ──
    rsi_str  = "{:.1f}".format(a["rsi"])  if a.get("rsi")  else "N/A"
    macd_str = "{:+.3f}".format(a["macd"]) if a.get("macd") else "N/A"

    text = (
        f"🔬 *Technical Analysis — {symbol}*\n\n"
        f"💰 Price: *{fmt_price(a.get('current_price'))}*\n\n"
        f"*── Indicators ──*\n"
        f"• RSI (14):  `{rsi_str}`\n"
        f"• SMA 20:    {fmt_price(a.get('sma_20'))}\n"
        f"• SMA 50:    {fmt_price(a.get('sma_50'))}\n"
        f"• MACD:      `{macd_str}`\n"
        f"• BB Upper:  {fmt_price(a.get('bb_upper'))}\n"
        f"• BB Lower:  {fmt_price(a.get('bb_lower'))}\n\n"
        f"*── Price Performance ──*\n"
        f"• 1 Day:   {fmt_change(a.get('change_1d'))}\n"
        f"• 1 Week:  {fmt_change(a.get('change_1w'))}\n"
        f"• 1 Month: {fmt_change(a.get('change_1m'))}\n\n"
        f"*── Period Range ──*\n"
        f"• From Low:  +{a.get('pct_from_low', 0):.1f}%\n"
        f"• From High: {a.get('pct_from_high', 0):.1f}%\n"
        f"• Volume:    {a.get('volume_ratio', 1):.1f}× average\n\n"
        f"*── Signals ──*\n"
        f"{signals_block}\n\n"
        f"🎯 *Overall: {a.get('overall_signal', 'N/A')}*\n"
        f"_Score: {a.get('score', 50)}/100_\n\n"
        f"⚠️ _Not financial advice. Do your own research._"
    )

    await msg.edit_text(text, parse_mode="Markdown")


# ═══════════════════════════════════════════════════════════
#  /news
# ═══════════════════════════════════════════════════════════

async def news_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ Usage: /news SYMBOL\nExample: `/news MSFT`", parse_mode="Markdown")
        return

    symbol = context.args[0].upper()
    msg    = await update.message.reply_text(f"🔍 Fetching news for *{symbol}*…", parse_mode="Markdown")
    items  = get_stock_news(symbol, max_items=6)

    if not items:
        await msg.edit_text(f"📭 No recent news found for *{symbol}*.", parse_mode="Markdown")
        return

    lines = [f"📰 *Latest News — {symbol}*\n"]

    for item in items:
        title     = item.get("title", "No title")
        url       = item.get("link", "")
        publisher = item.get("publisher", "")
        ts        = item.get("providerPublishTime")
        date_str  = datetime.fromtimestamp(ts).strftime("%b %d") if ts else ""

        line = f"• [{title}]({url})"
        if publisher or date_str:
            meta = " | ".join(filter(None, [date_str, publisher]))
            line += f"\n  _{meta}_"
        lines.append(line)

    await msg.edit_text(
        "\n".join(lines),
        parse_mode="Markdown",
        disable_web_page_preview=True,
    )


# ═══════════════════════════════════════════════════════════
#  /opportunities
# ═══════════════════════════════════════════════════════════

async def opportunities_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id   = update.effective_user.id
    portfolio = get_portfolio(user_id)
    watchlist = get_watchlist(user_id)
    symbols   = list({r["symbol"] for r in portfolio} | {r["symbol"] for r in watchlist})

    if not symbols:
        await update.message.reply_text("📭 Track some stocks first with /add or /watch.")
        return

    msg = await update.message.reply_text(f"🔍 Scanning {len(symbols)} stocks…")

    found = []
    for symbol in symbols:
        is_opp, reasons = is_opportunity(symbol)
        if is_opp:
            price = get_current_price(symbol)
            found.append((symbol, price, reasons))

    if not found:
        await msg.edit_text(
            "🔍 No strong buy opportunities right now.\n"
            "Your tracked stocks appear fairly valued at current prices."
        )
        return

    lines = [f"💡 *{len(found)} Opportunity Alert{'s' if len(found)>1 else ''} Detected*\n"]

    for symbol, price, reasons in found:
        lines.append(f"*{symbol}* — {fmt_price(price)}")
        for r in reasons:
            lines.append(f"  • {r}")
        lines.append("")

    lines.append("⚠️ _Not financial advice. Always do your own research._")

    await msg.edit_text("\n".join(lines), parse_mode="Markdown")


# ═══════════════════════════════════════════════════════════
#  Settings commands
# ═══════════════════════════════════════════════════════════

async def settings_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id  = update.effective_user.id
    s        = get_user_settings(user_id)

    text = (
        f"⚙️ *Your Settings*\n\n"
        f"🚨 Price alert threshold: *{s['alert_threshold']}%*\n"
        f"📰 News alerts:           {'✅ ON' if s['news_alerts'] else '❌ OFF'}\n"
        f"💡 Opportunity alerts:    {'✅ ON' if s['opportunity_alerts'] else '❌ OFF'}\n"
        f"🔔 All notifications:     {'✅ ON' if s['notifications_enabled'] else '❌ OFF'}\n\n"
        f"Change with:\n"
        f"• /setalert `[%]` — e.g. `/setalert 5`\n"
        f"• /togglenews\n"
        f"• /toggleopps"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def setalert_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    s       = get_user_settings(user_id)

    if not context.args:
        await update.message.reply_text(
            f"Current threshold: *{s['alert_threshold']}%*\n"
            f"Usage: /setalert `[percentage]`\nExample: `/setalert 5`",
            parse_mode="Markdown",
        )
        return

    try:
        pct = float(context.args[0])
        if not (0.5 <= pct <= 50):
            raise ValueError
        update_user_settings(user_id, alert_threshold=pct)
        await update.message.reply_text(
            f"✅ Price alert threshold set to *{pct}%*", parse_mode="Markdown"
        )
    except ValueError:
        await update.message.reply_text("❌ Please enter a value between 0.5 and 50.\nExample: `/setalert 5`", parse_mode="Markdown")


async def togglenews_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    s       = get_user_settings(user_id)
    new_val = 0 if s["news_alerts"] else 1
    update_user_settings(user_id, news_alerts=new_val)
    status = "✅ ON" if new_val else "❌ OFF"
    await update.message.reply_text(f"📰 News alerts: *{status}*", parse_mode="Markdown")


async def toggleopps_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    s       = get_user_settings(user_id)
    new_val = 0 if s["opportunity_alerts"] else 1
    update_user_settings(user_id, opportunity_alerts=new_val)
    status = "✅ ON" if new_val else "❌ OFF"
    await update.message.reply_text(f"💡 Opportunity alerts: *{status}*", parse_mode="Markdown")


# ═══════════════════════════════════════════════════════════
#  Inline button callbacks
# ═══════════════════════════════════════════════════════════

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    action, symbol = query.data.split("|", 1)
    symbol = symbol.upper()

    if action == "analyze":
        a = analyze_stock(symbol)
        if "error" in a:
            await query.message.reply_text(f"❌ Analysis failed for {symbol}: {a['error']}")
            return

        # ── Fix: extract formatted values before building the f-string ──
        rsi_str  = "{:.1f}".format(a["rsi"])   if a.get("rsi")  else "N/A"
        macd_str = "{:+.3f}".format(a["macd"]) if a.get("macd") else "N/A"

        signals_block = "\n".join(a.get("signals") or ["No signals"])
        text = (
            f"🔬 *{symbol} Quick Analysis*\n\n"
            f"💰 {fmt_price(a.get('current_price'))}\n"
            f"RSI: `{rsi_str}`  "
            f"MACD: `{macd_str}`\n\n"
            f"{signals_block}\n\n"
            f"🎯 *{a.get('overall_signal', 'N/A')}*"
        )
        await query.message.reply_text(text, parse_mode="Markdown")

    elif action == "news":
        items = get_stock_news(symbol, max_items=4)
        if not items:
            await query.message.reply_text(f"📭 No news for {symbol}")
            return
        lines = [f"📰 *News — {symbol}*\n"]
        for item in items:
            title = item.get("title", "")
            url   = item.get("link", "")
            lines.append(f"• [{title}]({url})")
        await query.message.reply_text(
            "\n".join(lines), parse_mode="Markdown", disable_web_page_preview=True
        )

    elif action == "opps":
        is_opp, reasons = is_opportunity(symbol)
        if not is_opp:
            await query.message.reply_text(f"🔍 No clear opportunity detected for *{symbol}* right now.", parse_mode="Markdown")
        else:
            price  = get_current_price(symbol)
            reason_lines = "\n".join(f"• {r}" for r in reasons)
            text = (
                f"💡 *Opportunity — {symbol}*\n"
                f"{fmt_price(price)}\n\n"
                f"{reason_lines}\n\n"
                f"⚠️ _Not financial advice._"
            )
            await query.message.reply_text(text, parse_mode="Markdown")


# ═══════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════

def main():
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set in .env")

    init_db()
    logger.info("✅ Database initialised")

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # ── Register command handlers ──────────────────────────
    handlers = [
        ("start",        start),
        ("help",         help_cmd),
        ("add",          add_cmd),
        ("remove",       remove_cmd),
        ("watch",        watch_cmd),
        ("unwatch",      unwatch_cmd),
        ("portfolio",    portfolio_cmd),
        ("watchlist",    watchlist_cmd),
        ("price",        price_cmd),
        ("analyze",      analyze_cmd),
        ("news",         news_cmd),
        ("opportunities",opportunities_cmd),
        ("settings",     settings_cmd),
        ("setalert",     setalert_cmd),
        ("togglenews",   togglenews_cmd),
        ("toggleopps",   toggleopps_cmd),
    ]
    for command, handler in handlers:
        app.add_handler(CommandHandler(command, handler))

    app.add_handler(CallbackQueryHandler(button_callback))

    # ── Start background scheduler ─────────────────────────
    scheduler = AsyncIOScheduler(timezone="UTC")

    scheduler.add_job(
        check_price_alerts, "interval",
        minutes=PRICE_CHECK_INTERVAL,
        args=[app],
        id="price_alerts",
        max_instances=1,
    )
    scheduler.add_job(
        check_news_alerts, "interval",
        minutes=NEWS_CHECK_INTERVAL,
        args=[app],
        id="news_alerts",
        max_instances=1,
    )
    scheduler.add_job(
        check_opportunities, "interval",
        minutes=OPPORTUNITY_CHECK_INTERVAL,
        args=[app],
        id="opportunity_scan",
        max_instances=1,
    )

    async def post_init(application: Application) -> None:
        scheduler.start()
        logger.info(
            f"🕐 Scheduler running — prices every {PRICE_CHECK_INTERVAL}m, "
            f"news every {NEWS_CHECK_INTERVAL}m, opps every {OPPORTUNITY_CHECK_INTERVAL}m"
        )

    app.post_init = post_init

    logger.info("🤖 Stock Tracker Bot is live!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()