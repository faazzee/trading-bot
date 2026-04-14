"""
database.py — All SQLite operations for the Stock Tracker Bot.

Tables
------
portfolio      – user's owned stocks (with shares / avg price)
watchlist      – stocks the user monitors but doesn't own
price_snapshots– rolling price history for change detection
user_settings  – per-user alert config
sent_alerts    – dedup table so we don't spam alerts
sent_news      – dedup table for news items already sent
"""

import json
import sqlite3
from config import DB_PATH


# ── Connection helper ──────────────────────────────────────

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ── Schema creation ────────────────────────────────────────

def init_db():
    conn = get_connection()
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS portfolio (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL,
            symbol      TEXT    NOT NULL,
            shares      REAL    DEFAULT 0,
            avg_price   REAL    DEFAULT 0,
            added_date  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, symbol)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS watchlist (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL,
            symbol      TEXT    NOT NULL,
            added_date  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, symbol)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS price_snapshots (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol      TEXT    NOT NULL,
            price       REAL    NOT NULL,
            recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS user_settings (
            user_id               INTEGER PRIMARY KEY,
            alert_threshold       REAL    DEFAULT 3.0,
            news_alerts           INTEGER DEFAULT 1,
            opportunity_alerts    INTEGER DEFAULT 1,
            notifications_enabled INTEGER DEFAULT 1
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS sent_alerts (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL,
            symbol     TEXT    NOT NULL,
            alert_type TEXT    NOT NULL,
            sent_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS sent_news (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol   TEXT NOT NULL,
            news_url TEXT NOT NULL,
            sent_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(symbol, news_url)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS fundamental_snapshots (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol        TEXT    NOT NULL,
            snapshot_data TEXT    NOT NULL,
            score         REAL    NOT NULL,
            recorded_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS sentiment_history (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol      TEXT NOT NULL,
            score       REAL NOT NULL,
            label       TEXT NOT NULL,
            recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS weekly_digest_log (
            user_id INTEGER NOT NULL,
            symbol  TEXT    NOT NULL,
            sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, symbol)
        )
    """)

    # Index for faster lookups
    c.execute("CREATE INDEX IF NOT EXISTS idx_price_symbol ON price_snapshots(symbol, recorded_at)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_alert_user   ON sent_alerts(user_id, symbol, alert_type, sent_at)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_fundamental_symbol ON fundamental_snapshots(symbol, recorded_at)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_sentiment_symbol   ON sentiment_history(symbol, recorded_at)")

    conn.commit()
    conn.close()


# ── Portfolio ──────────────────────────────────────────────

def add_to_portfolio(user_id: int, symbol: str, shares: float = 0, avg_price: float = 0) -> bool:
    conn = get_connection()
    try:
        conn.execute(
            """INSERT INTO portfolio (user_id, symbol, shares, avg_price)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(user_id, symbol)
               DO UPDATE SET shares=excluded.shares, avg_price=excluded.avg_price""",
            (user_id, symbol.upper(), shares, avg_price)
        )
        conn.commit()
        return True
    except Exception:
        return False
    finally:
        conn.close()


def remove_from_portfolio(user_id: int, symbol: str):
    conn = get_connection()
    conn.execute("DELETE FROM portfolio WHERE user_id=? AND symbol=?", (user_id, symbol.upper()))
    conn.commit()
    conn.close()


def get_portfolio(user_id: int) -> list:
    conn = get_connection()
    rows = conn.execute(
        "SELECT symbol, shares, avg_price, added_date FROM portfolio WHERE user_id=? ORDER BY symbol",
        (user_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def is_in_portfolio(user_id: int, symbol: str) -> bool:
    conn = get_connection()
    row = conn.execute(
        "SELECT id FROM portfolio WHERE user_id=? AND symbol=?", (user_id, symbol.upper())
    ).fetchone()
    conn.close()
    return row is not None


# ── Watchlist ──────────────────────────────────────────────

def add_to_watchlist(user_id: int, symbol: str) -> bool:
    conn = get_connection()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO watchlist (user_id, symbol) VALUES (?, ?)",
            (user_id, symbol.upper())
        )
        conn.commit()
        return True
    except Exception:
        return False
    finally:
        conn.close()


def remove_from_watchlist(user_id: int, symbol: str):
    conn = get_connection()
    conn.execute("DELETE FROM watchlist WHERE user_id=? AND symbol=?", (user_id, symbol.upper()))
    conn.commit()
    conn.close()


def get_watchlist(user_id: int) -> list:
    conn = get_connection()
    rows = conn.execute(
        "SELECT symbol, added_date FROM watchlist WHERE user_id=? ORDER BY symbol",
        (user_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def is_in_watchlist(user_id: int, symbol: str) -> bool:
    conn = get_connection()
    row = conn.execute(
        "SELECT id FROM watchlist WHERE user_id=? AND symbol=?", (user_id, symbol.upper())
    ).fetchone()
    conn.close()
    return row is not None


# ── Cross-user helpers ─────────────────────────────────────

def get_all_tracked_symbols() -> list:
    """All unique symbols across every user's portfolio + watchlist."""
    conn = get_connection()
    p = conn.execute("SELECT DISTINCT symbol FROM portfolio").fetchall()
    w = conn.execute("SELECT DISTINCT symbol FROM watchlist").fetchall()
    conn.close()
    return list({r["symbol"] for r in p + w})


def get_users_tracking_symbol(symbol: str) -> list:
    """All user IDs that have this symbol in portfolio or watchlist."""
    conn = get_connection()
    p = conn.execute("SELECT DISTINCT user_id FROM portfolio WHERE symbol=?", (symbol,)).fetchall()
    w = conn.execute("SELECT DISTINCT user_id FROM watchlist WHERE symbol=?", (symbol,)).fetchall()
    conn.close()
    return list({r["user_id"] for r in p + w})


# ── User settings ──────────────────────────────────────────

def get_user_settings(user_id: int) -> dict:
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM user_settings WHERE user_id=?", (user_id,)
    ).fetchone()
    conn.close()
    if not row:
        return {
            "alert_threshold": 3.0,
            "news_alerts": 1,
            "opportunity_alerts": 1,
            "notifications_enabled": 1,
        }
    return dict(row)


def update_user_settings(user_id: int, **kwargs):
    conn = get_connection()
    conn.execute("INSERT OR IGNORE INTO user_settings (user_id) VALUES (?)", (user_id,))
    for key, val in kwargs.items():
        conn.execute(f"UPDATE user_settings SET {key}=? WHERE user_id=?", (val, user_id))
    conn.commit()
    conn.close()


# ── Price snapshots ────────────────────────────────────────

def save_price_snapshot(symbol: str, price: float):
    conn = get_connection()
    conn.execute(
        "INSERT INTO price_snapshots (symbol, price) VALUES (?, ?)",
        (symbol.upper(), price)
    )
    # Keep only last 200 rows per symbol to prevent unbounded growth
    conn.execute(
        """DELETE FROM price_snapshots WHERE symbol=? AND id NOT IN (
               SELECT id FROM price_snapshots WHERE symbol=?
               ORDER BY recorded_at DESC LIMIT 200
           )""",
        (symbol.upper(), symbol.upper())
    )
    conn.commit()
    conn.close()


def get_last_price_snapshot(symbol: str):
    """Returns (price, recorded_at) or None."""
    conn = get_connection()
    row = conn.execute(
        "SELECT price, recorded_at FROM price_snapshots WHERE symbol=? ORDER BY recorded_at DESC LIMIT 1",
        (symbol.upper(),)
    ).fetchone()
    conn.close()
    return (row["price"], row["recorded_at"]) if row else None


# ── Alert deduplication ────────────────────────────────────

def was_alert_sent_recently(user_id: int, symbol: str, alert_type: str, hours: int = 1) -> bool:
    conn = get_connection()
    row = conn.execute(
        """SELECT id FROM sent_alerts
           WHERE user_id=? AND symbol=? AND alert_type=?
             AND sent_at > datetime('now', ?)""",
        (user_id, symbol, alert_type, f"-{hours} hours")
    ).fetchone()
    conn.close()
    return row is not None


def record_sent_alert(user_id: int, symbol: str, alert_type: str):
    conn = get_connection()
    conn.execute(
        "INSERT INTO sent_alerts (user_id, symbol, alert_type) VALUES (?, ?, ?)",
        (user_id, symbol, alert_type)
    )
    conn.commit()
    conn.close()


def was_news_sent(symbol: str, news_url: str) -> bool:
    conn = get_connection()
    row = conn.execute(
        "SELECT id FROM sent_news WHERE symbol=? AND news_url=?",
        (symbol, news_url)
    ).fetchone()
    conn.close()
    return row is not None


def record_sent_news(symbol: str, news_url: str):
    conn = get_connection()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO sent_news (symbol, news_url) VALUES (?, ?)",
            (symbol, news_url)
        )
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()


# ── Fundamental snapshots ──────────────────────────────────

def save_fundamental_snapshot(symbol: str, data_dict: dict, score: float):
    """Store a fundamental data snapshot for a symbol."""
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO fundamental_snapshots (symbol, snapshot_data, score) VALUES (?, ?, ?)",
            (symbol.upper(), json.dumps(data_dict), score)
        )
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()


def get_last_fundamental_snapshot(symbol: str) -> dict:
    """Return the most recent fundamental snapshot for a symbol, or empty dict."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT snapshot_data, score, recorded_at FROM fundamental_snapshots WHERE symbol=? ORDER BY recorded_at DESC LIMIT 1",
            (symbol.upper(),)
        ).fetchone()
        if not row:
            return {}
        return {
            "data": json.loads(row["snapshot_data"]),
            "score": row["score"],
            "recorded_at": row["recorded_at"],
        }
    except Exception:
        return {}
    finally:
        conn.close()


# ── Sentiment history ──────────────────────────────────────

def save_sentiment_score(symbol: str, score: float, label: str):
    """Store a daily sentiment score for a symbol."""
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO sentiment_history (symbol, score, label) VALUES (?, ?, ?)",
            (symbol.upper(), score, label)
        )
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()


def get_sentiment_history(symbol: str, days: int = 30) -> list:
    """Return sentiment score rows for the last N days."""
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT score, label, recorded_at FROM sentiment_history
               WHERE symbol=? AND recorded_at > datetime('now', ?)
               ORDER BY recorded_at ASC""",
            (symbol.upper(), f"-{days} days")
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []
    finally:
        conn.close()


# ── Weekly digest log ─────────────────────────────────────

def was_weekly_digest_sent(user_id: int, symbol: str, within_hours: int = 168) -> bool:
    """Return True if a weekly digest was sent for this user+symbol within the given hours (default 7 days)."""
    conn = get_connection()
    try:
        row = conn.execute(
            """SELECT user_id FROM weekly_digest_log
               WHERE user_id=? AND symbol=? AND sent_at > datetime('now', ?)""",
            (user_id, symbol.upper(), f"-{within_hours} hours")
        ).fetchone()
        return row is not None
    except Exception:
        return False
    finally:
        conn.close()


def record_weekly_digest_sent(user_id: int, symbol: str):
    """Record that a weekly digest was sent for this user+symbol."""
    conn = get_connection()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO weekly_digest_log (user_id, symbol, sent_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
            (user_id, symbol.upper())
        )
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()
