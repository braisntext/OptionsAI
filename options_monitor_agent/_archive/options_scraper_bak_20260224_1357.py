""" Herramienta: Obtener datos de opciones usando yfinance """
import yfinance as yf
import pandas as pd
import numpy as np
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from config import AGENT_CONFIG


# MEFF ticker map: Yahoo ticker -> MEFF URL slug
MEFF_TICKERS = {
    "ACX.MC": "ACX_ACERINOX",
    "ACS.MC": "ACS_ACS",
    "ANA.MC": "ANA_ACCIONA",
    "BBVA.MC": "BBVA_BBVA",
    "BKT.MC": "BKT_BANKINTER",
    "CABK.MC": "CABK_CAIXABANK",
    "ELE.MC": "ELE_ENDESA",
    "ENG.MC": "ENG_ENAGAS",
    "FER.MC": "FER_FERROVIAL",
    "GRF.MC": "GRF_GRIFOLS",
    "IAG.MC": "IAG_IAG",
    "IBE.MC": "IBE_IBERDROLA",
    "IDR.MC": "IDR_INDRA",
    "ITX.MC": "ITX_INDITEX",
    "MAP.MC": "MAP_MAPFRE",
    "MEL.MC": "MEL_MELIA",
    "MTS.MC": "MTS_ARCELORMITTAL",
    "NTGY.MC": "NTGY_NATURGY",
    "REE.MC": "REE_REDELECTRICA",
    "REP.MC": "REP_REPSOL",
    "ROVI.MC": "ROVI_ROVI",
    "SAB.MC": "SAB_BANCSABADELL",
    "SAN.MC": "SAN_SANTANDER",
    "SOL.MC": "SOL_SOLARIA",
    "TEF.MC": "TEF_TELEFONICA",
    "UNI.MC": "UNI_UNICAJABANCO",
    "VIS.MC": "VIS_VISCOFAN",
}

def get_meff_options(ticker: str, current_price: float, stock_data: dict, historical_volatility: float) -> dict:
    """Obtiene opciones de MEFF via AllOrigins proxy para tickers espanoles."""
    meff_slug = MEFF_TICKERS.get(ticker)
    if not meff_slug:
        return None
    try:
        import subprocess as _sp, json as _json
        url = f"https://api.allorigins.win/get?url=https://www.meff.es/esp/Derivados-Financieros/Ficha/{meff_slug}"
        _res = _sp.run(["curl", "-s", "--max-time", "30", url], capture_output=True, text=True)
        if _res.returncode != 0:
            print(f" [MEFF] curl failed: {_res.stderr}")
            return None
        # Retry up to 3 times with increasing delay (handles AllOrigins 522 rate limit)
        import time as _time
        _html = ""
        for _attempt in range(3):
            _out = _res.stdout.strip() if _attempt == 0 else ""
            if _attempt > 0:
                _time.sleep(5 * _attempt)
                _res = _sp.run(["curl", "-s", "--max-time", "35", url], capture_output=True, text=True)
                _out = _res.stdout.strip()
            if not _out:
                continue
            try:
                _parsed = _json.loads(_out)
                _c = _parsed.get("contents", "")
                if _c and len(_c) > 1000:  # valid HTML page
                    _html = _c
                    break
                elif _parsed.get("status", {}).get("http_code", 0) >= 400:
                    print(f" [MEFF] AllOrigins error {_parsed.get('status')} for {ticker} (attempt {_attempt+1})")
                    continue
            except _json.JSONDecodeError:
                print(f" [MEFF] JSON error for {ticker} (attempt {_attempt+1}): {repr(_out[:60])}")
                continue
        if not _html:
            print(f" [MEFF] No valid content after 3 attempts for {ticker}")
            return None
        html = _html
        if not html:
            return None
        soup = BeautifulSoup(html, "html.parser")
        # Find expiration dates from the dropdown
        select = soup.find("select", {"id": "OpStrike"})
        expirations = []
        if select:
            for opt in select.find_all("option"):
                expirations.append(opt.get_text(strip=True))
        # Parse options table
        table = soup.find("table", {"id": "tblOpciones"})
        if not table:
            return None
        all_calls = []
        all_puts = []
        rows = table.find_all("tr")
        for row in rows:
            cells = row.find_all("td")
            if len(cells) < 13:
                continue
            # Columns: STRIKE, BUY_ORD, BUY_VOL, BUY_PRICE, SELL_PRICE, SELL_VOL, SELL_ORD, LAST, VOL, OPEN, MAX, MIN, ANT
            try:
                strike_txt = cells[0].get_text(strip=True).replace(",", ".")
                strike = float(strike_txt)
            except:
                continue
            buy_price_txt = cells[3].get_text(strip=True).replace(",", ".")
            sell_price_txt = cells[4].get_text(strip=True).replace(",", ".")
            ant_txt = cells[12].get_text(strip=True).replace(",", ".")
            try:
                buy_price = float(buy_price_txt) if buy_price_txt not in ["-", ""] else None
                sell_price = float(sell_price_txt) if sell_price_txt not in ["-", ""] else None
                last_price = float(ant_txt) if ant_txt not in ["-", ""] else None
            except:
                buy_price = sell_price = last_price = None
            # Compute implied volatility from mid price using Black-Scholes
            mid_price = None
            if buy_price and sell_price:
                mid_price = (buy_price + sell_price) / 2
            elif last_price:
                mid_price = last_price
            # Compute days to expiry
            _exp_str = expirations[0] if expirations else ""
            _days_to_expiry = 30
            if _exp_str:
                try:
                    from datetime import datetime as _dt
                    # MEFF format: "20/03/2026"
                    _exp_dt = _dt.strptime(_exp_str, "%d/%m/%Y")
                    _days_to_expiry = max(1, (_exp_dt - _dt.now()).days)
                except:
                    pass
            # Black-Scholes IV solver (Newton-Raphson)
            _iv = 0.0
            if mid_price and mid_price > 0 and current_price > 0 and strike > 0:
                try:
                    import math as _math
                    from scipy.stats import norm as _norm
                    _S = current_price
                    _K = strike
                    _T = _days_to_expiry / 365.0
                    _r = 0.03  # risk-free rate
                    _sigma = 0.3  # initial guess
                    for _ in range(50):
                        _d1 = (_math.log(_S/_K) + (_r + 0.5*_sigma**2)*_T) / (_sigma*_math.sqrt(_T))
                        _d2 = _d1 - _sigma*_math.sqrt(_T)
                        _price = _S*_norm.cdf(_d1) - _K*_math.exp(-_r*_T)*_norm.cdf(_d2)
                        _vega = _S*_norm.pdf(_d1)*_math.sqrt(_T)
                        if _vega < 1e-10:
                            break
                        _diff = _price - mid_price
                        _sigma -= _diff / _vega
                        if abs(_diff) < 1e-6:
                            break
                    if 0.01 < _sigma < 5.0:
                        _iv = round(_sigma, 4)
                except:
                    pass
            entry = {
                "strike": strike,
                "bid": buy_price,
                "ask": sell_price,
                "lastPrice": last_price,
                "impliedVolatility": _iv,
                "daysToExpiry": _days_to_expiry,
                "expiration": _exp_str,
                "type": "CALL",
                "source": "MEFF",
            }
            all_calls.append(entry)
        if not all_calls:
            return None
        calls_count = len(all_calls)
        pcr = round(len(all_puts) / calls_count, 4) if calls_count > 0 else 0
        return {
            "ticker": ticker,
            "current_price": current_price,
            "timestamp": datetime.now().isoformat(),
            "stock_data": stock_data,
            "historical_volatility": round(historical_volatility, 2),
            "expirations_analyzed": expirations,
            "calls": all_calls,
            "puts": all_puts,
            "calls_count": calls_count,
            "puts_count": len(all_puts),
            "put_call_ratio": pcr,
            "status": "success",
            "source": "MEFF",
        }
    except Exception as e:
        print(f" [MEFF] Error para {ticker}: {e}")
        return None

def get_options_data(ticker: str) -> dict:
    """Obtiene datos de opciones (calls y puts) para un ticker dado."""
    try:
        # Normalizar ticker para yfinance (ej: ENG.MC)
        stock = yf.Ticker(ticker)
        info = stock.info
        current_price = info.get("currentPrice") or info.get("regularMarketPrice", 0)

        stock_data = {
            "market_cap": info.get("market_cap", 0),
            "pe_ratio": info.get("trailingPE", 0),
            "52w_high": info.get("fiftyTwoWeekHigh", 0),
            "52w_low": info.get("fiftyTwoWeekLow", 0),
            "avg_volume": info.get("averageVolume", 0),
            "dividend_yield": info.get("dividendYield", 0),
            "beta": info.get("beta", 0),
        }

        hist = stock.history(period="30d")
        historical_volatility = 0
        if len(hist) > 1:
            log_returns = np.log(hist["Close"] / hist["Close"].shift(1)).dropna()
            historical_volatility = float(log_returns.std() * np.sqrt(252) * 100)

        expirations = stock.options

        # Fallback para tickers europeos si stock.options devuelve vacio
        if not expirations and ticker.endswith(".MC"):
             print(f" [!] Intento de fallback para {ticker}...")
             expirations = _fetch_expirations_from_yahoo_web(ticker)

        if not expirations:
            # Intentar MEFF para tickers espanoles
            if ticker.endswith(".MC") and ticker in MEFF_TICKERS:
                print(f" [MEFF] Intentando MEFF para {ticker}...")
                meff_result = get_meff_options(ticker, current_price, stock_data, historical_volatility)
                if meff_result:
                    print(f" [MEFF] OK: {meff_result['calls_count']} calls de MEFF")
                    # Guardar en cache local para fallback
                    try:
                        import os as _os_mc, json as _json_mc
                        _meff_cache_dir = "/home/braisn/options_monitor_agent/data/meff_cache"
                        _os_mc.makedirs(_meff_cache_dir, exist_ok=True)
                        _meff_cf = f"{_meff_cache_dir}/{ticker.replace('.', '_')}.json"
                        with open(_meff_cf, 'w') as _mcf:
                            _json_mc.dump(meff_result, _mcf)
                    except Exception:
                        pass
                    return meff_result
                print(f" [MEFF] Sin datos MEFF para {ticker}")
                # Intentar cache local si AllOrigins fallo
                try:
                    import os as _os_mc2, json as _json_mc2
                    _meff_cf2 = f"/home/braisn/options_monitor_agent/data/meff_cache/{ticker.replace('.', '_')}.json"
                    if _os_mc2.path.exists(_meff_cf2):
                        with open(_meff_cf2) as _mcf2:
                            _cached_meff = _json_mc2.load(_mcf2)
                        import datetime as _dt_mc
                        _cached_meff['timestamp'] = _dt_mc.datetime.now().isoformat()
                        _cached_meff['note'] = 'MEFF datos desde cache local'
                        print(f" [MEFF] Usando cache para {ticker}: {_cached_meff.get('calls_count',0)} calls")
                        return _cached_meff
                except Exception as _ce_mc:
                    print(f" [MEFF] Error cache: {_ce_mc}")
            # Para tickers europeos sin opciones (ej: .MC), devolver datos del stock sin error de opciones
            if ticker.endswith(".MC") or any(ticker.endswith(f".{sfx}") for sfx in ["L", "PA", "AS", "MI", "DE", "SW", "HE", "ST", "CO"]):
                return {
                    "ticker": ticker,
                    "current_price": current_price,
                    "timestamp": datetime.now().isoformat(),
                    "stock_data": stock_data,
                    "historical_volatility": round(historical_volatility, 2),
                    "expirations_analyzed": [],
                    "calls": [],
                    "puts": [],
                    "calls_count": 0,
                    "puts_count": 0,
                    "put_call_ratio": 0,
                    "status": "no_options",
                    "note": f"No hay opciones disponibles en Yahoo Finance para {ticker} (mercado europeo)"
                }
            return {"error": f"No options found for {ticker}", "ticker": ticker, "status": "error", "timestamp": datetime.now().isoformat()}

        max_date = datetime.now() + timedelta(weeks=AGENT_CONFIG["expiration_range_weeks"])
        valid_expirations = [
            exp for exp in expirations
            if datetime.strptime(exp, "%Y-%m-%d") <= max_date
        ]

        if not valid_expirations:
            valid_expirations = [expirations[0]]

        all_calls = []
        all_puts = []

        for exp_date in valid_expirations:
            try:
                opt_chain = stock.option_chain(exp_date)
                calls = opt_chain.calls.copy()
                calls["expiration"] = exp_date
                calls["type"] = "CALL"
                calls["daysToExpiry"] = (datetime.strptime(exp_date, "%Y-%m-%d") - datetime.now()).days
                all_calls.append(calls)

                puts = opt_chain.puts.copy()
                puts["expiration"] = exp_date
                puts["type"] = "PUT"
                puts["daysToExpiry"] = (datetime.strptime(exp_date, "%Y-%m-%d") - datetime.now()).days
                all_puts.append(puts)
            except Exception as e:
                print(f" Error fetching chain for {exp_date}: {e}")

        if not all_calls and not all_puts:
             return {"error": f"Options chains empty for {ticker}", "ticker": ticker, "status": "error", "timestamp": datetime.now().isoformat()}

        calls_df = pd.concat(all_calls, ignore_index=True) if all_calls else pd.DataFrame()
        puts_df = pd.concat(all_puts, ignore_index=True) if all_puts else pd.DataFrame()

        price_range = current_price * 0.15
        def filter_near_money(df, price):
            if df.empty: return df
            return df[
                (df["strike"] >= price - price_range) &
                (df["strike"] <= price + price_range)
            ]

        calls_filtered = filter_near_money(calls_df, current_price)
        puts_filtered = filter_near_money(puts_df, current_price)

        return {
            "ticker": ticker,
            "current_price": current_price,
            "timestamp": datetime.now().isoformat(),
            "stock_data": stock_data,
            "historical_volatility": round(historical_volatility, 2),
            "expirations_analyzed": valid_expirations,
            "calls": _df_to_detailed(calls_filtered),
            "puts": _df_to_detailed(puts_filtered),
            "calls_raw_df": calls_filtered,
            "puts_raw_df": puts_filtered,
            "calls_count": len(calls_filtered),
            "puts_count": len(puts_filtered),
            "put_call_ratio": len(puts_filtered) / max(len(calls_filtered), 1),
            "status": "success"
        }
    except Exception as e:
        return {
            "ticker": ticker,
            "error": str(e),
            "status": "error",
            "timestamp": datetime.now().isoformat()
        }

def _fetch_expirations_from_yahoo_web(ticker: str) -> list:
    """Intenta obtener fechas de expiracion directamente de Yahoo Finance web."""
    url = f"https://query1.finance.yahoo.com/v7/finance/options/{ticker}"
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        r = requests.get(url, headers=headers, timeout=10)
        data = r.json()
        timestamps = data['optionChain']['result'][0]['expirationDates']
        return [datetime.fromtimestamp(ts).strftime('%Y-%m-%d') for ts in timestamps]
    except Exception as e:
        print(f" Fallback failed: {e}")
        return []

def _df_to_detailed(df: pd.DataFrame) -> list:
    """Convierte DataFrame a lista de diccionarios."""
    if df.empty: return []
    columns = [
        "contractSymbol", "strike", "lastPrice", "bid", "ask",
        "change", "percentChange", "volume", "openInterest",
        "impliedVolatility", "inTheMoney", "expiration", "type", "daysToExpiry"
    ]
    available_cols = [c for c in columns if c in df.columns]
    summary = df[available_cols].head(30)
    result = []
    for _, row in summary.iterrows():
        entry = {}
        for col in available_cols:
            val = row[col]
            if pd.isna(val): entry[col] = None
            elif isinstance(val, bool): entry[col] = bool(val)
            elif isinstance(val, (np.integer,)): entry[col] = int(val)
            elif isinstance(val, (np.floating, float)): entry[col] = round(float(val), 4)
            else: entry[col] = str(val)
        result.append(entry)
    return result

def get_multiple_options(tickers: list) -> list:
    """Obtiene datos de opciones para multiples tickers."""
    import time as _tmeff
    results = []
    meff_done = 0
    for ticker in tickers:
        if ticker.endswith(".MC") and ticker in MEFF_TICKERS and meff_done > 0:
            print(f"[MEFF] Pausa 20s entre tickers MEFF para evitar rate-limit...")
            _tmeff.sleep(20)
        print(f" 📡 Obteniendo opciones de {ticker}...")
        data = get_options_data(ticker)
        if ticker.endswith(".MC") and ticker in MEFF_TICKERS:
            meff_done += 1
        results.append(data)
    return results
