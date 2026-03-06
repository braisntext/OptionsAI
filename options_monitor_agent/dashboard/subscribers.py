import sqlite3
import os
from datetime import datetime, timedelta

DB_PATH = os.path.join(os.path.dirname(__file__), 'subscribers.db')

SUPERUSERS = {'braisnatural@gmail.com', 'braisontour@gmail.com'}

def _conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c

def init_db():
    with _conn() as c:
        c.execute('''
            CREATE TABLE IF NOT EXISTS subscribers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL COLLATE NOCASE,
                status TEXT NOT NULL DEFAULT 'active',
                plan TEXT NOT NULL DEFAULT 'monthly',
                superuser INTEGER NOT NULL DEFAULT 0,
                subscribed_at TEXT NOT NULL,
                expires_at TEXT,
                stripe_customer_id TEXT,
                stripe_subscription_id TEXT,
                notes TEXT
            )
        ''')
        c.execute('''
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL COLLATE NOCASE,
                amount_eur REAL NOT NULL,
                method TEXT NOT NULL,
                reference TEXT,
                paid_at TEXT NOT NULL,
                months INTEGER NOT NULL DEFAULT 1
            )
        ''')
        # Seed superuser
        for email in SUPERUSERS:
            c.execute('''
                INSERT OR IGNORE INTO subscribers
                (email, status, plan, superuser, subscribed_at, expires_at, notes)
                VALUES (?, 'active', 'lifetime', 1, ?, NULL, 'Superuser - lifetime free')
            ''', (email, datetime.utcnow().isoformat()))
        c.commit()

def is_subscribed(email: str) -> bool:
    """Return True if this email has an active subscription (or is superuser)."""
    email = email.strip().lower()
    if email in {e.lower() for e in SUPERUSERS}:
        return True
    with _conn() as c:
        row = c.execute(
            "SELECT status, expires_at, superuser FROM subscribers WHERE email = ? COLLATE NOCASE",
            (email,)
        ).fetchone()
    if not row:
        return False
    if row['superuser']:
        return True
    if row['status'] != 'active':
        return False
    if row['expires_at'] is None:
        return True  # lifetime
    return datetime.utcnow() < datetime.fromisoformat(row['expires_at'])

def get_subscriber(email: str):
    email = email.strip().lower()
    with _conn() as c:
        return c.execute(
            "SELECT * FROM subscribers WHERE email = ? COLLATE NOCASE", (email,)
        ).fetchone()

def add_subscriber(email: str, months: int = 1, method: str = 'manual',
                   reference: str = None, amount: float = 0.95):
    email = email.strip().lower()
    now = datetime.utcnow()
    with _conn() as c:
        existing = c.execute(
            "SELECT expires_at FROM subscribers WHERE email = ? COLLATE NOCASE", (email,)
        ).fetchone()
        if existing and existing['expires_at']:
            base = max(datetime.fromisoformat(existing['expires_at']), now)
        else:
            base = now
        expires = (base + timedelta(days=30 * months)).isoformat()
        c.execute('''
            INSERT INTO subscribers (email, status, plan, superuser, subscribed_at, expires_at)
            VALUES (?, 'active', 'monthly', 0, ?, ?)
            ON CONFLICT(email) DO UPDATE SET
                status='active', expires_at=excluded.expires_at
        ''', (email, now.isoformat(), expires))
        c.execute('''
            INSERT INTO payments (email, amount_eur, method, reference, paid_at, months)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (email, amount * months, method, reference, now.isoformat(), months))
        c.commit()

def cancel_subscriber(email: str):
    email = email.strip().lower()
    with _conn() as c:
        c.execute("UPDATE subscribers SET status='cancelled' WHERE email = ? COLLATE NOCASE", (email,))
        c.commit()

def list_subscribers():
    with _conn() as c:
        return c.execute("SELECT * FROM subscribers ORDER BY subscribed_at DESC").fetchall()

def list_payments():
    with _conn() as c:
        return c.execute("SELECT * FROM payments ORDER BY paid_at DESC").fetchall()

init_db()
