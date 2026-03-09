"""
Price service — yfinance wrapper for live prices, symbol search, and cache.
Reuses fiscal.exchange_rates.to_eur() for EUR conversion.
"""

import yfinance as yf
from datetime import datetime, timedelta
from . import database as db

# Reuse fiscal exchange rate service
from options_monitor_agent.fiscal.exchange_rates import to_eur


def search_symbols(query):
    """Search for stock/ETF symbols using yfinance + local cache."""
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

    # Query yfinance
    results = []
    try:
        ticker = yf.Ticker(query)
        info = ticker.info or {}
        if info.get('symbol'):
            asset_type = _detect_asset_type(info)
            result = {
                'symbol': info.get('symbol', query),
                'name': info.get('shortName') or info.get('longName', ''),
                'exchange': info.get('exchange', ''),
                'asset_type': asset_type,
                'currency': info.get('currency', ''),
            }
            results.append(result)
            # Cache it
            db.upsert_symbol_cache(
                symbol=result['symbol'],
                name=result['name'],
                currency=result['currency'],
                exchange=result['exchange'],
                asset_type=asset_type,
            )
    except Exception:
        pass

    # Also try yfinance search if direct lookup didn't match well
    if not results or results[0]['symbol'] != query:
        try:
            search_results = yf.Search(query)
            for quote in (search_results.quotes or [])[:5]:
                sym = quote.get('symbol', '')
                if any(r['symbol'] == sym for r in results):
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


def get_live_price(symbol):
    """Get current price for a symbol. Returns dict or None."""
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

    # Fetch from yfinance
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info or {}
        price = info.get('currentPrice') or info.get('regularMarketPrice')
        currency = info.get('currency', 'EUR')

        if price is None:
            return None

        today = datetime.utcnow().strftime('%Y-%m-%d')
        price_eur = to_eur(price, currency, today) if currency != 'EUR' else price

        db.upsert_symbol_cache(
            symbol=symbol,
            name=info.get('shortName') or info.get('longName'),
            currency=currency,
            exchange=info.get('exchange'),
            asset_type=_detect_asset_type(info),
            last_price=price,
            last_price_eur=price_eur,
            dividend_yield=info.get('dividendYield'),
        )

        return {
            'symbol': symbol,
            'price': price,
            'price_eur': price_eur,
            'currency': currency,
            'name': info.get('shortName', ''),
        }
    except Exception:
        return None


def refresh_prices(symbols):
    """Batch-refresh prices for a list of symbols."""
    results = {}
    for sym in symbols:
        r = get_live_price(sym)
        if r:
            results[sym] = r
    return results


def get_price_history(symbol, period='1y'):
    """Get historical price data for charting."""
    valid_periods = {'1m', '3m', '6m', '1y', '5y', 'max'}
    if period not in valid_periods:
        period = '1y'

    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period=period)
        if hist.empty:
            return None

        info = ticker.info or {}
        currency = info.get('currency', 'EUR')

        data = []
        for date, row in hist.iterrows():
            date_str = date.strftime('%Y-%m-%d')
            close = float(row['Close'])
            close_eur = to_eur(close, currency, date_str) if currency != 'EUR' else close
            data.append({
                'date': date_str,
                'close': round(close, 4),
                'close_eur': round(close_eur, 4) if close_eur else None,
            })

        return {
            'symbol': symbol,
            'currency': currency,
            'data': data,
        }
    except Exception:
        return None


def _detect_asset_type(info):
    """Detect asset type from yfinance info dict."""
    qt = info.get('quoteType', '').upper()
    return _type_from_quote_type(qt)


def _type_from_quote_type(qt):
    qt = qt.upper()
    if qt == 'ETF':
        return 'etf'
    if qt in ('EQUITY', 'STOCK'):
        return 'stock'
    if qt == 'MUTUALFUND':
        return 'fund'
    return 'stock'
