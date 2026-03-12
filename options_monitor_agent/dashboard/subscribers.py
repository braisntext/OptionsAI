import os
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
from options_monitor_agent.db_utils import get_conn

_SQLITE_PATH = os.path.join(os.path.dirname(__file__), 'subscribers.db')

try:
    from config import SUPERADMIN_EMAILS
    SUPERUSERS = set(SUPERADMIN_EMAILS)
except ImportError:
    SUPERUSERS = {'braisnatural@gmail.com', 'braisontour@gmail.com'}

# ── Usage limits per plan ─────────────────────────────────────────────────────
LIMITS = {
    'watchlist_max':  25,   # max tickers in watchlist (paid)
    'alerts_max':     20,   # max spike alert configs (paid)
    'ask_agent_max':   5,   # max agent queries per day (paid)
}

FREE_LIMITS = {
    'watchlist_max':   3,
    'alerts_max':      3,
    'ask_agent_max':   0,
}

# ── App access per plan ───────────────────────────────────────────────────────
# Free: Options + Investments only.  Paid apps require monthly/basic+.
FREE_APPS = {'options', 'investments'}
ALL_APPS  = {'options', 'investments', 'fiscal', 'alt_investments'}

def _conn():
    return get_conn(_SQLITE_PATH)

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
                INSERT INTO subscribers
                (email, status, plan, superuser, subscribed_at, expires_at, notes)
                VALUES (?, 'active', 'lifetime', 1, ?, NULL, 'Superuser - lifetime free')
                ON CONFLICT(email) DO NOTHING
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

def add_free_subscriber(email: str):
    """Register a new user on the free plan (no expiry, limited features)."""
    email = email.strip().lower()
    now = datetime.utcnow()
    with _conn() as c:
        existing = c.execute(
            "SELECT id FROM subscribers WHERE email = ? COLLATE NOCASE", (email,)
        ).fetchone()
        if existing:
            return  # Already registered
        c.execute('''
            INSERT INTO subscribers (email, status, plan, superuser, subscribed_at, expires_at)
            VALUES (?, 'active', 'free', 0, ?, NULL)
        ''', (email, now.isoformat()))
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


# ── Superuser check ──────────────────────────────────────────────────────────
def is_superuser(email: str) -> bool:
    if not email:
        return False
    return email.strip().lower() in {e.lower() for e in SUPERUSERS}


# ── Daily usage tracking ─────────────────────────────────────────────────────
def _init_usage_table():
    with _conn() as c:
        c.execute('''
            CREATE TABLE IF NOT EXISTS daily_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL COLLATE NOCASE,
                usage_type TEXT NOT NULL,
                usage_date TEXT NOT NULL,
                count INTEGER NOT NULL DEFAULT 0,
                UNIQUE(email, usage_type, usage_date)
            )
        ''')
        c.commit()

def _init_tokens_table():
    with _conn() as c:
        c.execute('''
            CREATE TABLE IF NOT EXISTS magic_tokens (
                token TEXT PRIMARY KEY,
                email TEXT NOT NULL COLLATE NOCASE,
                expires_at TEXT NOT NULL
            )
        ''')
        c.commit()


def _init_user_watchlists_table():
    with _conn() as c:
        c.execute('''
            CREATE TABLE IF NOT EXISTS user_watchlists (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL COLLATE NOCASE,
                ticker TEXT NOT NULL,
                added_at TEXT NOT NULL,
                UNIQUE(email, ticker)
            )
        ''')
        c.commit()


def _init_user_spike_configs_table():
    with _conn() as c:
        c.execute('''
            CREATE TABLE IF NOT EXISTS user_spike_configs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL COLLATE NOCASE,
                ticker TEXT NOT NULL,
                threshold REAL NOT NULL DEFAULT 25,
                option_type TEXT NOT NULL DEFAULT 'ALL',
                notify_push INTEGER NOT NULL DEFAULT 1,
                notify_email INTEGER NOT NULL DEFAULT 0,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            )
        ''')
        c.commit()


# ── Per-user watchlists ──────────────────────────────────────────────────────
def get_user_watchlist(email: str) -> list:
    """Return list of tickers for this user."""
    email = email.strip().lower()
    with _conn() as c:
        rows = c.execute(
            "SELECT ticker FROM user_watchlists WHERE email = ? COLLATE NOCASE ORDER BY added_at",
            (email,)
        ).fetchall()
    return [r['ticker'] for r in rows]


def add_user_ticker(email: str, ticker: str) -> bool:
    """Add ticker to user's watchlist. Returns True if added, False if exists."""
    email = email.strip().lower()
    try:
        with _conn() as c:
            c.execute(
                "INSERT INTO user_watchlists (email, ticker, added_at) VALUES (?, ?, ?) ON CONFLICT(email, ticker) DO NOTHING",
                (email, ticker.strip().upper(), datetime.utcnow().isoformat())
            )
            c.commit()
            return c.total_changes > 0
    except Exception:
        return False


def remove_user_ticker(email: str, ticker: str) -> bool:
    """Remove ticker from user's watchlist."""
    email = email.strip().lower()
    with _conn() as c:
        c.execute(
            "DELETE FROM user_watchlists WHERE email = ? COLLATE NOCASE AND ticker = ?",
            (email, ticker.strip().upper())
        )
        c.commit()
        return c.total_changes > 0


def get_all_watched_tickers() -> list:
    """Return union of all tickers watched by any user."""
    with _conn() as c:
        rows = c.execute("SELECT DISTINCT ticker FROM user_watchlists").fetchall()
    return [r['ticker'] for r in rows]


def seed_user_watchlist(email: str, tickers: list):
    """Seed a user's watchlist from a list (e.g. on first login)."""
    email = email.strip().lower()
    now = datetime.utcnow().isoformat()
    with _conn() as c:
        for ticker in tickers:
            c.execute(
                "INSERT INTO user_watchlists (email, ticker, added_at) VALUES (?, ?, ?) ON CONFLICT(email, ticker) DO NOTHING",
                (email, ticker.strip().upper(), now)
            )
        c.commit()


def user_has_watchlist(email: str) -> bool:
    """Check if user has any tickers in watchlist."""
    email = email.strip().lower()
    with _conn() as c:
        row = c.execute(
            "SELECT 1 FROM user_watchlists WHERE email = ? COLLATE NOCASE LIMIT 1",
            (email,)
        ).fetchone()
    return row is not None


# ── Per-user spike configs ───────────────────────────────────────────────────
def get_user_spike_configs(email: str) -> list:
    """Return spike configs for this user."""
    email = email.strip().lower()
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM user_spike_configs WHERE email = ? COLLATE NOCASE ORDER BY created_at",
            (email,)
        ).fetchall()
    return [dict(r) for r in rows]


def add_user_spike_config(email: str, ticker: str, threshold: float = 25,
                          option_type: str = 'ALL', notify_push: bool = True,
                          notify_email: bool = False) -> dict:
    """Add a spike config for user. Returns the new config dict."""
    email = email.strip().lower()
    now = datetime.utcnow().isoformat()
    with _conn() as c:
        c.execute(
            '''INSERT INTO user_spike_configs
               (email, ticker, threshold, option_type, notify_push, notify_email, enabled, created_at)
               VALUES (?, ?, ?, ?, ?, ?, 1, ?)''',
            (email, ticker.strip().upper(), threshold, option_type,
             int(notify_push), int(notify_email), now)
        )
        c.commit()
        cfg_id = c.execute("SELECT last_insert_rowid()").fetchone()[0]
    return {
        'id': cfg_id, 'email': email, 'ticker': ticker.strip().upper(),
        'threshold': threshold, 'option_type': option_type,
        'notify_push': bool(notify_push), 'notify_email': bool(notify_email),
        'enabled': True, 'created_at': now,
    }


def delete_user_spike_config(email: str, cfg_id: int) -> bool:
    """Delete a spike config (only if owned by user)."""
    email = email.strip().lower()
    with _conn() as c:
        c.execute(
            "DELETE FROM user_spike_configs WHERE id = ? AND email = ? COLLATE NOCASE",
            (cfg_id, email)
        )
        c.commit()
        return c.total_changes > 0


def toggle_user_spike_config(email: str, cfg_id: int) -> bool:
    """Toggle enabled status (only if owned by user)."""
    email = email.strip().lower()
    with _conn() as c:
        c.execute(
            '''UPDATE user_spike_configs SET enabled = CASE WHEN enabled=1 THEN 0 ELSE 1 END
               WHERE id = ? AND email = ? COLLATE NOCASE''',
            (cfg_id, email)
        )
        c.commit()
        return c.total_changes > 0


def get_all_spike_configs() -> list:
    """Return all enabled spike configs across all users (for scheduler)."""
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM user_spike_configs WHERE enabled = 1 ORDER BY created_at"
        ).fetchall()
    return [dict(r) for r in rows]

# ── Password authentication ──────────────────────────────────────────────────
def set_password(email: str, password: str):
    """Set or update the password for a subscriber."""
    email = email.strip().lower()
    hashed = generate_password_hash(password)
    with _conn() as c:
        c.execute(
            "UPDATE subscribers SET password_hash = ? WHERE email = ? COLLATE NOCASE",
            (hashed, email)
        )
        c.commit()


def verify_password(email: str, password: str) -> bool:
    """Verify email/password credentials. Returns True if valid."""
    email = email.strip().lower()
    with _conn() as c:
        row = c.execute(
            "SELECT password_hash FROM subscribers WHERE email = ? COLLATE NOCASE",
            (email,)
        ).fetchone()
    if not row or not row['password_hash']:
        return False
    return check_password_hash(row['password_hash'], password)


def has_password(email: str) -> bool:
    """Check if user has a password set."""
    email = email.strip().lower()
    with _conn() as c:
        row = c.execute(
            "SELECT password_hash FROM subscribers WHERE email = ? COLLATE NOCASE",
            (email,)
        ).fetchone()
    return bool(row and row['password_hash'])


def store_magic_token(token: str, email: str, expires_at):
    """Persist a magic-link token to the database."""
    with _conn() as c:
        c.execute(
            """INSERT INTO magic_tokens (token, email, expires_at) VALUES (?, ?, ?)
               ON CONFLICT(token) DO UPDATE SET email=excluded.email, expires_at=excluded.expires_at""",
            (token, email.strip().lower(), expires_at.isoformat())
        )
        c.commit()

def consume_magic_token(token: str):
    """Fetch and delete a magic-link token. Returns {'email', 'expires_at'} or None."""
    with _conn() as c:
        row = c.execute("SELECT email, expires_at FROM magic_tokens WHERE token = ?", (token,)).fetchone()
        if not row:
            return None
        c.execute("DELETE FROM magic_tokens WHERE token = ?", (token,))
        # Purge expired tokens while we're here
        c.execute("DELETE FROM magic_tokens WHERE expires_at < ?", (datetime.utcnow().isoformat(),))
        c.commit()
    return {'email': row['email'], 'expires_at': datetime.fromisoformat(row['expires_at'])}

def _init_password_column():
    """Add password_hash column to subscribers table if it doesn't exist."""
    with _conn() as c:
        try:
            c.execute("SELECT password_hash FROM subscribers LIMIT 1")
        except Exception:
            c.execute("ALTER TABLE subscribers ADD COLUMN password_hash TEXT")
            c.commit()

_init_usage_table()
_init_tokens_table()
_init_user_watchlists_table()
_init_user_spike_configs_table()
_init_password_column()


def get_daily_usage(email: str, usage_type: str) -> int:
    """Get usage count for today."""
    today = datetime.utcnow().strftime('%Y-%m-%d')
    with _conn() as c:
        row = c.execute(
            "SELECT count FROM daily_usage WHERE email = ? AND usage_type = ? AND usage_date = ?",
            (email.lower(), usage_type, today)
        ).fetchone()
    return row['count'] if row else 0


def increment_usage(email: str, usage_type: str) -> int:
    """Increment usage count for today. Returns new count."""
    today = datetime.utcnow().strftime('%Y-%m-%d')
    email = email.strip().lower()
    with _conn() as c:
        c.execute('''
            INSERT INTO daily_usage (email, usage_type, usage_date, count)
            VALUES (?, ?, ?, 1)
            ON CONFLICT(email, usage_type, usage_date)
            DO UPDATE SET count = count + 1
        ''', (email, usage_type, today))
        c.commit()
        row = c.execute(
            "SELECT count FROM daily_usage WHERE email = ? AND usage_type = ? AND usage_date = ?",
            (email, usage_type, today)
        ).fetchone()
    return row['count'] if row else 1


def get_user_plan(email: str) -> str:
    """Return the plan name for this user: 'free', 'monthly', 'lifetime', etc."""
    email = email.strip().lower()
    if email in {e.lower() for e in SUPERUSERS}:
        return 'lifetime'
    with _conn() as c:
        row = c.execute(
            "SELECT plan FROM subscribers WHERE email = ? COLLATE NOCASE", (email,)
        ).fetchone()
    return row['plan'] if row else 'free'


def has_app_access(email: str, app_name: str) -> bool:
    """Check if user can access a specific app."""
    if is_superuser(email):
        return True
    plan = get_user_plan(email)
    if plan in ('unlimited', 'lifetime'):
        return True
    if plan == 'free':
        return app_name in FREE_APPS
    # Paid plans (monthly/basic) get all current apps
    if not is_subscribed(email):
        return app_name in FREE_APPS
    return True


def check_limit(email: str, usage_type: str) -> tuple:
    """Check if user is within limits. Returns (allowed: bool, remaining: int, limit: int)."""
    if is_superuser(email):
        return True, 999, 999
    plan = get_user_plan(email)
    limits = FREE_LIMITS if plan == 'free' else LIMITS
    limit = limits.get(usage_type, 999)
    used = get_daily_usage(email, usage_type)
    return used < limit, limit - used, limit


init_db()
