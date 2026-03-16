# 📈 Stock Tracker Bot

A Telegram bot that tracks your stock portfolio and watchlist with real-time price alerts, breaking news, and investment opportunity detection.

---

## Features

| Feature | Details |
|---|---|
| **Portfolio tracking** | Add stocks with optional shares + avg price for live P&L |
| **Watchlist** | Monitor any stock without owning it |
| **Price alerts** | Auto-notify on sudden moves (configurable %, default 3%) |
| **News alerts** | Important headlines filtered by impact keywords |
| **Opportunity scanner** | RSI oversold, golden cross, Bollinger breakouts, 52W low proximity |
| **Technical analysis** | RSI, SMA 20/50, EMA 12/26, MACD, Bollinger Bands, volume analysis |
| **Per-user settings** | Each user sets their own thresholds independently |

---

## Quick Start

### 1. Create a Telegram Bot

1. Open Telegram, search for **@BotFather**
2. Send `/newbot` and follow the prompts
3. Copy the **bot token** you receive

### 2. Install dependencies

```bash
# Python 3.10+ required
pip install -r requirements.txt
```

### 3. Configure environment

```bash
cp .env.example .env
# Edit .env and paste your TELEGRAM_BOT_TOKEN
```

### 4. Run the bot

```bash
python bot.py
```

Open Telegram, find your bot, and send `/start`.

---

## Commands

### Portfolio & Watchlist
```
/add AAPL 10 175.50   — Add AAPL: 10 shares at $175.50 avg
/add AAPL             — Add without share tracking
/remove AAPL          — Remove from portfolio
/watch GOOGL          — Add to watchlist (no shares)
/unwatch GOOGL        — Remove from watchlist
/portfolio            — Live view with P&L
/watchlist            — Live view of watched stocks
```

### Market Data
```
/price AAPL           — Price snapshot with inline buttons
/analyze TSLA         — Full technical analysis
/news MSFT            — Latest headlines
/opportunities        — Scan your stocks for buy signals
```

### Alerts & Settings
```
/setalert 5           — Alert when price moves ±5%
/togglenews           — Toggle news notifications
/toggleopps           — Toggle opportunity alerts
/settings             — View your current settings
```

---

## How Alerts Work

### Price Alerts
The scheduler checks every **5 minutes** (configurable). If the price has moved more than your threshold since the last check, you get an instant Telegram message. Alerts are rate-limited to once per hour per symbol to prevent spam.

### News Alerts
Every **30 minutes**, the bot scans recent headlines for your tracked symbols. Only articles containing impact keywords (earnings, merger, FDA, downgrade, etc.) are forwarded. Each article is sent only once (deduplication via SQLite).

### Opportunity Alerts
Every **60 minutes**, each tracked symbol runs through the technical analyzer. You'll be alerted if **any** of these conditions hold:
- RSI < 35 (momentum oversold)
- Price within 5% of its recent low
- Down >8% in the past week (potential oversell)
- Price below lower Bollinger Band
- Golden Cross forming with bullish momentum

Opportunity alerts fire at most once per 24 hours per symbol.

---

## Technical Analysis Explained

| Indicator | What it means |
|---|---|
| **RSI < 30** | Oversold — momentum may reverse upward |
| **RSI > 70** | Overbought — momentum may reverse downward |
| **Golden Cross** | SMA20 crossed above SMA50 — medium-term bullish |
| **Death Cross** | SMA20 crossed below SMA50 — medium-term bearish |
| **MACD > 0** | Short-term momentum above long-term — bullish |
| **Price < BB lower** | Statistically stretched to the downside |
| **Volume spike** | High conviction behind the price move |

The overall score ranges 0–100; ≥65 = BUY, ≤35 = SELL.

> ⚠️ All signals are informational. This is not financial advice.

---

## Running on a Server (24/7)

### Using systemd (Linux)

Create `/etc/systemd/system/stockbot.service`:

```ini
[Unit]
Description=Stock Tracker Telegram Bot
After=network.target

[Service]
Type=simple
User=your_user
WorkingDirectory=/path/to/stock_tracker_bot
ExecStart=/usr/bin/python3 bot.py
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable stockbot
sudo systemctl start stockbot
sudo systemctl status stockbot
```

### Using screen / tmux

```bash
screen -S stockbot
python bot.py
# Ctrl+A, D to detach
```

---

## Project Structure

```
stock_tracker_bot/
├── bot.py          # Telegram bot handlers + main entry point
├── scheduler.py    # Background alert tasks (price / news / opps)
├── analyzer.py     # RSI, SMA, MACD, Bollinger Bands, scoring
├── tracker.py      # yfinance wrapper for prices & news
├── database.py     # SQLite schema + all DB operations
├── config.py       # Environment variable loading
├── requirements.txt
├── .env.example
└── README.md
```

---

## Customising

**Add more symbols to scan automatically** — just add them to any user's portfolio or watchlist via Telegram commands.

**Change alert frequency** — edit `PRICE_CHECK_INTERVAL`, `NEWS_CHECK_INTERVAL`, `OPPORTUNITY_CHECK_INTERVAL` in `.env`.

**Add more news keywords** — edit `IMPORTANT_NEWS_KEYWORDS` list in `config.py`.

**Support multiple users** — works out of the box; each Telegram user has their own portfolio, watchlist, and settings.
"# trading-bot" 
"# trading-bot" 
