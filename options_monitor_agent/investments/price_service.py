"""
Price service — fetches live prices via direct Yahoo Finance HTTP API,
with yfinance as fallback.  Reuses fiscal.exchange_rates.to_eur() for EUR.
"""

import logging
import requests as _requests
import yfinance as yf
from datetime import datetime, timedelta
from . import database as db

log = logging.getLogger(__name__)

# Reuse fiscal exchange rate service (graceful fallback if unavailable)
try:
    from options_monitor_agent.fiscal.exchange_rates import to_eur
except Exception:
    log.warning('[price] Could not import to_eur — EUR conversion disabled')
    def to_eur(amount, currency, date):
        return None

# ── Direct Yahoo HTTP helpers (no yfinance dependency) ───────────────────────
_YF_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
_YF_HEADERS = {"User-Agent": "Mozilla/5.0"}


def _fetch_yahoo_http(symbol):
    """Fetch price + currency directly from Yahoo Finance chart API.
    Returns (price, currency) or (None, None)."""
    try:
        url = _YF_CHART_URL.format(symbol=symbol)
        r = _requests.get(url, headers=_YF_HEADERS, timeout=10,
                          params={"range": "5d", "interval": "1d"})
        r.raise_for_status()
        data = r.json()
        result = data["chart"]["result"][0]
        meta = result["meta"]
        currency = meta.get("currency", "EUR")
        # regularMarketPrice is the most current
        price = meta.get("regularMarketPrice")
        if price and float(price) > 0:
            return float(price), currency
        # Fallback: last close from the time series
        closes = result.get("indicators", {}).get("quote", [{}])[0].get("close", [])
        for c in reversed(closes):
            if c is not None and float(c) > 0:
                return float(c), currency
        return None, currency
    except Exception as exc:
        log.warning('[price] %s: Yahoo HTTP fallback failed: %s', symbol, exc)
        return None, None


# ── Symbol search ────────────────────────────────────────────────────────────

def search_symbols(query):
    """Search for stock/ETF symbols — cache-first, then yfinance Search API only."""
    query = query.strip().upper()
    if not query:
        return []

    # Check local cache first
    cached = db.search_symbols_cache(query)
    if cached:
        return [{
            'symbol': r['symbol'], 'name': r['name'],
            'exchange': r['exchange'], 'asset_type': r['asset_type'],
            'currency': r['currency'],
        } for r in cached]

    # Use yfinance Search API only (lightweight, no Ticker creation)
    results = []
    try:
        search_results = yf.Search(query)
        for quote in (search_results.quotes or [])[:8]:
            sym = quote.get('symbol', '')
            if not sym:
                continue
            asset_type = _type_from_quote_type(quote.get('quoteType', ''))
            result = {
                'symbol': sym,
                'name': quote.get('shortname') or quote.get('longname', ''),
                'exchange': quote.get('exchange', ''),
                'asset_type': asset_type,
                'currency': quote.get('currency', ''),
            }
            results.append(result)
            db.upsert_symbol_cache(
                symbol=result['symbol'],
                name=result['name'],
                currency=result['currency'],
                exchange=result['exchange'],
                asset_type=asset_type,
            )
    except Exception:
        pass

    return results[:10]


# ── Live prices ──────────────────────────────────────────────────────────────

def get_live_price(symbol):
    """Get current price. Tries: 1) DB cache, 2) Yahoo HTTP API, 3) yfinance fast_info."""
    cached = db.get_cached_symbol(symbol)
    if cached and cached.get('last_updated'):
        try:
            updated = datetime.fromisoformat(cached['last_updated'])
            if datetime.utcnow() - updated < timedelta(minutes=15):
                return {
                    'symbol': cached['symbol'],
                    'price': cached['last_price'],
                    'price_eur': cached['last_price_eur'],
                    'currency': cached['currency'],
                    'name': cached['name'],
                }
        except (ValueError, TypeError):
            pass

    price, currency = None, None

    # ── Source 1: Direct Yahoo HTTP API (most reliable on cloud) ──────────
    price, currency = _fetch_yahoo_http(symbol)

    # ── Source 2: yfinance fast_info (fallback) ──────────────────────────
    if price is None:
        try:
            ticker = yf.Ticker(symbol)
            fi = ticker.fast_info
            for attr in ('last_price', 'previous_close', 'regular_market_previous_close'):
                try:
                    val = getattr(fi, attr, None)
                    if val is not None and val > 0:
                        price = float(val)
                        break
                except Exception:
                    continue
            if not currency:
                try:
                    currency = getattr(fi, 'currency', None) or fi.get('currency', 'EUR')
                except Exception:
                    pass
        except Exception as exc:
            log.warning('[price] %s: yfinance fast_info failed: %s', symbol, exc)

    if not currency:
        currency = 'EUR'

    if price is None:
        log.warning('[price] %s: no price from any source', symbol)
        return None

    today = datetime.utcnow().strftime('%Y-%m-%d')
    price_eur = price
    if currency != 'EUR':
        try:
            price_eur = to_eur(price, currency, today)
        except Exception as exc:
            log.warning('[price] %s: to_eur failed: %s', symbol, exc)
        if price_eur is None:
            price_eur = price

    name = (cached or {}).get('name', '')

    db.upsert_symbol_cache(
        symbol=symbol,
        name=name or None,
        currency=currency,
        last_price=price,
        last_price_eur=price_eur,
    )

    log.info('[price] %s: %.2f %s -> %.2f EUR', symbol, price, currency, price_eur)
    return {
        'symbol': symbol,
        'price': price,
        'price_eur': price_eur,
        'currency': currency,
        'name': name,
    }


def refresh_prices(symbols):
    """Batch-refresh prices for a list of symbols."""
    results = {}
    for sym in symbols:
        r = get_live_price(sym)
        if r:
            results[sym] = r
    return results


# ── Price history (charts) ───────────────────────────────────────────────────

def get_price_history(symbol, period='1y'):
    """Get historical price data for charting. Lightweight — no .info call."""
    valid_periods = {'1m', '3m', '6m', '1y', '5y', 'max'}
    if period not in valid_periods:
        period = '1y'

    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period=period)
        if hist.empty:
            return None

        # Get currency from cache (avoids .info call)
        cached = db.get_cached_symbol(symbol)
        currency = (cached or {}).get('currency', 'EUR') or 'EUR'

        # For EUR symbols or unknown currency, skip conversion overhead
        if currency == 'EUR':
            data = [
                {'date': date.strftime('%Y-%m-%d'),
                 'close': round(float(row['Close']), 4),
                 'close_eur': round(float(row['Close']), 4)}
                for date, row in hist.iterrows()
            ]
        else:
            # Convert using a single rate (latest) for performance
            today = datetime.utcnow().strftime('%Y-%m-%d')
            rate = None
            try:
                from options_monitor_agent.fiscal.exchange_rates import get_rate
                rate = get_rate(currency, today)
            except Exception:
                pass

            data = []
            for date, row in hist.iterrows():
                close = float(row['Close'])
                close_eur = round(close * rate, 4) if rate else round(close, 4)
                data.append({
                    'date': date.strftime('%Y-%m-%d'),
                    'close': round(close, 4),
                    'close_eur': close_eur,
                })

        return {
            'symbol': symbol,
            'currency': currency,
            'data': data,
        }
    except Exception:
        return None


# ── Helpers ──────────────────────────────────────────────────────────────────

def _type_from_quote_type(qt):
    qt = (qt or '').upper()
    if qt == 'ETF':
        return 'etf'
    if qt in ('EQUITY', 'STOCK'):
        return 'stock'
    if qt == 'MUTUALFUND':
        return 'fund'
    return 'stock'
