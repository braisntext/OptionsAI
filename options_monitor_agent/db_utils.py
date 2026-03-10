"""
Shared database connection layer.

- PostgreSQL when DATABASE_URL is set (production on Render).
- SQLite when DATABASE_URL is absent (local development).

Each module calls get_conn(sqlite_path) to obtain a ConnectionWrapper
that transparently handles dialect differences.
"""

import os
import re
import sqlite3
import threading
from functools import lru_cache

# ── Detect backend ───────────────────────────────────────────────────────────

_raw_url = os.getenv("DATABASE_URL", "")
if _raw_url.startswith("postgres://"):
    _raw_url = _raw_url.replace("postgres://", "postgresql://", 1)

IS_POSTGRES = _raw_url.startswith("postgresql")
DATABASE_URL = _raw_url

# ── PostgreSQL pool (lazy init — safe with Gunicorn pre-fork) ────────────────

_pool = None
_pool_lock = threading.Lock()


def _get_pool():
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                import psycopg2.pool
                _pool = psycopg2.pool.ThreadedConnectionPool(1, 5, DATABASE_URL)
    return _pool


# ── Public API ───────────────────────────────────────────────────────────────

def get_conn(sqlite_path=None):
    """Return a ConnectionWrapper.

    Production (IS_POSTGRES): ignores sqlite_path, uses pooled PostgreSQL.
    Development: uses sqlite_path for a local SQLite file.
    """
    if IS_POSTGRES:
        pool = _get_pool()
        raw = pool.getconn()
        # Validate connection — Render free-tier drops idle connections
        try:
            raw.rollback()  # resets state + checks liveness
        except Exception:
            try:
                pool.putconn(raw, close=True)
            except Exception:
                pass
            raw = pool.getconn()
        return _PgConnWrapper(raw)
    else:
        if not sqlite_path:
            raise ValueError("sqlite_path is required for SQLite connections")
        c = sqlite3.connect(sqlite_path)
        c.row_factory = sqlite3.Row
        return _SqliteConnWrapper(c)


# ── SQLite wrapper ───────────────────────────────────────────────────────────

class _SqliteConnWrapper:
    """Thin pass-through around sqlite3.Connection."""

    def __init__(self, conn):
        self._conn = conn
        self.total_changes = 0
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")

    def execute(self, sql, params=None):
        cur = self._conn.execute(sql, params) if params else self._conn.execute(sql)
        self.total_changes = self._conn.total_changes
        return cur

    def executemany(self, sql, params_list):
        return self._conn.executemany(sql, params_list)

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            self._conn.rollback()
        self._conn.close()
        return False


# ── PostgreSQL wrapper ───────────────────────────────────────────────────────

_AUTOINCREMENT_RE = re.compile(
    r'INTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT', re.IGNORECASE,
)
_COLLATE_RE = re.compile(r'\s*COLLATE\s+NOCASE', re.IGNORECASE)


class _PgConnWrapper:
    """Wraps a psycopg2 connection to accept SQLite-style SQL."""

    def __init__(self, conn):
        self._conn = conn
        self.total_changes = 0
        # Cache the cursor factory at import time
        import psycopg2.extras
        self._dict_cursor = psycopg2.extras.DictCursor

    @staticmethod
    @lru_cache(maxsize=256)
    def _translate(sql):
        if sql.strip().upper().startswith('PRAGMA'):
            return None
        sql = sql.replace('?', '%s')
        sql = sql.replace('last_insert_rowid()', 'lastval()')
        sql = _AUTOINCREMENT_RE.sub('SERIAL PRIMARY KEY', sql)
        sql = _COLLATE_RE.sub('', sql)
        return sql

    def execute(self, sql, params=None):
        sql = self._translate(sql)
        if sql is None:
            return _NullCursor()
        cur = self._conn.cursor(cursor_factory=self._dict_cursor)
        cur.execute(sql, params or ())
        self.total_changes = cur.rowcount
        return cur

    def executemany(self, sql, params_list):
        sql = self._translate(sql)
        if sql is None:
            return _NullCursor()
        cur = self._conn.cursor()
        cur.executemany(sql, params_list)
        self.total_changes = cur.rowcount
        return cur

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        try:
            _get_pool().putconn(self._conn)
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            try:
                self._conn.rollback()
            except Exception:
                pass
            # Discard potentially dead connection from pool
            try:
                _get_pool().putconn(self._conn, close=True)
            except Exception:
                pass
        else:
            self.close()
        return False


class _NullCursor:
    """No-op cursor for skipped statements (PRAGMAs on PostgreSQL)."""
    def fetchone(self):
        return None

    def fetchall(self):
        return []
