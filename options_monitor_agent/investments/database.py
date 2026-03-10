"""
Investments database — SQLite storage for portfolio, transactions, FIFO lots.
Same pattern as fiscal/database.py (raw sqlite3, per-user data keyed by email).
"""

import os
import threading
from datetime import datetime
from options_monitor_agent.db_utils import get_conn

_SQLITE_PATH = os.path.join(os.path.dirname(__file__), '..', 'dashboard', 'investments.db')


def _conn():
    return get_conn(_SQLITE_PATH)


# Thread-local connection for batch operations
_local = threading.local()


def get_shared_conn():
    """Get a thread-local shared connection for batch use."""
    c = getattr(_local, 'conn', None)
    if c is None:
        c = _conn()
        _local.conn = c
    return c


def close_shared_conn():
    """Close and discard the thread-local shared connection."""
    c = getattr(_local, 'conn', None)
    if c is not None:
        try:
            c.close()
        except Exception:
            pass
        _local.conn = None


def init_investments_db():
    """Create all investment tables if they don't exist."""
    with _conn() as c:
        c.execute('''
            CREATE TABLE IF NOT EXISTS investment_accounts (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                email        TEXT    NOT NULL COLLATE NOCASE,
                broker       TEXT    NOT NULL,
                account_name TEXT    NOT NULL DEFAULT '',
                created_at   TEXT    NOT NULL,
                UNIQUE(email, broker, account_name)
            )
        ''')
        c.execute('CREATE INDEX IF NOT EXISTS idx_ia_email ON investment_accounts(email)')

        c.execute('''
            CREATE TABLE IF NOT EXISTS investment_transactions (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                email          TEXT    NOT NULL COLLATE NOCASE,
                account_id     INTEGER NOT NULL,
                symbol         TEXT    NOT NULL,
                description    TEXT,
                tx_type        TEXT    NOT NULL CHECK(tx_type IN ('buy','sell','split','transfer')),
                tx_date        TEXT    NOT NULL,
                quantity       REAL    NOT NULL,
                price          REAL    NOT NULL,
                currency       TEXT    NOT NULL DEFAULT 'EUR',
                price_eur      REAL,
                commission     REAL    NOT NULL DEFAULT 0,
                commission_eur REAL    NOT NULL DEFAULT 0,
                exchange_rate  REAL,
                notes          TEXT,
                source         TEXT    NOT NULL DEFAULT 'manual' CHECK(source IN ('manual','csv_import','fiscal_import')),
                source_ref     TEXT,
                created_at     TEXT    NOT NULL,
                FOREIGN KEY (account_id) REFERENCES investment_accounts(id) ON DELETE CASCADE
            )
        ''')
        c.execute('CREATE INDEX IF NOT EXISTS idx_it_email  ON investment_transactions(email)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_it_acct   ON investment_transactions(account_id)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_it_symbol ON investment_transactions(symbol)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_it_date   ON investment_transactions(tx_date)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_it_source ON investment_transactions(source, source_ref)')

        c.execute('''
            CREATE TABLE IF NOT EXISTS investment_lots (
                id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                email              TEXT    NOT NULL COLLATE NOCASE,
                account_id         INTEGER NOT NULL,
                symbol             TEXT    NOT NULL,
                buy_date           TEXT    NOT NULL,
                buy_tx_id          INTEGER NOT NULL,
                original_quantity  REAL    NOT NULL,
                remaining_quantity REAL    NOT NULL,
                cost_per_unit_eur  REAL    NOT NULL,
                FOREIGN KEY (account_id) REFERENCES investment_accounts(id) ON DELETE CASCADE,
                FOREIGN KEY (buy_tx_id) REFERENCES investment_transactions(id) ON DELETE CASCADE
            )
        ''')
        c.execute('CREATE INDEX IF NOT EXISTS idx_il_email ON investment_lots(email, account_id, symbol)')

        c.execute('''
            CREATE TABLE IF NOT EXISTS investment_closed (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                email           TEXT    NOT NULL COLLATE NOCASE,
                account_id      INTEGER NOT NULL,
                symbol          TEXT    NOT NULL,
                buy_date        TEXT    NOT NULL,
                sell_date       TEXT    NOT NULL,
                buy_tx_id       INTEGER NOT NULL,
                sell_tx_id      INTEGER NOT NULL,
                quantity        REAL    NOT NULL,
                cost_eur        REAL    NOT NULL,
                proceeds_eur    REAL    NOT NULL,
                realized_pl_eur REAL    NOT NULL,
                holding_days    INTEGER NOT NULL,
                FOREIGN KEY (account_id) REFERENCES investment_accounts(id) ON DELETE CASCADE,
                FOREIGN KEY (buy_tx_id) REFERENCES investment_transactions(id) ON DELETE CASCADE,
                FOREIGN KEY (sell_tx_id) REFERENCES investment_transactions(id) ON DELETE CASCADE
            )
        ''')
        c.execute('CREATE INDEX IF NOT EXISTS idx_ic_email ON investment_closed(email)')

        c.execute('''
            CREATE TABLE IF NOT EXISTS investment_positions (
                id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                email              TEXT    NOT NULL COLLATE NOCASE,
                account_id         INTEGER NOT NULL,
                symbol             TEXT    NOT NULL,
                open_date          TEXT,
                quantity           REAL    NOT NULL,
                avg_cost_eur       REAL    NOT NULL,
                total_cost_eur     REAL    NOT NULL,
                last_updated       TEXT    NOT NULL,
                UNIQUE(email, account_id, symbol),
                FOREIGN KEY (account_id) REFERENCES investment_accounts(id) ON DELETE CASCADE
            )
        ''')

        c.execute('''
            CREATE TABLE IF NOT EXISTS investment_dividends (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                email            TEXT    NOT NULL COLLATE NOCASE,
                account_id       INTEGER NOT NULL,
                symbol           TEXT    NOT NULL,
                pay_date         TEXT    NOT NULL,
                amount           REAL    NOT NULL,
                currency         TEXT    NOT NULL DEFAULT 'EUR',
                amount_eur       REAL    NOT NULL,
                exchange_rate    REAL,
                withholding      REAL    NOT NULL DEFAULT 0,
                withholding_eur  REAL    NOT NULL DEFAULT 0,
                source           TEXT    NOT NULL DEFAULT 'manual',
                source_ref       TEXT,
                FOREIGN KEY (account_id) REFERENCES investment_accounts(id) ON DELETE CASCADE
            )
        ''')
        c.execute('CREATE INDEX IF NOT EXISTS idx_id_email ON investment_dividends(email)')

        c.execute('''
            CREATE TABLE IF NOT EXISTS investment_symbols_cache (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol         TEXT    NOT NULL UNIQUE,
                name           TEXT,
                currency       TEXT,
                exchange       TEXT,
                asset_type     TEXT    CHECK(asset_type IN ('stock','etf','bond','reit','fund')),
                last_price     REAL,
                last_price_eur REAL,
                dividend_yield REAL,
                last_updated   TEXT
            )
        ''')

        c.commit()


# ── Account CRUD ─────────────────────────────────────────────────────────────

def create_account(email, broker, account_name=''):
    """Create an investment account. Returns account id."""
    now = datetime.utcnow().isoformat()
    with _conn() as c:
        c.execute(
            '''INSERT INTO investment_accounts (email, broker, account_name, created_at)
               VALUES (?, ?, ?, ?)''',
            (email.lower(), broker.strip(), account_name.strip(), now)
        )
        c.commit()
        return c.execute("SELECT last_insert_rowid()").fetchone()[0]


def get_or_create_account(email, broker, account_name=''):
    """Get existing account or create one. Returns account id."""
    with _conn() as c:
        row = c.execute(
            '''SELECT id FROM investment_accounts
               WHERE email = ? COLLATE NOCASE AND broker = ? AND account_name = ?''',
            (email.lower(), broker.strip(), account_name.strip())
        ).fetchone()
    if row:
        return row['id']
    return create_account(email, broker, account_name)


def get_accounts(email):
    """Get all accounts for a user."""
    with _conn() as c:
        rows = c.execute(
            '''SELECT * FROM investment_accounts WHERE email = ? COLLATE NOCASE
               ORDER BY broker, account_name''',
            (email.lower(),)
        ).fetchall()
    return [dict(r) for r in rows]


def get_account(account_id, email):
    """Get a single account, verifying ownership."""
    with _conn() as c:
        row = c.execute(
            'SELECT * FROM investment_accounts WHERE id = ? AND email = ? COLLATE NOCASE',
            (account_id, email.lower())
        ).fetchone()
    return dict(row) if row else None


def delete_account(account_id, email):
    """Delete an account (CASCADE deletes all related data)."""
    with _conn() as c:
        c.execute(
            'DELETE FROM investment_accounts WHERE id = ? AND email = ? COLLATE NOCASE',
            (account_id, email.lower())
        )
        c.commit()


# ── Transaction CRUD ─────────────────────────────────────────────────────────

def insert_transaction(email, account_id, symbol, tx_type, tx_date,
                       quantity, price, currency='EUR', price_eur=None,
                       commission=0, commission_eur=0, exchange_rate=None,
                       description=None, notes=None,
                       source='manual', source_ref=None):
    """Insert a single transaction. Returns transaction id."""
    now = datetime.utcnow().isoformat()
    with _conn() as c:
        c.execute(
            '''INSERT INTO investment_transactions
               (email, account_id, symbol, description, tx_type, tx_date,
                quantity, price, currency, price_eur, commission, commission_eur,
                exchange_rate, notes, source, source_ref, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (email.lower(), account_id, symbol.upper(), description,
             tx_type, tx_date, quantity, price, currency,
             price_eur, commission, commission_eur, exchange_rate,
             notes, source, source_ref, now)
        )
        c.commit()
        return c.execute("SELECT last_insert_rowid()").fetchone()[0]


def insert_transactions_bulk(email, transactions):
    """Insert multiple transactions. Each is a dict matching insert_transaction params."""
    now = datetime.utcnow().isoformat()
    with _conn() as c:
        for t in transactions:
            c.execute(
                '''INSERT INTO investment_transactions
                   (email, account_id, symbol, description, tx_type, tx_date,
                    quantity, price, currency, price_eur, commission, commission_eur,
                    exchange_rate, notes, source, source_ref, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (email.lower(), t['account_id'], t['symbol'].upper(),
                 t.get('description'), t['tx_type'], t['tx_date'],
                 t['quantity'], t['price'], t.get('currency', 'EUR'),
                 t.get('price_eur'), t.get('commission', 0),
                 t.get('commission_eur', 0), t.get('exchange_rate'),
                 t.get('notes'), t.get('source', 'manual'),
                 t.get('source_ref'), now)
            )
        c.commit()


def get_transactions(email, account_id=None, symbol=None, tx_types=None,
                     date_from=None, date_to=None, page=1, per_page=50):
    """Query transactions with filters. Returns (rows, total)."""
    where = ['t.email = ? COLLATE NOCASE']
    params = [email.lower()]

    if account_id:
        where.append('t.account_id = ?')
        params.append(account_id)
    if symbol:
        where.append('t.symbol = ?')
        params.append(symbol.upper())
    if tx_types:
        placeholders = ','.join('?' * len(tx_types))
        where.append(f't.tx_type IN ({placeholders})')
        params.extend(tx_types)
    if date_from:
        where.append('t.tx_date >= ?')
        params.append(date_from)
    if date_to:
        where.append('t.tx_date <= ?')
        params.append(date_to)

    where_clause = ' AND '.join(where)

    with _conn() as c:
        total = c.execute(
            f'SELECT COUNT(*) FROM investment_transactions t WHERE {where_clause}',
            params
        ).fetchone()[0]

        offset = (page - 1) * per_page
        rows = c.execute(
            f'''SELECT t.*, a.broker, a.account_name
                FROM investment_transactions t
                JOIN investment_accounts a ON a.id = t.account_id
                WHERE {where_clause}
                ORDER BY t.tx_date DESC, t.id DESC
                LIMIT ? OFFSET ?''',
            params + [per_page, offset]
        ).fetchall()

    return [dict(r) for r in rows], total


def get_transactions_for_fifo(email, account_id, symbol):
    """Get buy/sell transactions ordered for FIFO processing."""
    with _conn() as c:
        rows = c.execute(
            '''SELECT * FROM investment_transactions
               WHERE email = ? COLLATE NOCASE AND account_id = ?
                 AND symbol = ? AND tx_type IN ('buy','sell','split')
               ORDER BY tx_date ASC, id ASC''',
            (email.lower(), account_id, symbol)
        ).fetchall()
    return [dict(r) for r in rows]


def delete_transaction(tx_id, email):
    """Delete a transaction. Returns (account_id, symbol) for FIFO rebuild, or None."""
    with _conn() as c:
        row = c.execute(
            'SELECT account_id, symbol FROM investment_transactions WHERE id = ? AND email = ? COLLATE NOCASE',
            (tx_id, email.lower())
        ).fetchone()
        if not row:
            return None
        result = (row['account_id'], row['symbol'])
        c.execute('DELETE FROM investment_transactions WHERE id = ?', (tx_id,))
        c.commit()
    return result


def check_duplicate_transaction(email, account_id, symbol, tx_date, quantity, price):
    """Check if a matching transaction already exists (for import dedup)."""
    with _conn() as c:
        row = c.execute(
            '''SELECT id FROM investment_transactions
               WHERE email = ? COLLATE NOCASE AND account_id = ?
                 AND symbol = ? AND tx_date = ? AND quantity = ? AND price = ?''',
            (email.lower(), account_id, symbol, tx_date, quantity, price)
        ).fetchone()
    return row is not None


def check_duplicate_by_source(email, source, source_ref):
    """Check if transactions from this source already exist."""
    with _conn() as c:
        row = c.execute(
            '''SELECT COUNT(*) FROM investment_transactions
               WHERE email = ? COLLATE NOCASE AND source = ? AND source_ref = ?''',
            (email.lower(), source, source_ref)
        ).fetchone()
    return row[0] > 0


def delete_by_source(email, source, source_ref):
    """Delete all transactions and dividends imported from a specific source.
    Returns list of (account_id, symbol) pairs affected for FIFO rebuild."""
    e = email.lower()
    with _conn() as c:
        # Get affected (account_id, symbol) pairs before deleting
        affected = c.execute(
            '''SELECT DISTINCT account_id, symbol FROM investment_transactions
               WHERE email = ? COLLATE NOCASE AND source = ? AND source_ref = ?''',
            (e, source, source_ref)
        ).fetchall()
        affected = [(r['account_id'], r['symbol']) for r in affected]

        # Delete transactions
        c.execute(
            '''DELETE FROM investment_transactions
               WHERE email = ? COLLATE NOCASE AND source = ? AND source_ref = ?''',
            (e, source, source_ref)
        )

        # Delete dividends
        c.execute(
            '''DELETE FROM investment_dividends
               WHERE email = ? COLLATE NOCASE AND source = ? AND source_ref = ?''',
            (e, source, source_ref)
        )

        c.commit()
    return affected


# ── FIFO-related writes ──────────────────────────────────────────────────────

def delete_lots(email, account_id, symbol):
    with _conn() as c:
        c.execute(
            '''DELETE FROM investment_lots
               WHERE email = ? COLLATE NOCASE AND account_id = ? AND symbol = ?''',
            (email.lower(), account_id, symbol)
        )
        c.commit()


def delete_closed(email, account_id, symbol):
    with _conn() as c:
        c.execute(
            '''DELETE FROM investment_closed
               WHERE email = ? COLLATE NOCASE AND account_id = ? AND symbol = ?''',
            (email.lower(), account_id, symbol)
        )
        c.commit()


def delete_position(email, account_id, symbol):
    with _conn() as c:
        c.execute(
            '''DELETE FROM investment_positions
               WHERE email = ? COLLATE NOCASE AND account_id = ? AND symbol = ?''',
            (email.lower(), account_id, symbol)
        )
        c.commit()


def insert_lot(email, account_id, symbol, buy_date, buy_tx_id,
               original_quantity, remaining_quantity, cost_per_unit_eur):
    with _conn() as c:
        c.execute(
            '''INSERT INTO investment_lots
               (email, account_id, symbol, buy_date, buy_tx_id,
                original_quantity, remaining_quantity, cost_per_unit_eur)
               VALUES (?,?,?,?,?,?,?,?)''',
            (email.lower(), account_id, symbol, buy_date, buy_tx_id,
             original_quantity, remaining_quantity, cost_per_unit_eur)
        )
        c.commit()


def insert_closed(email, account_id, symbol, buy_date, sell_date,
                  buy_tx_id, sell_tx_id, quantity, cost_eur,
                  proceeds_eur, realized_pl_eur, holding_days):
    with _conn() as c:
        c.execute(
            '''INSERT INTO investment_closed
               (email, account_id, symbol, buy_date, sell_date,
                buy_tx_id, sell_tx_id, quantity, cost_eur, proceeds_eur,
                realized_pl_eur, holding_days)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
            (email.lower(), account_id, symbol, buy_date, sell_date,
             buy_tx_id, sell_tx_id, quantity, cost_eur, proceeds_eur,
             realized_pl_eur, holding_days)
        )
        c.commit()


def upsert_position(email, account_id, symbol, open_date,
                     quantity, avg_cost_eur, total_cost_eur):
    now = datetime.utcnow().isoformat()
    with _conn() as c:
        c.execute(
            '''INSERT INTO investment_positions
               (email, account_id, symbol, open_date, quantity,
                avg_cost_eur, total_cost_eur, last_updated)
               VALUES (?,?,?,?,?,?,?,?)
               ON CONFLICT(email, account_id, symbol) DO UPDATE SET
                 open_date = excluded.open_date,
                 quantity = excluded.quantity,
                 avg_cost_eur = excluded.avg_cost_eur,
                 total_cost_eur = excluded.total_cost_eur,
                 last_updated = excluded.last_updated''',
            (email.lower(), account_id, symbol, open_date,
             quantity, avg_cost_eur, total_cost_eur, now)
        )
        c.commit()


# ── Position queries ─────────────────────────────────────────────────────────

def get_positions(email, account_id=None):
    """Get all open positions, optionally filtered by account."""
    where = ['p.email = ? COLLATE NOCASE']
    params = [email.lower()]
    if account_id:
        where.append('p.account_id = ?')
        params.append(account_id)

    with _conn() as c:
        rows = c.execute(
            f'''SELECT p.*, a.broker, a.account_name,
                       sc.name as symbol_name, sc.last_price, sc.last_price_eur,
                       sc.dividend_yield
                FROM investment_positions p
                JOIN investment_accounts a ON a.id = p.account_id
                LEFT JOIN investment_symbols_cache sc ON sc.symbol = p.symbol
                WHERE {' AND '.join(where)}
                ORDER BY p.total_cost_eur DESC''',
            params
        ).fetchall()
    return [dict(r) for r in rows]


def get_position_detail(email, symbol):
    """Get detailed data for one symbol across all accounts."""
    e = email.lower()
    with _conn() as c:
        positions = c.execute(
            '''SELECT p.*, a.broker, a.account_name
               FROM investment_positions p
               JOIN investment_accounts a ON a.id = p.account_id
               WHERE p.email = ? COLLATE NOCASE AND p.symbol = ?''',
            (e, symbol)
        ).fetchall()

        lots = c.execute(
            '''SELECT l.*, a.broker
               FROM investment_lots l
               JOIN investment_accounts a ON a.id = l.account_id
               WHERE l.email = ? COLLATE NOCASE AND l.symbol = ?
               ORDER BY l.buy_date ASC''',
            (e, symbol)
        ).fetchall()

        txs = c.execute(
            '''SELECT t.*, a.broker
               FROM investment_transactions t
               JOIN investment_accounts a ON a.id = t.account_id
               WHERE t.email = ? COLLATE NOCASE AND t.symbol = ?
               ORDER BY t.tx_date DESC LIMIT 50''',
            (e, symbol)
        ).fetchall()

        closed = c.execute(
            '''SELECT c.*, a.broker
               FROM investment_closed c
               JOIN investment_accounts a ON a.id = c.account_id
               WHERE c.email = ? COLLATE NOCASE AND c.symbol = ?
               ORDER BY c.sell_date DESC''',
            (e, symbol)
        ).fetchall()

        divs = c.execute(
            '''SELECT d.*, a.broker
               FROM investment_dividends d
               JOIN investment_accounts a ON a.id = d.account_id
               WHERE d.email = ? COLLATE NOCASE AND d.symbol = ?
               ORDER BY d.pay_date DESC''',
            (e, symbol)
        ).fetchall()

    return {
        'positions': [dict(r) for r in positions],
        'lots': [dict(r) for r in lots],
        'transactions': [dict(r) for r in txs],
        'closed': [dict(r) for r in closed],
        'dividends': [dict(r) for r in divs],
    }


def get_closed_trades(email, symbol=None, year=None):
    """Get realized (closed) trades, optionally filtered."""
    where = ['c.email = ? COLLATE NOCASE']
    params = [email.lower()]
    if symbol:
        where.append('c.symbol = ?')
        params.append(symbol)
    if year:
        where.append("c.sell_date LIKE ?")
        params.append(f"{year}%")

    with _conn() as c:
        rows = c.execute(
            f'''SELECT c.*, a.broker
                FROM investment_closed c
                JOIN investment_accounts a ON a.id = c.account_id
                WHERE {' AND '.join(where)}
                ORDER BY c.sell_date DESC''',
            params
        ).fetchall()
    return [dict(r) for r in rows]


# ── Dividend CRUD ────────────────────────────────────────────────────────────

def insert_dividend(email, account_id, symbol, pay_date, amount,
                    currency='EUR', amount_eur=0, exchange_rate=None,
                    withholding=0, withholding_eur=0,
                    source='manual', source_ref=None):
    with _conn() as c:
        c.execute(
            '''INSERT INTO investment_dividends
               (email, account_id, symbol, pay_date, amount, currency,
                amount_eur, exchange_rate, withholding, withholding_eur,
                source, source_ref)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
            (email.lower(), account_id, symbol.upper(), pay_date,
             amount, currency, amount_eur, exchange_rate,
             withholding, withholding_eur, source, source_ref)
        )
        c.commit()
        return c.execute("SELECT last_insert_rowid()").fetchone()[0]


def insert_dividends_bulk(email, dividends):
    """Insert multiple dividends. Each is a dict."""
    with _conn() as c:
        for d in dividends:
            c.execute(
                '''INSERT INTO investment_dividends
                   (email, account_id, symbol, pay_date, amount, currency,
                    amount_eur, exchange_rate, withholding, withholding_eur,
                    source, source_ref)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
                (email.lower(), d['account_id'], d['symbol'].upper(),
                 d['pay_date'], d['amount'], d.get('currency', 'EUR'),
                 d.get('amount_eur', 0), d.get('exchange_rate'),
                 d.get('withholding', 0), d.get('withholding_eur', 0),
                 d.get('source', 'manual'), d.get('source_ref'))
            )
        c.commit()


def get_dividends(email, symbol=None, year=None, account_id=None,
                  page=1, per_page=50):
    """Query dividends with filters. Returns (rows, total, total_amount_eur)."""
    where = ['d.email = ? COLLATE NOCASE']
    params = [email.lower()]
    if symbol:
        where.append('d.symbol = ?')
        params.append(symbol)
    if year:
        where.append("d.pay_date LIKE ?")
        params.append(f"{year}%")
    if account_id:
        where.append('d.account_id = ?')
        params.append(account_id)

    where_clause = ' AND '.join(where)

    with _conn() as c:
        agg = c.execute(
            f'''SELECT COUNT(*) as cnt, COALESCE(SUM(d.amount_eur), 0) as total_eur
                FROM investment_dividends d WHERE {where_clause}''',
            params
        ).fetchone()

        offset = (page - 1) * per_page
        rows = c.execute(
            f'''SELECT d.*, a.broker, a.account_name
                FROM investment_dividends d
                JOIN investment_accounts a ON a.id = d.account_id
                WHERE {where_clause}
                ORDER BY d.pay_date DESC
                LIMIT ? OFFSET ?''',
            params + [per_page, offset]
        ).fetchall()

    return [dict(r) for r in rows], agg['cnt'], agg['total_eur']


# ── Portfolio summary ────────────────────────────────────────────────────────

def get_portfolio_summary(email):
    """Compute aggregate portfolio stats."""
    e = email.lower()
    with _conn() as c:
        # Positions cost
        pos = c.execute(
            '''SELECT COALESCE(SUM(total_cost_eur), 0) as total_invested,
                      COUNT(*) as positions_count
               FROM investment_positions WHERE email = ? COLLATE NOCASE''',
            (e,)
        ).fetchone()

        # Realized P&L
        closed = c.execute(
            '''SELECT COALESCE(SUM(realized_pl_eur), 0) as total_realized
               FROM investment_closed WHERE email = ? COLLATE NOCASE''',
            (e,)
        ).fetchone()

        # Total dividends
        divs = c.execute(
            '''SELECT COALESCE(SUM(amount_eur), 0) as total_dividends
               FROM investment_dividends WHERE email = ? COLLATE NOCASE''',
            (e,)
        ).fetchone()

        # Dividends YTD
        current_year = datetime.utcnow().strftime('%Y')
        divs_ytd = c.execute(
            '''SELECT COALESCE(SUM(amount_eur), 0) as total
               FROM investment_dividends
               WHERE email = ? COLLATE NOCASE AND pay_date LIKE ?''',
            (e, f"{current_year}%")
        ).fetchone()

    return {
        'total_invested_eur': pos['total_invested'],
        'positions_count': pos['positions_count'],
        'total_realized_pl_eur': closed['total_realized'],
        'total_dividends_eur': divs['total_dividends'],
        'total_dividends_ytd_eur': divs_ytd['total'],
    }


# ── Symbols cache ────────────────────────────────────────────────────────────

def get_cached_symbol(symbol):
    with _conn() as c:
        row = c.execute(
            'SELECT * FROM investment_symbols_cache WHERE symbol = ?',
            (symbol.upper(),)
        ).fetchone()
    return dict(row) if row else None


def upsert_symbol_cache(symbol, name=None, currency=None, exchange=None,
                        asset_type=None, last_price=None, last_price_eur=None,
                        dividend_yield=None):
    now = datetime.utcnow().isoformat()
    with _conn() as c:
        c.execute(
            '''INSERT INTO investment_symbols_cache
               (symbol, name, currency, exchange, asset_type,
                last_price, last_price_eur, dividend_yield, last_updated)
               VALUES (?,?,?,?,?,?,?,?,?)
               ON CONFLICT(symbol) DO UPDATE SET
                 name = COALESCE(excluded.name, investment_symbols_cache.name),
                 currency = COALESCE(excluded.currency, investment_symbols_cache.currency),
                 exchange = COALESCE(excluded.exchange, investment_symbols_cache.exchange),
                 asset_type = COALESCE(excluded.asset_type, investment_symbols_cache.asset_type),
                 last_price = excluded.last_price,
                 last_price_eur = excluded.last_price_eur,
                 dividend_yield = excluded.dividend_yield,
                 last_updated = excluded.last_updated''',
            (symbol.upper(), name, currency, exchange, asset_type,
             last_price, last_price_eur, dividend_yield, now)
        )
        c.commit()


def search_symbols_cache(query):
    """Search local symbol cache by prefix/substring."""
    with _conn() as c:
        rows = c.execute(
            '''SELECT * FROM investment_symbols_cache
               WHERE symbol LIKE ? OR name LIKE ?
               ORDER BY symbol LIMIT 20''',
            (f'{query}%', f'%{query}%')
        ).fetchall()
    return [dict(r) for r in rows]


def get_all_user_symbols(email):
    """Get distinct symbols the user has positions or transactions for."""
    with _conn() as c:
        rows = c.execute(
            '''SELECT DISTINCT symbol FROM investment_transactions
               WHERE email = ? COLLATE NOCASE
               UNION
               SELECT DISTINCT symbol FROM investment_positions
               WHERE email = ? COLLATE NOCASE
               ORDER BY symbol''',
            (email.lower(), email.lower())
        ).fetchall()
    return [r['symbol'] for r in rows]


# Initialize on import
init_investments_db()
