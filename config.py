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

# ── FinBERT model ──────────────────────────────────────────
FINBERT_MODEL = os.getenv("FINBERT_MODEL", "ProsusAI/finbert")

# ── Long-term scoring thresholds ───────────────────────────
LONGTERM_STRONG_HOLD_THRESHOLD = int(os.getenv("LONGTERM_STRONG_HOLD_THRESHOLD", "75"))
LONGTERM_HOLD_THRESHOLD        = int(os.getenv("LONGTERM_HOLD_THRESHOLD", "60"))
LONGTERM_WATCH_THRESHOLD       = int(os.getenv("LONGTERM_WATCH_THRESHOLD", "45"))

# ── Sentiment alert thresholds ─────────────────────────────
SENTIMENT_FLIP_THRESHOLD            = int(os.getenv("SENTIMENT_FLIP_THRESHOLD", "15"))
HIGH_IMPACT_NEGATIVE_CONFIDENCE     = float(os.getenv("HIGH_IMPACT_NEGATIVE_CONFIDENCE", "0.92"))

# ── New scheduler intervals ────────────────────────────────
FUNDAMENTAL_SENTIMENT_CHECK_INTERVAL = int(os.getenv("FUNDAMENTAL_SENTIMENT_CHECK_INTERVAL", "360"))  # minutes (6 hours)
WEEKLY_DIGEST_DAY                    = os.getenv("WEEKLY_DIGEST_DAY", "sun")
WEEKLY_DIGEST_HOUR                   = int(os.getenv("WEEKLY_DIGEST_HOUR", "9"))
