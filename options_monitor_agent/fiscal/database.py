"""
Fiscal database — SQLite storage for imported broker statements and tax data.
Uses the same pattern as subscribers.py (raw sqlite3, per-user data).
"""

import sqlite3
import os
import json
from datetime import datetime

_PERSISTENT_DIR = '/var/data'
_LOCAL_FALLBACK = os.path.join(os.path.dirname(__file__), '..', 'dashboard')
_DB_DIR = _PERSISTENT_DIR if os.path.isdir(_PERSISTENT_DIR) else _LOCAL_FALLBACK
DB_PATH = os.path.join(_DB_DIR, 'fiscal.db')


def _conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA foreign_keys=ON")
    return c


def init_fiscal_db():
    """Create all fiscal tables if they don't exist."""
    with _conn() as c:
        # Uploaded statement metadata
        c.execute('''
            CREATE TABLE IF NOT EXISTS fiscal_statements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL COLLATE NOCASE,
                broker TEXT NOT NULL,
                tax_year INTEGER NOT NULL,
                filename TEXT NOT NULL,
                account_id TEXT,
                base_currency TEXT DEFAULT 'EUR',
                uploaded_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'processing',
                error_message TEXT,
                UNIQUE(email, broker, tax_year, account_id)
            )
        ''')

        # Normalized trades (stocks, options, other instruments)
        c.execute('''
            CREATE TABLE IF NOT EXISTS fiscal_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                statement_id INTEGER NOT NULL,
                asset_category TEXT NOT NULL,
                currency TEXT NOT NULL,
                symbol TEXT NOT NULL,
                description TEXT,
                trade_date TEXT NOT NULL,
                quantity REAL NOT NULL,
                trade_price REAL NOT NULL,
                proceeds REAL NOT NULL,
                commission REAL NOT NULL DEFAULT 0,
                basis REAL NOT NULL DEFAULT 0,
                realized_pl REAL NOT NULL DEFAULT 0,
                code TEXT,
                multiplier REAL NOT NULL DEFAULT 1,
                underlying TEXT,
                expiry TEXT,
                strike REAL,
                option_type TEXT,
                proceeds_eur REAL,
                commission_eur REAL,
                basis_eur REAL,
                realized_pl_eur REAL,
                exchange_rate REAL,
                FOREIGN KEY (statement_id) REFERENCES fiscal_statements(id) ON DELETE CASCADE
            )
        ''')
        c.execute('CREATE INDEX IF NOT EXISTS idx_ft_stmt ON fiscal_trades(statement_id)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_ft_cat ON fiscal_trades(asset_category)')

        # Dividends
        c.execute('''
            CREATE TABLE IF NOT EXISTS fiscal_dividends (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                statement_id INTEGER NOT NULL,
                currency TEXT NOT NULL,
                pay_date TEXT NOT NULL,
                symbol TEXT NOT NULL,
                description TEXT,
                gross_amount REAL NOT NULL,
                gross_amount_eur REAL,
                is_in_lieu INTEGER NOT NULL DEFAULT 0,
                exchange_rate REAL,
                FOREIGN KEY (statement_id) REFERENCES fiscal_statements(id) ON DELETE CASCADE
            )
        ''')

        # Interest income
        c.execute('''
            CREATE TABLE IF NOT EXISTS fiscal_interest (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                statement_id INTEGER NOT NULL,
                currency TEXT NOT NULL,
                pay_date TEXT NOT NULL,
                description TEXT,
                amount REAL NOT NULL,
                amount_eur REAL,
                exchange_rate REAL,
                FOREIGN KEY (statement_id) REFERENCES fiscal_statements(id) ON DELETE CASCADE
            )
        ''')

        # Withholding taxes
        c.execute('''
            CREATE TABLE IF NOT EXISTS fiscal_withholdings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                statement_id INTEGER NOT NULL,
                currency TEXT NOT NULL,
                pay_date TEXT NOT NULL,
                symbol TEXT,
                description TEXT,
                amount REAL NOT NULL,
                amount_eur REAL,
                tax_type TEXT,
                country TEXT,
                exchange_rate REAL,
                FOREIGN KEY (statement_id) REFERENCES fiscal_statements(id) ON DELETE CASCADE
            )
        ''')

        # Forex transactions
        c.execute('''
            CREATE TABLE IF NOT EXISTS fiscal_forex (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                statement_id INTEGER NOT NULL,
                currency TEXT NOT NULL,
                symbol TEXT NOT NULL,
                trade_date TEXT NOT NULL,
                quantity REAL NOT NULL,
                trade_price REAL NOT NULL,
                proceeds REAL NOT NULL,
                proceeds_eur REAL,
                commission_eur REAL NOT NULL DEFAULT 0,
                mtm_eur REAL,
                code TEXT,
                is_auto_fx INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (statement_id) REFERENCES fiscal_statements(id) ON DELETE CASCADE
            )
        ''')

        # Open positions snapshot (informational)
        c.execute('''
            CREATE TABLE IF NOT EXISTS fiscal_positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                statement_id INTEGER NOT NULL,
                asset_category TEXT NOT NULL,
                currency TEXT NOT NULL,
                symbol TEXT NOT NULL,
                quantity REAL NOT NULL,
                cost_price REAL,
                cost_basis REAL,
                close_price REAL,
                market_value REAL,
                unrealized_pl REAL,
                cost_basis_eur REAL,
                market_value_eur REAL,
                unrealized_pl_eur REAL,
                FOREIGN KEY (statement_id) REFERENCES fiscal_statements(id) ON DELETE CASCADE
            )
        ''')

        # Calculated tax results per casilla
        c.execute('''
            CREATE TABLE IF NOT EXISTS fiscal_tax_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                statement_id INTEGER NOT NULL,
                casilla TEXT NOT NULL,
                category TEXT NOT NULL,
                description TEXT,
                amount_eur REAL NOT NULL,
                details TEXT,
                FOREIGN KEY (statement_id) REFERENCES fiscal_statements(id) ON DELETE CASCADE
            )
        ''')

        # Cached ECB exchange rates
        c.execute('''
            CREATE TABLE IF NOT EXISTS exchange_rates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                rate_date TEXT NOT NULL,
                currency TEXT NOT NULL,
                rate REAL NOT NULL,
                source TEXT DEFAULT 'ECB',
                UNIQUE(rate_date, currency)
            )
        ''')

        c.commit()


# ── Statement CRUD ───────────────────────────────────────────────────────────

def create_statement(email, broker, tax_year, filename, account_id=None,
                     base_currency='EUR'):
    """Create a statement record. Returns statement_id."""
    now = datetime.utcnow().isoformat()
    with _conn() as c:
        # Delete existing data for same broker/year/account (re-upload)
        existing = c.execute(
            '''SELECT id FROM fiscal_statements
               WHERE email = ? AND broker = ? AND tax_year = ? AND account_id = ?''',
            (email.lower(), broker, tax_year, account_id or '')
        ).fetchone()
        if existing:
            c.execute('DELETE FROM fiscal_statements WHERE id = ?', (existing['id'],))

        c.execute(
            '''INSERT INTO fiscal_statements
               (email, broker, tax_year, filename, account_id, base_currency, uploaded_at, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'processing')''',
            (email.lower(), broker, tax_year, filename, account_id or '', base_currency, now)
        )
        c.commit()
        stmt_id = c.execute("SELECT last_insert_rowid()").fetchone()[0]
    return stmt_id


def update_statement_status(stmt_id, status, error_message=None):
    with _conn() as c:
        c.execute(
            'UPDATE fiscal_statements SET status = ?, error_message = ? WHERE id = ?',
            (status, error_message, stmt_id)
        )
        c.commit()


def get_user_statements(email):
    """Get all statements for a user."""
    with _conn() as c:
        rows = c.execute(
            '''SELECT * FROM fiscal_statements WHERE email = ? COLLATE NOCASE
               ORDER BY tax_year DESC, uploaded_at DESC''',
            (email.lower(),)
        ).fetchall()
    return [dict(r) for r in rows]


def get_statement(stmt_id, email=None):
    """Get a single statement, optionally verifying ownership."""
    with _conn() as c:
        if email:
            row = c.execute(
                'SELECT * FROM fiscal_statements WHERE id = ? AND email = ? COLLATE NOCASE',
                (stmt_id, email.lower())
            ).fetchone()
        else:
            row = c.execute(
                'SELECT * FROM fiscal_statements WHERE id = ?', (stmt_id,)
            ).fetchone()
    return dict(row) if row else None


# ── Bulk insert helpers ──────────────────────────────────────────────────────

def insert_trades(stmt_id, trades):
    """Insert a list of trade dicts."""
    with _conn() as c:
        for t in trades:
            c.execute(
                '''INSERT INTO fiscal_trades
                   (statement_id, asset_category, currency, symbol, description,
                    trade_date, quantity, trade_price, proceeds, commission, basis,
                    realized_pl, code, multiplier, underlying, expiry, strike,
                    option_type, proceeds_eur, commission_eur, basis_eur,
                    realized_pl_eur, exchange_rate)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (stmt_id, t['asset_category'], t['currency'], t['symbol'],
                 t.get('description'), t['trade_date'], t['quantity'],
                 t['trade_price'], t['proceeds'], t.get('commission', 0),
                 t.get('basis', 0), t.get('realized_pl', 0), t.get('code'),
                 t.get('multiplier', 1), t.get('underlying'), t.get('expiry'),
                 t.get('strike'), t.get('option_type'),
                 t.get('proceeds_eur'), t.get('commission_eur'),
                 t.get('basis_eur'), t.get('realized_pl_eur'),
                 t.get('exchange_rate'))
            )
        c.commit()


def insert_dividends(stmt_id, dividends):
    with _conn() as c:
        for d in dividends:
            c.execute(
                '''INSERT INTO fiscal_dividends
                   (statement_id, currency, pay_date, symbol, description,
                    gross_amount, gross_amount_eur, is_in_lieu, exchange_rate)
                   VALUES (?,?,?,?,?,?,?,?,?)''',
                (stmt_id, d['currency'], d['pay_date'], d['symbol'],
                 d.get('description'), d['gross_amount'],
                 d.get('gross_amount_eur'), d.get('is_in_lieu', 0),
                 d.get('exchange_rate'))
            )
        c.commit()


def insert_interest(stmt_id, interest_records):
    with _conn() as c:
        for i in interest_records:
            c.execute(
                '''INSERT INTO fiscal_interest
                   (statement_id, currency, pay_date, description, amount,
                    amount_eur, exchange_rate)
                   VALUES (?,?,?,?,?,?,?)''',
                (stmt_id, i['currency'], i['pay_date'], i.get('description'),
                 i['amount'], i.get('amount_eur'), i.get('exchange_rate'))
            )
        c.commit()


def insert_withholdings(stmt_id, withholdings):
    with _conn() as c:
        for w in withholdings:
            c.execute(
                '''INSERT INTO fiscal_withholdings
                   (statement_id, currency, pay_date, symbol, description,
                    amount, amount_eur, tax_type, country, exchange_rate)
                   VALUES (?,?,?,?,?,?,?,?,?,?)''',
                (stmt_id, w['currency'], w['pay_date'], w.get('symbol'),
                 w.get('description'), w['amount'], w.get('amount_eur'),
                 w.get('tax_type'), w.get('country'), w.get('exchange_rate'))
            )
        c.commit()


def insert_forex(stmt_id, forex_records):
    with _conn() as c:
        for f in forex_records:
            c.execute(
                '''INSERT INTO fiscal_forex
                   (statement_id, currency, symbol, trade_date, quantity,
                    trade_price, proceeds, proceeds_eur, commission_eur,
                    mtm_eur, code, is_auto_fx)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
                (stmt_id, f['currency'], f['symbol'], f['trade_date'],
                 f['quantity'], f['trade_price'], f['proceeds'],
                 f.get('proceeds_eur'), f.get('commission_eur', 0),
                 f.get('mtm_eur'), f.get('code'),
                 f.get('is_auto_fx', 0))
            )
        c.commit()


def insert_positions(stmt_id, positions):
    with _conn() as c:
        for p in positions:
            c.execute(
                '''INSERT INTO fiscal_positions
                   (statement_id, asset_category, currency, symbol, quantity,
                    cost_price, cost_basis, close_price, market_value,
                    unrealized_pl, cost_basis_eur, market_value_eur, unrealized_pl_eur)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (stmt_id, p['asset_category'], p['currency'], p['symbol'],
                 p['quantity'], p.get('cost_price'), p.get('cost_basis'),
                 p.get('close_price'), p.get('market_value'),
                 p.get('unrealized_pl'), p.get('cost_basis_eur'),
                 p.get('market_value_eur'), p.get('unrealized_pl_eur'))
            )
        c.commit()


def insert_tax_results(stmt_id, results):
    """Insert calculated tax results. Clears previous results first."""
    with _conn() as c:
        c.execute('DELETE FROM fiscal_tax_results WHERE statement_id = ?', (stmt_id,))
        for r in results:
            c.execute(
                '''INSERT INTO fiscal_tax_results
                   (statement_id, casilla, category, description, amount_eur, details)
                   VALUES (?,?,?,?,?,?)''',
                (stmt_id, r['casilla'], r['category'], r.get('description'),
                 r['amount_eur'], json.dumps(r.get('details', {}), ensure_ascii=False))
            )
        c.commit()


# ── Query helpers ────────────────────────────────────────────────────────────

def get_trades(stmt_id, asset_category=None):
    with _conn() as c:
        if asset_category:
            rows = c.execute(
                'SELECT * FROM fiscal_trades WHERE statement_id = ? AND asset_category = ? ORDER BY trade_date',
                (stmt_id, asset_category)
            ).fetchall()
        else:
            rows = c.execute(
                'SELECT * FROM fiscal_trades WHERE statement_id = ? ORDER BY trade_date',
                (stmt_id,)
            ).fetchall()
    return [dict(r) for r in rows]


def get_dividends(stmt_id):
    with _conn() as c:
        rows = c.execute(
            'SELECT * FROM fiscal_dividends WHERE statement_id = ? ORDER BY pay_date',
            (stmt_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_interest(stmt_id):
    with _conn() as c:
        rows = c.execute(
            'SELECT * FROM fiscal_interest WHERE statement_id = ? ORDER BY pay_date',
            (stmt_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_withholdings(stmt_id):
    with _conn() as c:
        rows = c.execute(
            'SELECT * FROM fiscal_withholdings WHERE statement_id = ? ORDER BY pay_date',
            (stmt_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_forex(stmt_id):
    with _conn() as c:
        rows = c.execute(
            'SELECT * FROM fiscal_forex WHERE statement_id = ? ORDER BY trade_date',
            (stmt_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_positions(stmt_id):
    with _conn() as c:
        rows = c.execute(
            'SELECT * FROM fiscal_positions WHERE statement_id = ? ORDER BY symbol',
            (stmt_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_tax_results(stmt_id):
    with _conn() as c:
        rows = c.execute(
            'SELECT * FROM fiscal_tax_results WHERE statement_id = ? ORDER BY casilla',
            (stmt_id,)
        ).fetchall()
    return [dict(r) for r in rows]


# ── Exchange rates cache ─────────────────────────────────────────────────────

def get_cached_rate(rate_date, currency):
    """Get cached exchange rate. Returns float or None."""
    with _conn() as c:
        row = c.execute(
            'SELECT rate FROM exchange_rates WHERE rate_date = ? AND currency = ?',
            (rate_date, currency)
        ).fetchone()
    return row['rate'] if row else None


def cache_rate(rate_date, currency, rate, source='ECB'):
    with _conn() as c:
        c.execute(
            '''INSERT OR REPLACE INTO exchange_rates (rate_date, currency, rate, source)
               VALUES (?, ?, ?, ?)''',
            (rate_date, currency, rate, source)
        )
        c.commit()


def get_cached_rates_bulk(currency, start_date=None, end_date=None):
    """Get all cached rates for a currency in a date range."""
    with _conn() as c:
        if start_date and end_date:
            rows = c.execute(
                '''SELECT rate_date, rate FROM exchange_rates
                   WHERE currency = ? AND rate_date BETWEEN ? AND ?
                   ORDER BY rate_date''',
                (currency, start_date, end_date)
            ).fetchall()
        else:
            rows = c.execute(
                'SELECT rate_date, rate FROM exchange_rates WHERE currency = ? ORDER BY rate_date',
                (currency,)
            ).fetchall()
    return {r['rate_date']: r['rate'] for r in rows}


# ── Cross-statement query helpers ────────────────────────────────────────────

def get_user_statement_ids(email, tax_year):
    """Get all completed statement IDs for a user+year."""
    with _conn() as c:
        rows = c.execute(
            '''SELECT id FROM fiscal_statements
               WHERE email = ? COLLATE NOCASE AND tax_year = ? AND status = 'completed'
               ORDER BY broker, account_id''',
            (email.lower(), tax_year)
        ).fetchall()
    return [r['id'] for r in rows]


def get_user_years(email):
    """Get all tax years with statements, grouped with metadata."""
    with _conn() as c:
        rows = c.execute(
            '''SELECT id, broker, tax_year, account_id, filename, uploaded_at, status
               FROM fiscal_statements
               WHERE email = ? COLLATE NOCASE
               ORDER BY tax_year DESC, broker, account_id''',
            (email.lower(),)
        ).fetchall()
    years = {}
    for r in rows:
        yr = r['tax_year']
        if yr not in years:
            years[yr] = []
        years[yr].append(dict(r))
    return [{'tax_year': yr, 'statements': stmts} for yr, stmts in sorted(years.items(), reverse=True)]


def get_tax_results_multi(stmt_ids):
    """Get tax results across multiple statements."""
    if not stmt_ids:
        return []
    placeholders = ','.join('?' * len(stmt_ids))
    with _conn() as c:
        rows = c.execute(
            f'SELECT * FROM fiscal_tax_results WHERE statement_id IN ({placeholders}) ORDER BY casilla',
            stmt_ids
        ).fetchall()
    return [dict(r) for r in rows]


def get_trades_multi(stmt_ids, asset_category=None):
    """Get trades across multiple statements."""
    if not stmt_ids:
        return []
    placeholders = ','.join('?' * len(stmt_ids))
    params = list(stmt_ids)
    sql = f'''SELECT t.*, s.broker FROM fiscal_trades t
              JOIN fiscal_statements s ON t.statement_id = s.id
              WHERE t.statement_id IN ({placeholders})'''
    if asset_category:
        sql += ' AND t.asset_category = ?'
        params.append(asset_category)
    sql += ' ORDER BY t.trade_date'
    with _conn() as c:
        rows = c.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def get_dividends_multi(stmt_ids):
    """Get dividends across multiple statements."""
    if not stmt_ids:
        return []
    placeholders = ','.join('?' * len(stmt_ids))
    with _conn() as c:
        rows = c.execute(
            f'''SELECT d.*, s.broker FROM fiscal_dividends d
                JOIN fiscal_statements s ON d.statement_id = s.id
                WHERE d.statement_id IN ({placeholders}) ORDER BY d.pay_date''',
            stmt_ids
        ).fetchall()
    return [dict(r) for r in rows]


def get_interest_multi(stmt_ids):
    """Get interest across multiple statements."""
    if not stmt_ids:
        return []
    placeholders = ','.join('?' * len(stmt_ids))
    with _conn() as c:
        rows = c.execute(
            f'''SELECT i.*, s.broker FROM fiscal_interest i
                JOIN fiscal_statements s ON i.statement_id = s.id
                WHERE i.statement_id IN ({placeholders}) ORDER BY i.pay_date''',
            stmt_ids
        ).fetchall()
    return [dict(r) for r in rows]


def get_withholdings_multi(stmt_ids):
    """Get withholdings across multiple statements."""
    if not stmt_ids:
        return []
    placeholders = ','.join('?' * len(stmt_ids))
    with _conn() as c:
        rows = c.execute(
            f'''SELECT w.*, s.broker FROM fiscal_withholdings w
                JOIN fiscal_statements s ON w.statement_id = s.id
                WHERE w.statement_id IN ({placeholders}) ORDER BY w.pay_date''',
            stmt_ids
        ).fetchall()
    return [dict(r) for r in rows]


# Initialize on import
init_fiscal_db()
