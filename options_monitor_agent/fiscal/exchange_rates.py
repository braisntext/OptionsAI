"""
ECB exchange rate service — fetches EUR rates from the European Central Bank.
Caches locally to avoid repeated API calls.
"""

import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from . import database as db

# ECB provides free daily exchange rates (no API key needed)
_ECB_DAILY_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist-90d.xml"
_ECB_FULL_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.xml"
_ECB_NS = {"gesmes": "http://www.gesmes.org/xml/2002-08-01",
           "ecb": "http://www.ecb.int/vocabulary/2002-08-01/eurofxref"}


def _fetch_ecb_xml(url):
    """Fetch and parse ECB XML feed."""
    import requests
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return ET.fromstring(resp.content)


def _parse_ecb_rates(root):
    """Parse ECB XML into {date_str: {currency: rate}} dict."""
    rates = {}
    cube = root.find('.//ecb:Cube', _ECB_NS)
    if cube is None:
        return rates
    for time_cube in cube.findall('ecb:Cube[@time]', _ECB_NS):
        date_str = time_cube.attrib['time']
        day_rates = {}
        for rate_cube in time_cube.findall('ecb:Cube', _ECB_NS):
            currency = rate_cube.attrib['currency']
            rate = float(rate_cube.attrib['rate'])
            day_rates[currency] = rate
        rates[date_str] = day_rates
    return rates


def fetch_and_cache_rates(year=None):
    """Fetch ECB rates and cache them. Uses 90-day feed or full history."""
    current_year = datetime.utcnow().year
    if year and year < current_year:
        url = _ECB_FULL_URL
    else:
        url = _ECB_DAILY_URL

    root = _fetch_ecb_xml(url)
    all_rates = _parse_ecb_rates(root)

    cached = 0
    for date_str, currencies in all_rates.items():
        if year and not date_str.startswith(str(year)):
            continue
        for currency, rate in currencies.items():
            db.cache_rate(date_str, currency, rate, source='ECB')
            cached += 1

    return cached


def get_rate(currency, date_str):
    """
    Get EUR exchange rate for a currency on a given date.
    Rate meaning: 1 EUR = X units of currency.
    So to convert FROM currency TO EUR: amount / rate.

    Falls back to nearest available date if exact date not cached.
    """
    if currency == 'EUR':
        return 1.0

    # Try exact date
    rate = db.get_cached_rate(date_str, currency)
    if rate:
        return rate

    # Try nearby dates (weekends/holidays)
    dt = datetime.strptime(date_str, '%Y-%m-%d')
    for delta in range(1, 8):
        for direction in (-1, 1):
            nearby = (dt + timedelta(days=delta * direction)).strftime('%Y-%m-%d')
            rate = db.get_cached_rate(nearby, currency)
            if rate:
                return rate

    # Not cached — try fetching
    try:
        year = int(date_str[:4])
        fetch_and_cache_rates(year=year)
        rate = db.get_cached_rate(date_str, currency)
        if rate:
            return rate
        # Try nearby again after fetch
        for delta in range(1, 8):
            for direction in (-1, 1):
                nearby = (dt + timedelta(days=delta * direction)).strftime('%Y-%m-%d')
                rate = db.get_cached_rate(nearby, currency)
                if rate:
                    return rate
    except Exception as e:
        print(f"[exchange_rates] Failed to fetch rates: {e}")

    return None


def to_eur(amount, currency, date_str):
    """Convert an amount in a foreign currency to EUR using ECB rate."""
    if currency == 'EUR':
        return round(amount, 6)
    rate = get_rate(currency, date_str)
    if rate is None:
        return None
    return round(amount / rate, 6)


def ensure_rates_cached(year):
    """Ensure we have rates cached for a full year."""
    start = f"{year}-01-01"
    end = f"{year}-12-31"
    existing = db.get_cached_rates_bulk('USD', start, end)
    # If we have fewer than 200 trading days, fetch
    if len(existing) < 200:
        try:
            fetch_and_cache_rates(year=year)
        except Exception as e:
            print(f"[exchange_rates] Warning: could not fetch rates for {year}: {e}")
