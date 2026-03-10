"""
Price service — lightweight yfinance wrapper.
Uses fast_info (not .info) to avoid downloading huge payloads.
Reuses fiscal.exchange_rates.to_eur() for EUR conversion.
"""

import yfinance as yf
from datetime import datetime, timedelta
from . import database as db

# Reuse fiscal exchange rate service
from options_monitor_agent.fiscal.exchange_rates import to_eur


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
    """Get current price using fast_info (low memory). Returns dict or None."""
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

    try:
        ticker = yf.Ticker(symbol)
        fi = ticker.fast_info

        # Try multiple price sources — fast_info attribute access is most reliable
        price = None
        for attr in ('last_price', 'previous_close', 'regular_market_previous_close'):
            try:
                val = getattr(fi, attr, None)
                if val is not None and val > 0:
                    price = float(val)
                    break
            except Exception:
                continue

        # Fallback: dict-style access
        if price is None:
            for key in ('lastPrice', 'previousClose', 'regularMarketPreviousClose'):
                try:
                    val = fi.get(key)
                    if val is not None and val != 'N/A' and float(val) > 0:
                        price = float(val)
                        break
                except Exception:
                    continue

        # Last resort: use recent history
        if price is None:
            try:
                hist = ticker.history(period='5d')
                if not hist.empty:
                    price = float(hist['Close'].iloc[-1])
            except Exception:
                pass

        currency = None
        try:
            currency = getattr(fi, 'currency', None)
        except Exception:
            pass
        if not currency:
            currency = fi.get('currency', 'EUR') or 'EUR'

        if price is None:
            return None

        today = datetime.utcnow().strftime('%Y-%m-%d')
        price_eur = price
        if currency != 'EUR':
            try:
                price_eur = to_eur(price, currency, today)
            except Exception:
                pass
            # If to_eur returned None, try with previous_close date or keep raw price
            if price_eur is None:
                price_eur = price  # Use unconverted as fallback

        # Cache name from existing cache or leave blank (avoid .info)
        name = (cached or {}).get('name', '')

        db.upsert_symbol_cache(
            symbol=symbol,
            name=name or None,
            currency=currency,
            last_price=price,
            last_price_eur=price_eur,
        )

        return {
            'symbol': symbol,
            'price': price,
            'price_eur': price_eur,
            'currency': currency,
            'name': name,
        }
    except Exception:
        # Return stale cache as fallback
        if cached and cached.get('last_price'):
            return {
                'symbol': cached['symbol'],
                'price': cached['last_price'],
                'price_eur': cached['last_price_eur'],
                'currency': cached.get('currency', 'EUR'),
                'name': cached.get('name', ''),
            }
        return None


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
