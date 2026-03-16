import os
from dotenv import load_dotenv

load_dotenv()

# ── Telegram ───────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

# ── Alert thresholds ───────────────────────────────────────
DEFAULT_PRICE_ALERT_THRESHOLD = float(os.getenv("PRICE_ALERT_THRESHOLD", "3.0"))  # %

# ── Scheduler intervals (minutes) ─────────────────────────
PRICE_CHECK_INTERVAL     = int(os.getenv("PRICE_CHECK_INTERVAL", "5"))
NEWS_CHECK_INTERVAL      = int(os.getenv("NEWS_CHECK_INTERVAL", "30"))
OPPORTUNITY_CHECK_INTERVAL = int(os.getenv("OPPORTUNITY_CHECK_INTERVAL", "60"))

# ── Database ───────────────────────────────────────────────
DB_PATH = os.getenv("DB_PATH", "stock_tracker.db")

# ── Misc ───────────────────────────────────────────────────
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# Keywords that flag a news item as important
IMPORTANT_NEWS_KEYWORDS = [
    "earnings", "beat", "miss", "guidance", "acquisition", "merger",
    "fda", "approval", "lawsuit", "ceo", "layoff", "bankruptcy",
    "dividend", "buyback", "upgrade", "downgrade", "revenue", "profit",
    "loss", "record high", "record low", "crash", "surge", "recall",
    "investigation", "sec", "fine", "penalty", "deal", "partnership",
    "ipo", "spin-off", "split", "default", "restatement",
]
