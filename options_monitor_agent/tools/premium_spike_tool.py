"""
Premium Spike Detection Tool
Detects sudden spikes in options premium prices between cycles.
Stores snapshots in SQLite and fires alerts + push notifications.
"""
import json
import os
import time
from datetime import datetime
from options_monitor_agent.db_utils import get_conn

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SQLITE_PATH = os.path.join(BASE_DIR, "memory", "premium_snapshots.db")


def _get_conn():
    conn = get_conn(_SQLITE_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS premium_snapshots (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ts          REAL NOT NULL,
            ticker      TEXT NOT NULL,
            option_type TEXT NOT NULL,
            expiration  TEXT NOT NULL,
            strike      REAL NOT NULL,
            mid_price   REAL NOT NULL,
            iv          REAL,
            volume      INTEGER,
            open_interest INTEGER
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_snap_lookup
        ON premium_snapshots(ticker, option_type, expiration, strike)
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS spike_alerts (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ts          REAL NOT NULL,
            ticker      TEXT NOT NULL,
            option_type TEXT NOT NULL,
            expiration  TEXT NOT NULL,
            strike      REAL NOT NULL,
            prev_mid    REAL NOT NULL,
            curr_mid    REAL NOT NULL,
            pct_change  REAL NOT NULL,
            notified    INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    return conn


def save_snapshot(ticker, options_data):
    """Save current options prices snapshot for a ticker.
    options_data: list of dicts with keys type, expiration, strike, bid, ask, impliedVolatility, volume, openInterest
    """
    conn = _get_conn()
    ts = time.time()
    rows = []
    for opt in options_data:
        bid = opt.get("bid", 0) or 0
        ask = opt.get("ask", 0) or 0
        last = opt.get("lastPrice", 0) or opt.get("last", 0) or 0
        if bid > 0 and ask > 0:
            mid = round((bid + ask) / 2, 4)
        elif last > 0:
            mid = round(last, 4)
        else:
            continue  # no usable price data
        rows.append((
            ts,
            ticker,
            opt.get("type", "CALL"),
            opt.get("expiration", ""),
            float(opt.get("strike", 0)),
            mid,
            opt.get("impliedVolatility", None),
            opt.get("volume", 0),
            opt.get("openInterest", 0),
        ))
    conn.executemany("""
        INSERT INTO premium_snapshots
        (ts, ticker, option_type, expiration, strike, mid_price, iv, volume, open_interest)
        VALUES (?,?,?,?,?,?,?,?,?)
    """, rows)
    conn.commit()
    conn.close()
    return len(rows)


def detect_spikes(ticker, options_data, threshold=0.25):
    """Compare current options prices vs last snapshot.
    Returns list of spike dicts if premium moved > threshold (default 25%).
    """
    conn = _get_conn()
    spikes = []
    ts_now = time.time()

    for opt in options_data:
        bid = opt.get("bid", 0) or 0
        ask = opt.get("ask", 0) or 0
        last = opt.get("lastPrice", 0) or opt.get("last", 0) or 0
        if bid > 0 and ask > 0:
            curr_mid = round((bid + ask) / 2, 4)
        elif last > 0:
            curr_mid = round(last, 4)
        else:
            continue  # no usable price data
        if curr_mid <= 0.01:
            continue

        opt_type = opt.get("type", "CALL")
        expiration = opt.get("expiration", "")
        strike = float(opt.get("strike", 0))

        row = conn.execute("""
            SELECT mid_price, ts FROM premium_snapshots
            WHERE ticker=? AND option_type=? AND expiration=? AND strike=?
            ORDER BY ts DESC LIMIT 1
        """, (ticker, opt_type, expiration, strike)).fetchone()

        if not row:
            continue

        prev_mid = row["mid_price"]
        if prev_mid <= 0.01:
            continue

        pct_change = (curr_mid - prev_mid) / prev_mid

        if abs(pct_change) >= threshold:
            spike = {
                "ticker": ticker,
                "option_type": opt_type,
                "expiration": expiration,
                "strike": strike,
                "prev_mid": prev_mid,
                "curr_mid": curr_mid,
                "pct_change": round(pct_change * 100, 1),
                "direction": "UP" if pct_change > 0 else "DOWN",
                "iv": opt.get("impliedVolatility", 0),
            }
            spikes.append(spike)
            # Save to spike_alerts table
            conn.execute("""
                INSERT INTO spike_alerts
                (ts, ticker, option_type, expiration, strike, prev_mid, curr_mid, pct_change)
                VALUES (?,?,?,?,?,?,?,?)
            """, (ts_now, ticker, opt_type, expiration, strike, prev_mid, curr_mid, pct_change * 100))

    conn.commit()
    conn.close()
    return spikes


def get_recent_spike_alerts(hours=24):
    """Fetch spike alerts from the last N hours for the dashboard."""
    conn = _get_conn()
    cutoff = time.time() - (hours * 3600)
    rows = conn.execute("""
        SELECT * FROM spike_alerts WHERE ts > ? ORDER BY ts DESC LIMIT 50
    """, (cutoff,)).fetchall()
    conn.close()
    result = []
    for r in rows:
        result.append({
            "ts": r["ts"],
            "ticker": r["ticker"],
            "option_type": r["option_type"],
            "expiration": r["expiration"],
            "strike": r["strike"],
            "prev_mid": r["prev_mid"],
            "curr_mid": r["curr_mid"],
            "pct_change": r["pct_change"],
            "timestamp": datetime.fromtimestamp(r["ts"]).strftime("%Y-%m-%d %H:%M:%S"),
        })
    return result
