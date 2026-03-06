#!/usr/bin/env python3
"""
🤖 Options Monitor Agent v2.0 - Generador Automático del Proyecto
Ejecuta: python setup_project.py
"""

import os

PROJECT_NAME = "options_monitor_agent"

# ============================================================
# DEFINICIÓN DE TODOS LOS ARCHIVOS
# ============================================================

FILES = {}

# ============================================================
# requirements.txt
# ============================================================
FILES["requirements.txt"] = """# === Core ===
anthropic>=0.30.0
python-dotenv>=1.0.0

# === Data ===
yfinance>=0.2.31
pandas>=2.1.0
numpy>=1.26.0

# === Visualization ===
matplotlib>=3.8.0
plotly>=5.18.0
rich>=13.6.0

# === Greeks ===
scipy>=1.11.0

# === Database ===
sqlalchemy>=2.0.0

# === Scheduling ===
schedule>=1.2.0

# === Notifications ===
python-telegram-bot>=20.6
aiohttp>=3.9.0

# === Dashboard ===
flask>=3.0.0
flask-socketio>=5.3.0

# === Backtesting ===
tabulate>=0.9.0
"""

# ============================================================
# .env.example
# ============================================================
FILES[".env.example"] = """# === Required ===
ANTHROPIC_API_KEY=sk-ant-xxxxx

# === Optional: Telegram Notifications ===
TELEGRAM_BOT_TOKEN=123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11
TELEGRAM_CHAT_ID=123456789

# === Optional: Email Notifications ===
EMAIL_ADDRESS=tu_email@gmail.com
EMAIL_PASSWORD=tu_app_password
EMAIL_SMTP_SERVER=smtp.gmail.com
EMAIL_SMTP_PORT=587
EMAIL_RECIPIENTS=destinatario1@email.com,destinatario2@email.com

# === Optional: Database ===
DATABASE_URL=sqlite:///memory/options_monitor.db
"""

# ============================================================
# config.py
# ============================================================
FILES["config.py"] = '''"""
Configuración central del agente de monitoreo de opciones.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ============================================================
# API KEYS
# ============================================================
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS", "")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "")
EMAIL_SMTP_SERVER = os.getenv("EMAIL_SMTP_SERVER", "smtp.gmail.com")
EMAIL_SMTP_PORT = int(os.getenv("EMAIL_SMTP_PORT", "587"))
EMAIL_RECIPIENTS = os.getenv("EMAIL_RECIPIENTS", "").split(",")

# ============================================================
# WATCHLIST
# ============================================================
WATCHLIST = [
    "AAPL",   # Apple
    "MSFT",   # Microsoft
    "GOOGL",  # Alphabet
    "AMZN",   # Amazon
    "TSLA",   # Tesla
    "NVDA",   # NVIDIA
    "META",   # Meta
    "SPY",    # S&P 500 ETF
    "AMD",    # AMD
    "PLTR",   # Palantir
]

# ============================================================
# AGENT CONFIG
# ============================================================
AGENT_CONFIG = {
    "model": "claude-sonnet-4-20250514",
    "max_tokens": 4096,
    "temperature": 0.3,
    "monitor_interval_minutes": 15,
    "alert_threshold_percent": 5.0,
    "expiration_range_weeks": 6,
}

# ============================================================
# GREEKS CONFIG
# ============================================================
GREEKS_CONFIG = {
    "risk_free_rate": 0.053,
    "dividend_yield": 0.013,
    "trading_days_per_year": 252,
}

# ============================================================
# NOTIFICATION CONFIG
# ============================================================
NOTIFICATION_CONFIG = {
    "enable_email": bool(EMAIL_ADDRESS and EMAIL_PASSWORD),
    "enable_telegram": bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID),
    "notify_on_high_iv": True,
    "notify_on_unusual_volume": True,
    "notify_on_pcr_extreme": True,
    "notify_on_significant_change": True,
    "unusual_volume_threshold": 3.0,
}

# ============================================================
# DATABASE CONFIG
# ============================================================
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///memory/options_monitor.db")

# ============================================================
# DASHBOARD CONFIG
# ============================================================
DASHBOARD_CONFIG = {
    "host": "0.0.0.0",
    "port": 5000,
    "debug": False,
}

# ============================================================
# BACKTESTING CONFIG
# ============================================================
BACKTEST_CONFIG = {
    "lookback_days": 30,
    "signal_types": ["HIGH_IV", "HIGH_PUT_CALL_RATIO", "LOW_PUT_CALL_RATIO", "UNUSUAL_VOLUME"],
    "results_dir": "backtest_results",
}

# ============================================================
# PATHS
# ============================================================
REPORTS_DIR = "reports"
MEMORY_FILE = "memory/history.json"
'''

# ============================================================
# tools/__init__.py
# ============================================================
FILES["tools/__init__.py"] = '''from .options_scraper import get_options_data, get_multiple_options
from .analysis_tool import analyze_options_data, generate_report_chart
from .greeks_calculator import GreeksCalculator
from .notification_tool import display_analysis
from .email_notifier import EmailNotifier
from .telegram_notifier import TelegramNotifier
from .backtester import Backtester
'''

# ============================================================
# tools/options_scraper.py
# ============================================================
FILES["tools/options_scraper.py"] = '''"""
Herramienta: Obtener datos de opciones usando yfinance
"""

import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from config import AGENT_CONFIG


def get_options_data(ticker: str) -> dict:
    """Obtiene datos de opciones (calls y puts) para un ticker dado."""
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        current_price = info.get("currentPrice") or info.get("regularMarketPrice", 0)

        stock_data = {
            "market_cap": info.get("marketCap", 0),
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
        if not expirations:
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

        calls_df = pd.concat(all_calls, ignore_index=True) if all_calls else pd.DataFrame()
        puts_df = pd.concat(all_puts, ignore_index=True) if all_puts else pd.DataFrame()

        price_range = current_price * 0.15

        def filter_near_money(df, price):
            if df.empty:
                return df
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


def _df_to_detailed(df: pd.DataFrame) -> list:
    """Convierte DataFrame a lista de diccionarios."""
    if df.empty:
        return []

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
            if pd.isna(val):
                entry[col] = None
            elif isinstance(val, bool):
                entry[col] = bool(val)
            elif isinstance(val, (np.integer,)):
                entry[col] = int(val)
            elif isinstance(val, (np.floating, float)):
                entry[col] = round(float(val), 4)
            else:
                entry[col] = str(val)
        result.append(entry)

    return result


def get_multiple_options(tickers: list) -> list:
    """Obtiene datos de opciones para multiples tickers."""
    results = []
    for ticker in tickers:
        print(f"  📡 Obteniendo opciones de {ticker}...")
        data = get_options_data(ticker)
        results.append(data)
    return results
'''

# ============================================================
# tools/greeks_calculator.py
# ============================================================
FILES["tools/greeks_calculator.py"] = '''"""
Herramienta: Calculo de Greeks (Delta, Gamma, Theta, Vega, Rho)
"""

import numpy as np
from scipy.stats import norm
from config import GREEKS_CONFIG


class GreeksCalculator:
    """Calcula las Greeks usando Black-Scholes."""

    def __init__(self):
        self.r = GREEKS_CONFIG["risk_free_rate"]
        self.q = GREEKS_CONFIG["dividend_yield"]
        self.trading_days = GREEKS_CONFIG["trading_days_per_year"]

    def calculate_all_greeks(self, S, K, T, sigma, option_type="call"):
        """Calcula todas las Greeks para una opcion."""
        if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
            return self._empty_greeks()

        try:
            d1 = self._d1(S, K, T, sigma)
            d2 = self._d2(d1, sigma, T)

            if option_type.lower() == "call":
                delta = np.exp(-self.q * T) * norm.cdf(d1)
                theta = self._call_theta(S, K, T, sigma, d1, d2)
                rho = K * T * np.exp(-self.r * T) * norm.cdf(d2)
                price = S * np.exp(-self.q * T) * norm.cdf(d1) - K * np.exp(-self.r * T) * norm.cdf(d2)
            else:
                delta = np.exp(-self.q * T) * (norm.cdf(d1) - 1)
                theta = self._put_theta(S, K, T, sigma, d1, d2)
                rho = -K * T * np.exp(-self.r * T) * norm.cdf(-d2)
                price = K * np.exp(-self.r * T) * norm.cdf(-d2) - S * np.exp(-self.q * T) * norm.cdf(-d1)

            gamma = norm.pdf(d1) * np.exp(-self.q * T) / (S * sigma * np.sqrt(T))
            vega = S * np.exp(-self.q * T) * np.sqrt(T) * norm.pdf(d1)

            return {
                "delta": round(float(delta), 4),
                "gamma": round(float(gamma), 6),
                "theta": round(float(theta / self.trading_days), 4),
                "vega": round(float(vega / 100), 4),
                "rho": round(float(rho / 100), 4),
                "theoretical_price": round(float(price), 4),
                "d1": round(float(d1), 4),
                "d2": round(float(d2), 4),
            }
        except Exception as e:
            return self._empty_greeks(error=str(e))

    def _d1(self, S, K, T, sigma):
        return (np.log(S / K) + (self.r - self.q + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))

    def _d2(self, d1, sigma, T):
        return d1 - sigma * np.sqrt(T)

    def _call_theta(self, S, K, T, sigma, d1, d2):
        t1 = -(S * np.exp(-self.q * T) * norm.pdf(d1) * sigma) / (2 * np.sqrt(T))
        t2 = -self.r * K * np.exp(-self.r * T) * norm.cdf(d2)
        t3 = self.q * S * np.exp(-self.q * T) * norm.cdf(d1)
        return t1 + t2 + t3

    def _put_theta(self, S, K, T, sigma, d1, d2):
        t1 = -(S * np.exp(-self.q * T) * norm.pdf(d1) * sigma) / (2 * np.sqrt(T))
        t2 = self.r * K * np.exp(-self.r * T) * norm.cdf(-d2)
        t3 = -self.q * S * np.exp(-self.q * T) * norm.cdf(-d1)
        return t1 + t2 + t3

    def _empty_greeks(self, error=None):
        result = {"delta": 0, "gamma": 0, "theta": 0, "vega": 0, "rho": 0, "theoretical_price": 0, "d1": 0, "d2": 0}
        if error:
            result["error"] = error
        return result

    def enrich_options_with_greeks(self, options_data):
        """Enriquece datos de opciones con Greeks."""
        if options_data.get("status") != "success":
            return options_data

        S = options_data["current_price"]

        for opt_list, opt_type in [(options_data["calls"], "call"), (options_data["puts"], "put")]:
            for opt in opt_list:
                K = opt.get("strike", 0)
                iv = opt.get("impliedVolatility", 0)
                days = opt.get("daysToExpiry", 0)
                T = max(days, 1) / 365.0

                if K and iv and iv > 0:
                    greeks = self.calculate_all_greeks(S, K, T, iv, opt_type)
                    opt["greeks"] = greeks
                else:
                    opt["greeks"] = self._empty_greeks()

        return options_data

    def calculate_portfolio_greeks(self, positions):
        """Calcula Greeks agregados de un portafolio."""
        total = {"delta": 0, "gamma": 0, "theta": 0, "vega": 0, "rho": 0}
        for pos in positions:
            greeks = self.calculate_all_greeks(
                S=pos["S"], K=pos["strike"],
                T=max(pos.get("days_to_expiry", 1), 1) / 365.0,
                sigma=pos["iv"], option_type=pos["type"]
            )
            qty = pos.get("quantity", 1) * 100
            for greek in total:
                total[greek] += greeks[greek] * qty
        return {k: round(v, 4) for k, v in total.items()}
'''

# ============================================================
# tools/analysis_tool.py
# ============================================================
FILES["tools/analysis_tool.py"] = '''"""
Herramienta: Analisis avanzado de datos de opciones
"""

import json
import pandas as pd
import numpy as np
from datetime import datetime
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import os
from config import REPORTS_DIR, NOTIFICATION_CONFIG


def analyze_options_data(options_data):
    """Analisis completo de opciones."""
    analysis = {
        "timestamp": datetime.now().isoformat(),
        "tickers_analyzed": [],
        "alerts": [],
        "summary": {},
        "market_sentiment": "",
        "unusual_activity": [],
        "greeks_summary": {},
    }

    total_put_volume = 0
    total_call_volume = 0

    for data in options_data:
        if data.get("status") == "error":
            analysis["alerts"].append({
                "type": "ERROR", "ticker": data.get("ticker", "UNKNOWN"),
                "message": data.get("error", "Unknown error"), "severity": "high"
            })
            continue

        ticker = data["ticker"]
        analysis["tickers_analyzed"].append(ticker)

        calls = data.get("calls", [])
        puts = data.get("puts", [])

        call_volume = sum(c.get("volume", 0) or 0 for c in calls)
        put_volume = sum(p.get("volume", 0) or 0 for p in puts)
        call_oi = sum(c.get("openInterest", 0) or 0 for c in calls)
        put_oi = sum(p.get("openInterest", 0) or 0 for p in puts)

        total_put_volume += put_volume
        total_call_volume += call_volume

        call_ivs = [c.get("impliedVolatility", 0) for c in calls if c.get("impliedVolatility")]
        put_ivs = [p.get("impliedVolatility", 0) for p in puts if p.get("impliedVolatility")]

        avg_call_iv = _safe_avg(call_ivs)
        avg_put_iv = _safe_avg(put_ivs)
        iv_skew = avg_put_iv - avg_call_iv

        greeks_agg = _aggregate_greeks(calls, puts)
        unusual = _detect_unusual_activity(calls + puts, ticker)
        analysis["unusual_activity"].extend(unusual)

        ticker_summary = {
            "current_price": data.get("current_price", 0),
            "historical_volatility": data.get("historical_volatility", 0),
            "stock_data": data.get("stock_data", {}),
            "call_volume": call_volume,
            "put_volume": put_volume,
            "total_volume": call_volume + put_volume,
            "call_open_interest": call_oi,
            "put_open_interest": put_oi,
            "put_call_ratio_volume": put_volume / max(call_volume, 1),
            "put_call_ratio_oi": put_oi / max(call_oi, 1),
            "avg_call_iv": round(avg_call_iv * 100, 2),
            "avg_put_iv": round(avg_put_iv * 100, 2),
            "max_call_iv": round(max(call_ivs) * 100, 2) if call_ivs else 0,
            "max_put_iv": round(max(put_ivs) * 100, 2) if put_ivs else 0,
            "iv_skew": round(iv_skew * 100, 2),
            "expirations": data.get("expirations_analyzed", []),
            "most_active_call": _get_most_active(calls),
            "most_active_put": _get_most_active(puts),
            "highest_oi_call": _get_highest_oi(calls),
            "highest_oi_put": _get_highest_oi(puts),
            "greeks": greeks_agg,
        }

        analysis["summary"][ticker] = ticker_summary
        _generate_alerts(ticker, ticker_summary, analysis["alerts"])

    overall_pcr = total_put_volume / max(total_call_volume, 1)
    if overall_pcr > 1.2:
        analysis["market_sentiment"] = "BEARISH 🐻"
    elif overall_pcr < 0.8:
        analysis["market_sentiment"] = "BULLISH 🐂"
    else:
        analysis["market_sentiment"] = "NEUTRAL 😐"

    analysis["overall_put_call_ratio"] = round(overall_pcr, 3)
    analysis["total_call_volume"] = total_call_volume
    analysis["total_put_volume"] = total_put_volume

    return analysis


def _aggregate_greeks(calls, puts):
    call_deltas = [c["greeks"]["delta"] for c in calls if "greeks" in c and c["greeks"].get("delta")]
    put_deltas = [p["greeks"]["delta"] for p in puts if "greeks" in p and p["greeks"].get("delta")]
    gammas = [o["greeks"]["gamma"] for o in calls + puts if "greeks" in o and o["greeks"].get("gamma")]
    thetas = [o["greeks"]["theta"] for o in calls + puts if "greeks" in o and o["greeks"].get("theta")]
    vegas = [o["greeks"]["vega"] for o in calls + puts if "greeks" in o and o["greeks"].get("vega")]
    return {
        "avg_delta_calls": round(_safe_avg(call_deltas), 4),
        "avg_delta_puts": round(_safe_avg(put_deltas), 4),
        "avg_gamma": round(_safe_avg(gammas), 6),
        "avg_theta": round(_safe_avg(thetas), 4),
        "avg_vega": round(_safe_avg(vegas), 4),
    }


def _detect_unusual_activity(options, ticker):
    unusual = []
    threshold = NOTIFICATION_CONFIG["unusual_volume_threshold"]
    for opt in options:
        vol = opt.get("volume", 0) or 0
        oi = opt.get("openInterest", 0) or 0
        if oi > 0 and vol > 0 and vol / oi >= threshold:
            unusual.append({
                "ticker": ticker, "type": opt.get("type", ""),
                "strike": opt.get("strike", 0), "expiration": opt.get("expiration", ""),
                "volume": vol, "open_interest": oi,
                "vol_oi_ratio": round(vol / oi, 2),
                "last_price": opt.get("lastPrice", 0),
                "implied_volatility": round((opt.get("impliedVolatility", 0) or 0) * 100, 2),
            })
    return sorted(unusual, key=lambda x: x["vol_oi_ratio"], reverse=True)[:5]


def _generate_alerts(ticker, summary, alerts):
    if summary["avg_call_iv"] > 50 or summary["avg_put_iv"] > 50:
        alerts.append({"type": "HIGH_IV", "ticker": ticker,
            "message": f"IV alta - Calls: {summary['avg_call_iv']:.1f}%, Puts: {summary['avg_put_iv']:.1f}%",
            "severity": "medium"})

    pcr = summary["put_call_ratio_volume"]
    if pcr > 1.5:
        alerts.append({"type": "HIGH_PUT_CALL_RATIO", "ticker": ticker,
            "message": f"P/C ratio alto: {pcr:.2f} - Sentimiento bajista fuerte", "severity": "high"})
    elif pcr < 0.4 and pcr > 0:
        alerts.append({"type": "LOW_PUT_CALL_RATIO", "ticker": ticker,
            "message": f"P/C ratio bajo: {pcr:.2f} - Sentimiento alcista fuerte", "severity": "medium"})

    if abs(summary["iv_skew"]) > 10:
        direction = "Puts mas caros" if summary["iv_skew"] > 0 else "Calls mas caros"
        alerts.append({"type": "IV_SKEW", "ticker": ticker,
            "message": f"IV Skew: {summary['iv_skew']:.1f}% ({direction})", "severity": "medium"})

    hv = summary.get("historical_volatility", 0)
    avg_iv = (summary["avg_call_iv"] + summary["avg_put_iv"]) / 2
    if hv > 0 and avg_iv > 0:
        iv_hv_ratio = avg_iv / hv
        if iv_hv_ratio > 1.5:
            alerts.append({"type": "IV_PREMIUM", "ticker": ticker,
                "message": f"IV >> HV: IV={avg_iv:.1f}% vs HV={hv:.1f}% (ratio: {iv_hv_ratio:.2f})",
                "severity": "medium"})


def generate_report_chart(analysis):
    """Genera graficos con Matplotlib."""
    os.makedirs(REPORTS_DIR, exist_ok=True)
    tickers = list(analysis["summary"].keys())
    if not tickers:
        return ""

    fig, axes = plt.subplots(2, 2, figsize=(20, 14))
    fig.suptitle(f"Options Monitor Report - {analysis['timestamp'][:19]}", fontsize=16, fontweight="bold")
    summary = analysis["summary"]

    call_ivs = [summary[t]["avg_call_iv"] for t in tickers]
    put_ivs = [summary[t]["avg_put_iv"] for t in tickers]
    hvs = [summary[t].get("historical_volatility", 0) for t in tickers]
    x = np.arange(len(tickers))
    width = 0.25

    axes[0, 0].bar(x - width, call_ivs, width, label="Call IV%", color="#2ecc71", alpha=0.8)
    axes[0, 0].bar(x, put_ivs, width, label="Put IV%", color="#e74c3c", alpha=0.8)
    axes[0, 0].bar(x + width, hvs, width, label="HV%", color="#3498db", alpha=0.8)
    axes[0, 0].set_xticks(x); axes[0, 0].set_xticklabels(tickers, rotation=45)
    axes[0, 0].set_title("Implied vs Historical Volatility"); axes[0, 0].legend(); axes[0, 0].grid(axis="y", alpha=0.3)

    pcrs = [summary[t]["put_call_ratio_volume"] for t in tickers]
    colors = ["#e74c3c" if p > 1.2 else "#2ecc71" if p < 0.8 else "#f39c12" for p in pcrs]
    axes[0, 1].bar(tickers, pcrs, color=colors)
    axes[0, 1].axhline(y=1.0, color="gray", linestyle="--", alpha=0.7)
    axes[0, 1].set_title("Put/Call Ratio (Volume)"); axes[0, 1].tick_params(axis="x", rotation=45); axes[0, 1].grid(axis="y", alpha=0.3)

    call_vols = [summary[t]["call_volume"] for t in tickers]
    put_vols = [summary[t]["put_volume"] for t in tickers]
    axes[1, 0].bar(x - 0.2, call_vols, 0.4, label="Call Volume", color="#2ecc71", alpha=0.8)
    axes[1, 0].bar(x + 0.2, put_vols, 0.4, label="Put Volume", color="#e74c3c", alpha=0.8)
    axes[1, 0].set_xticks(x); axes[1, 0].set_xticklabels(tickers, rotation=45)
    axes[1, 0].set_title("Options Volume"); axes[1, 0].legend(); axes[1, 0].grid(axis="y", alpha=0.3)

    skews = [summary[t]["iv_skew"] for t in tickers]
    skew_colors = ["#e74c3c" if s > 0 else "#2ecc71" for s in skews]
    axes[1, 1].barh(tickers, skews, color=skew_colors)
    axes[1, 1].axvline(x=0, color="gray", linestyle="--", alpha=0.7)
    axes[1, 1].set_title("IV Skew (Put IV - Call IV)"); axes[1, 1].grid(axis="x", alpha=0.3)

    plt.tight_layout()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = os.path.join(REPORTS_DIR, f"options_report_{timestamp}.png")
    plt.savefig(filepath, dpi=150, bbox_inches="tight"); plt.close()
    return filepath


def generate_interactive_chart(analysis):
    """Genera grafico interactivo con Plotly."""
    try:
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
    except ImportError:
        return ""

    os.makedirs(REPORTS_DIR, exist_ok=True)
    tickers = list(analysis["summary"].keys())
    if not tickers:
        return ""

    summary = analysis["summary"]
    fig = make_subplots(rows=2, cols=2,
        subplot_titles=("Implied Volatility", "Put/Call Ratio", "Volume", "IV Skew"))

    fig.add_trace(go.Bar(name="Call IV", x=tickers, y=[summary[t]["avg_call_iv"] for t in tickers], marker_color="#2ecc71"), row=1, col=1)
    fig.add_trace(go.Bar(name="Put IV", x=tickers, y=[summary[t]["avg_put_iv"] for t in tickers], marker_color="#e74c3c"), row=1, col=1)

    pcrs = [summary[t]["put_call_ratio_volume"] for t in tickers]
    fig.add_trace(go.Bar(name="P/C Ratio", x=tickers, y=pcrs,
        marker_color=["#e74c3c" if p > 1.2 else "#2ecc71" if p < 0.8 else "#f39c12" for p in pcrs]), row=1, col=2)

    fig.add_trace(go.Bar(name="Call Vol", x=tickers, y=[summary[t]["call_volume"] for t in tickers], marker_color="#2ecc71"), row=2, col=1)
    fig.add_trace(go.Bar(name="Put Vol", x=tickers, y=[summary[t]["put_volume"] for t in tickers], marker_color="#e74c3c"), row=2, col=1)

    fig.add_trace(go.Bar(name="IV Skew", x=tickers, y=[summary[t]["iv_skew"] for t in tickers], marker_color="#3498db"), row=2, col=2)

    fig.update_layout(height=800, title_text=f"Options Monitor - {analysis['timestamp'][:19]}")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = os.path.join(REPORTS_DIR, f"interactive_report_{timestamp}.html")
    fig.write_html(filepath)
    return filepath


def _safe_avg(values):
    clean = [v for v in values if v and v > 0]
    return sum(clean) / len(clean) if clean else 0.0

def _get_most_active(options):
    if not options: return {}
    top = sorted(options, key=lambda x: x.get("volume", 0) or 0, reverse=True)[0]
    return {k: top.get(k) for k in ["strike", "lastPrice", "volume", "openInterest", "expiration", "impliedVolatility"]}

def _get_highest_oi(options):
    if not options: return {}
    top = sorted(options, key=lambda x: x.get("openInterest", 0) or 0, reverse=True)[0]
    return {k: top.get(k) for k in ["strike", "lastPrice", "volume", "openInterest", "expiration", "impliedVolatility"]}
'''

# ============================================================
# tools/notification_tool.py
# ============================================================
FILES["tools/notification_tool.py"] = '''"""
Herramienta: Visualizacion en terminal con Rich
"""

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box
from datetime import datetime

console = Console()


def display_analysis(analysis, chart_path=""):
    """Muestra el analisis completo en terminal."""
    timestamp = analysis.get("timestamp", datetime.now().isoformat())

    console.print()
    console.print(Panel(
        f"[bold cyan]📊 MONITOR DE OPCIONES - REPORTE[/bold cyan]\\n"
        f"[dim]{timestamp}[/dim]\\n"
        f"Sentimiento: [bold]{analysis.get('market_sentiment', 'N/A')}[/bold]\\n"
        f"P/C Ratio: [bold]{analysis.get('overall_put_call_ratio', 'N/A')}[/bold]\\n"
        f"Vol Total - Calls: {analysis.get('total_call_volume', 0):,} | Puts: {analysis.get('total_put_volume', 0):,}",
        box=box.DOUBLE_EDGE, border_style="cyan"
    ))

    # Main table
    table = Table(title="Resumen por Ticker", box=box.ROUNDED, show_lines=True, border_style="blue")
    table.add_column("Ticker", style="bold cyan", justify="center")
    table.add_column("Precio", style="green", justify="right")
    table.add_column("Call Vol", justify="right")
    table.add_column("Put Vol", justify="right")
    table.add_column("P/C Vol", justify="center")
    table.add_column("Call IV%", justify="right")
    table.add_column("Put IV%", justify="right")
    table.add_column("HV%", justify="right")
    table.add_column("IV Skew", justify="center")

    for ticker, data in analysis.get("summary", {}).items():
        pcr = data.get("put_call_ratio_volume", 0)
        pcr_s = f"[bold red]{pcr:.2f}🐻[/bold red]" if pcr > 1.2 else f"[bold green]{pcr:.2f}🐂[/bold green]" if pcr < 0.8 else f"[yellow]{pcr:.2f}[/yellow]"
        skew = data.get("iv_skew", 0)
        skew_s = f"[red]{skew:+.1f}[/red]" if skew > 5 else f"[green]{skew:+.1f}[/green]" if skew < -5 else f"{skew:+.1f}"

        table.add_row(ticker, f"${data.get('current_price', 0):,.2f}",
            f"{data.get('call_volume', 0):,}", f"{data.get('put_volume', 0):,}",
            pcr_s, f"{data.get('avg_call_iv', 0):.1f}%", f"{data.get('avg_put_iv', 0):.1f}%",
            f"{data.get('historical_volatility', 0):.1f}%", skew_s)
    console.print(table)

    # Greeks table
    g_table = Table(title="📐 Greeks Promedio", box=box.ROUNDED, border_style="magenta")
    g_table.add_column("Ticker", style="bold")
    g_table.add_column("Delta Calls", justify="right")
    g_table.add_column("Delta Puts", justify="right")
    g_table.add_column("Gamma", justify="right")
    g_table.add_column("Theta", justify="right")
    g_table.add_column("Vega", justify="right")

    for ticker, data in analysis.get("summary", {}).items():
        g = data.get("greeks", {})
        g_table.add_row(ticker, f"{g.get('avg_delta_calls', 0):.4f}",
            f"{g.get('avg_delta_puts', 0):.4f}", f"{g.get('avg_gamma', 0):.6f}",
            f"{g.get('avg_theta', 0):.4f}", f"{g.get('avg_vega', 0):.4f}")
    console.print(g_table)

    # Unusual activity
    unusual = analysis.get("unusual_activity", [])
    if unusual:
        u_table = Table(title="🔥 Actividad Inusual", box=box.ROUNDED, border_style="yellow")
        u_table.add_column("Ticker", style="bold")
        u_table.add_column("Tipo", justify="center")
        u_table.add_column("Strike", justify="right")
        u_table.add_column("Exp", justify="center")
        u_table.add_column("Volume", justify="right")
        u_table.add_column("OI", justify="right")
        u_table.add_column("Vol/OI", justify="center", style="bold red")
        u_table.add_column("IV%", justify="right")

        for u in unusual[:10]:
            u_table.add_row(u["ticker"], f"{'📗 CALL' if u['type'] == 'CALL' else '📕 PUT'}",
                f"${u['strike']:,.2f}", u["expiration"], f"{u['volume']:,}",
                f"{u['open_interest']:,}", f"{u['vol_oi_ratio']:.1f}x", f"{u['implied_volatility']:.1f}%")
        console.print(u_table)

    # Alerts
    alerts = analysis.get("alerts", [])
    if alerts:
        console.print()
        console.print("[bold red]⚠️  ALERTAS:[/bold red]")
        for alert in alerts:
            icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(alert.get("severity", "medium"), "🟡")
            console.print(f"  {icon} [{alert.get('ticker', '')}] {alert.get('message', '')}")

    if chart_path:
        console.print(f"\\n📈 Grafico: [bold blue]{chart_path}[/bold blue]")
'''

# ============================================================
# tools/email_notifier.py
# ============================================================
FILES["tools/email_notifier.py"] = '''"""
Herramienta: Notificaciones por Email
"""

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
from datetime import datetime
import os
from config import (EMAIL_ADDRESS, EMAIL_PASSWORD, EMAIL_SMTP_SERVER,
                    EMAIL_SMTP_PORT, EMAIL_RECIPIENTS, NOTIFICATION_CONFIG)


class EmailNotifier:
    def __init__(self):
        self.enabled = NOTIFICATION_CONFIG["enable_email"]
        self.sender = EMAIL_ADDRESS
        self.password = EMAIL_PASSWORD
        self.smtp_server = EMAIL_SMTP_SERVER
        self.smtp_port = EMAIL_SMTP_PORT
        self.recipients = [r.strip() for r in EMAIL_RECIPIENTS if r.strip()]

    def send_report(self, analysis, chart_path=""):
        if not self.enabled:
            print("  📧 Email deshabilitado")
            return False
        try:
            subject = f"📊 Options Report - {analysis.get('market_sentiment', 'N/A')} - {datetime.now().strftime('%Y-%m-%d %H:%M')}"
            html_body = self._build_html(analysis)
            msg = MIMEMultipart("related")
            msg["Subject"] = subject
            msg["From"] = self.sender
            msg["To"] = ", ".join(self.recipients)
            msg.attach(MIMEText(html_body, "html"))

            if chart_path and os.path.exists(chart_path):
                with open(chart_path, "rb") as f:
                    img = MIMEImage(f.read())
                    img.add_header("Content-Disposition", "attachment", filename=os.path.basename(chart_path))
                    msg.attach(img)

            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls()
                server.login(self.sender, self.password)
                server.sendmail(self.sender, self.recipients, msg.as_string())
            print(f"  📧 Email enviado a {len(self.recipients)} destinatarios")
            return True
        except Exception as e:
            print(f"  ❌ Error email: {e}")
            return False

    def send_alert(self, alerts):
        if not self.enabled or not alerts:
            return False
        high = [a for a in alerts if a.get("severity") == "high"]
        if not high:
            return False
        try:
            body = "<h2>🚨 Alertas Criticas</h2><ul>"
            for a in high:
                body += f"<li><strong>[{a['ticker']}]</strong> {a['message']}</li>"
            body += "</ul>"
            msg = MIMEText(body, "html")
            msg["Subject"] = f"🚨 OPTIONS ALERT - {len(high)} alertas"
            msg["From"] = self.sender
            msg["To"] = ", ".join(self.recipients)
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls()
                server.login(self.sender, self.password)
                server.sendmail(self.sender, self.recipients, msg.as_string())
            return True
        except Exception as e:
            print(f"  ❌ Error alert email: {e}")
            return False

    def _build_html(self, analysis):
        summary = analysis.get("summary", {})
        rows = ""
        for ticker, data in summary.items():
            pcr = data.get("put_call_ratio_volume", 0)
            c = "#e74c3c" if pcr > 1.2 else "#27ae60" if pcr < 0.8 else "#f39c12"
            rows += f"<tr><td><b>{ticker}</b></td><td>${data.get('current_price',0):,.2f}</td>"
            rows += f"<td>{data.get('call_volume',0):,}</td><td>{data.get('put_volume',0):,}</td>"
            rows += f"<td style=\\"color:{c};font-weight:bold\\">{pcr:.2f}</td>"
            rows += f"<td>{data.get('avg_call_iv',0):.1f}%</td><td>{data.get('avg_put_iv',0):.1f}%</td></tr>"

        return f"""<html><body style="font-family:Arial;background:#1a1a2e;color:#e0e0e0;padding:20px;">
        <div style="max-width:800px;margin:0 auto;background:#16213e;border-radius:10px;padding:20px;">
        <h1 style="color:#00d2ff;">📊 Options Monitor</h1>
        <p>Sentiment: <b>{analysis.get('market_sentiment','N/A')}</b> | P/C: <b>{analysis.get('overall_put_call_ratio','N/A')}</b></p>
        <table style="width:100%;border-collapse:collapse;color:#e0e0e0;">
        <tr style="background:#0f3460;"><th style="padding:8px;border:1px solid #333;">Ticker</th>
        <th style="padding:8px;border:1px solid #333;">Price</th><th style="padding:8px;border:1px solid #333;">Call Vol</th>
        <th style="padding:8px;border:1px solid #333;">Put Vol</th><th style="padding:8px;border:1px solid #333;">P/C</th>
        <th style="padding:8px;border:1px solid #333;">Call IV</th><th style="padding:8px;border:1px solid #333;">Put IV</th></tr>
        {rows}</table></div></body></html>"""
'''

# ============================================================
# tools/telegram_notifier.py
# ============================================================
FILES["tools/telegram_notifier.py"] = '''"""
Herramienta: Notificaciones por Telegram
"""

import asyncio
import aiohttp
from datetime import datetime
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, NOTIFICATION_CONFIG


class TelegramNotifier:
    def __init__(self):
        self.enabled = NOTIFICATION_CONFIG["enable_telegram"]
        self.token = TELEGRAM_BOT_TOKEN
        self.chat_id = TELEGRAM_CHAT_ID
        self.base_url = f"https://api.telegram.org/bot{self.token}"

    def send_report(self, analysis, chart_path=""):
        if not self.enabled:
            print("  📱 Telegram deshabilitado")
            return False
        try:
            message = self._format(analysis)
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(self._send_message(message))
            if chart_path:
                loop.run_until_complete(self._send_photo(chart_path))
            loop.close()
            print("  📱 Reporte Telegram enviado")
            return result
        except Exception as e:
            print(f"  ❌ Error Telegram: {e}")
            return False

    def send_alert(self, alerts):
        if not self.enabled or not alerts:
            return False
        high = [a for a in alerts if a.get("severity") in ("high", "medium")]
        if not high:
            return False
        try:
            msg = "🚨 *ALERTAS*\\n\\n"
            for a in high:
                icon = "🔴" if a.get("severity") == "high" else "🟡"
                msg += f"{icon} *[{a['ticker']}]* {a['message']}\\n"
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self._send_message(msg))
            loop.close()
            return True
        except Exception as e:
            print(f"  ❌ Telegram alert error: {e}")
            return False

    async def _send_message(self, text):
        url = f"{self.base_url}/sendMessage"
        payload = {"chat_id": self.chat_id, "text": text[:4096], "parse_mode": "Markdown"}
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as resp:
                return resp.status == 200

    async def _send_photo(self, path):
        url = f"{self.base_url}/sendPhoto"
        async with aiohttp.ClientSession() as session:
            with open(path, "rb") as photo:
                data = aiohttp.FormData()
                data.add_field("chat_id", self.chat_id)
                data.add_field("photo", photo, filename="report.png")
                async with session.post(url, data=data) as resp:
                    return resp.status == 200

    def _format(self, analysis):
        summary = analysis.get("summary", {})
        msg = f"📊 *OPTIONS MONITOR*\\n{'─'*30}\\n"
        msg += f"Sentiment: *{analysis.get('market_sentiment', 'N/A')}*\\nP/C: *{analysis.get('overall_put_call_ratio', 0)}*\\n\\n"
        for ticker, data in summary.items():
            pcr = data.get("put_call_ratio_volume", 0)
            e = "🐻" if pcr > 1.2 else "🐂" if pcr < 0.8 else "😐"
            msg += f"*{ticker}* ${data.get('current_price',0):,.2f} {e}\\n"
            msg += f"  P/C:{pcr:.2f} IV:C{data.get('avg_call_iv',0):.0f}% P{data.get('avg_put_iv',0):.0f}%\\n\\n"
        alerts = analysis.get("alerts", [])
        if alerts:
            msg += "⚠️ *ALERTAS:*\\n"
            for a in alerts[:5]:
                msg += f"  [{a['ticker']}] {a['message']}\\n"
        msg += f"\\n⏰ {datetime.now().strftime('%H:%M')}"
        return msg
'''

# ============================================================
# tools/backtester.py
# ============================================================
FILES["tools/backtester.py"] = '''"""
Herramienta: Backtesting de señales
"""

import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
from rich.console import Console
from rich.table import Table
from rich import box
import os, json
from config import BACKTEST_CONFIG, REPORTS_DIR

console = Console()


class Backtester:
    def __init__(self, database=None):
        self.db = database
        self.results_dir = BACKTEST_CONFIG["results_dir"]
        os.makedirs(self.results_dir, exist_ok=True)

    def record_signal(self, ticker, signal_type, direction, price_at_signal, details=None):
        signal = {"ticker": ticker, "signal_type": signal_type, "direction": direction,
                  "price_at_signal": price_at_signal, "timestamp": datetime.now().isoformat(),
                  "details": details or {}}
        if self.db:
            signal["id"] = self.db.save_backtest_signal(signal)
        return signal

    def evaluate_past_signals(self):
        if not self.db:
            return []
        signals = self.db.get_backtest_signals(days=BACKTEST_CONFIG["lookback_days"])
        pending = [s for s in signals if s.get("outcome") in (None, "PENDING")]
        if not pending:
            return signals

        for signal in pending:
            ticker = signal["ticker"]
            signal_time = datetime.fromisoformat(signal["timestamp"])
            days_since = (datetime.now() - signal_time).days
            if days_since < 1:
                continue
            try:
                stock = yf.Ticker(ticker)
                hist = stock.history(start=(signal_time - timedelta(days=1)).strftime("%Y-%m-%d"),
                                    end=(datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d"))
                if hist.empty:
                    continue

                price_1d = price_3d = price_7d = None
                for days_check, attr in [(1, "price_1d"), (3, "price_3d"), (7, "price_7d")]:
                    if days_since >= days_check:
                        target = signal_time + timedelta(days=days_check)
                        tz = hist.index.tz
                        after = hist[hist.index >= pd.Timestamp(target, tz=tz)]
                        if not after.empty:
                            locals()[attr] = float(after.iloc[0]["Close"])

                price_1d = locals().get("price_1d")
                price_3d = locals().get("price_3d")
                price_7d = locals().get("price_7d")

                outcome = "PENDING"
                check_price = price_7d or price_3d or price_1d
                if check_price and signal["price_at_signal"]:
                    change = (check_price - signal["price_at_signal"]) / signal["price_at_signal"] * 100
                    if signal["direction"] == "BULLISH":
                        outcome = "CORRECT" if change > 0 else "INCORRECT"
                    elif signal["direction"] == "BEARISH":
                        outcome = "CORRECT" if change < 0 else "INCORRECT"

                self.db.update_backtest_outcome(signal["id"], price_1d, price_3d, price_7d, outcome)
            except Exception as e:
                console.print(f"  [red]Error evaluando {ticker}: {e}[/red]")

        return self.db.get_backtest_signals(days=BACKTEST_CONFIG["lookback_days"])

    def generate_backtest_report(self):
        signals = self.evaluate_past_signals()
        if not signals:
            return {"message": "No signals to report"}

        evaluated = [s for s in signals if s.get("outcome") in ("CORRECT", "INCORRECT")]
        if not evaluated:
            return {"total_signals": len(signals), "message": "All signals pending"}

        correct = len([s for s in evaluated if s["outcome"] == "CORRECT"])
        accuracy = correct / len(evaluated) * 100

        report = {"total": len(signals), "evaluated": len(evaluated),
                  "correct": correct, "accuracy": round(accuracy, 1)}

        console.print(f"\\n[bold cyan]📊 BACKTEST: {accuracy:.1f}% accuracy ({correct}/{len(evaluated)})[/bold cyan]")

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        with open(os.path.join(self.results_dir, f"backtest_{timestamp}.json"), "w") as f:
            json.dump(report, f, indent=2)
        return report

    def record_signals_from_analysis(self, analysis):
        signals = []
        for alert in analysis.get("alerts", []):
            ticker = alert.get("ticker", "")
            at = alert.get("type", "")
            price = analysis.get("summary", {}).get(ticker, {}).get("current_price", 0)
            if not price or not ticker:
                continue
            direction = None
            if at == "HIGH_PUT_CALL_RATIO": direction = "BEARISH"
            elif at == "LOW_PUT_CALL_RATIO": direction = "BULLISH"
            elif at in ("HIGH_IV", "IV_PREMIUM"): direction = "BEARISH"
            if direction:
                signals.append(self.record_signal(ticker, at, direction, price, {"msg": alert.get("message", "")}))

        for u in analysis.get("unusual_activity", []):
            ticker = u.get("ticker", "")
            price = analysis.get("summary", {}).get(ticker, {}).get("current_price", 0)
            if price:
                direction = "BULLISH" if u.get("type") == "CALL" else "BEARISH"
                signals.append(self.record_signal(ticker, "UNUSUAL_VOLUME", direction, price,
                    {"type": u.get("type"), "strike": u.get("strike"), "ratio": u.get("vol_oi_ratio")}))

        if signals:
            console.print(f"  📝 {len(signals)} signals recorded for backtesting")
        return signals
'''

# ============================================================
# memory/__init__.py
# ============================================================
FILES["memory/__init__.py"] = '''from .memory_store import AgentMemory
from .database import OptionsDatabase
'''

# ============================================================
# memory/memory_store.py
# ============================================================
FILES["memory/memory_store.py"] = '''"""
Sistema de memoria persistente
"""

import json, os
from datetime import datetime
from config import MEMORY_FILE


class AgentMemory:
    def __init__(self):
        self.history = self._load()

    def _load(self):
        os.makedirs(os.path.dirname(MEMORY_FILE), exist_ok=True)
        if os.path.exists(MEMORY_FILE):
            try:
                with open(MEMORY_FILE, "r") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                return []
        return []

    def _save(self):
        with open(MEMORY_FILE, "w") as f:
            json.dump(self.history, f, indent=2, default=str)

    def store_analysis(self, analysis):
        clean = self._clean(analysis)
        self.history.append({"timestamp": datetime.now().isoformat(), "analysis": clean})
        if len(self.history) > 200:
            self.history = self.history[-200:]
        self._save()

    def _clean(self, obj):
        if isinstance(obj, dict):
            return {k: self._clean(v) for k, v in obj.items() if k not in ("calls_raw_df", "puts_raw_df")}
        elif isinstance(obj, list):
            return [self._clean(i) for i in obj]
        elif isinstance(obj, (int, float, str, bool, type(None))):
            return obj
        return str(obj)

    def get_previous_analysis(self):
        if len(self.history) >= 2:
            return self.history[-2].get("analysis")
        return None

    def detect_significant_changes(self, current, threshold=5.0):
        previous = self.get_previous_analysis()
        if not previous:
            return []
        changes = []
        prev_s = previous.get("summary", {})
        curr_s = current.get("summary", {})
        for ticker in curr_s:
            if ticker not in prev_s:
                continue
            for key, label in [("avg_call_iv", "Call IV"), ("avg_put_iv", "Put IV"),
                               ("put_call_ratio_volume", "P/C Ratio"), ("iv_skew", "IV Skew"),
                               ("current_price", "Price")]:
                cv = curr_s[ticker].get(key, 0)
                pv = prev_s[ticker].get(key, 0)
                if pv and pv != 0:
                    pct = ((cv - pv) / abs(pv)) * 100
                    if abs(pct) >= threshold:
                        changes.append({"ticker": ticker, "metric": label,
                            "previous": round(pv, 2), "current": round(cv, 2),
                            "change_pct": round(pct, 2),
                            "direction": "📈 UP" if pct > 0 else "📉 DOWN"})
        return changes

    def get_history_summary(self):
        if not self.history:
            return "No previous history."
        return f"Total analyses: {len(self.history)}\\nFirst: {self.history[0]['timestamp']}\\nLast: {self.history[-1]['timestamp']}"

    def get_ticker_trend(self, ticker, metric="avg_call_iv", last_n=10):
        trend = []
        for entry in self.history[-last_n:]:
            s = entry.get("analysis", {}).get("summary", {})
            if ticker in s:
                trend.append({"timestamp": entry["timestamp"], "value": s[ticker].get(metric, 0)})
        return trend
'''

# ============================================================
# memory/database.py
# ============================================================
FILES["memory/database.py"] = '''"""
Base de datos SQLite con SQLAlchemy
"""

from sqlalchemy import create_engine, Column, Integer, Float, String, DateTime, Text, Boolean, func
from sqlalchemy.orm import sessionmaker, declarative_base
from datetime import datetime, timedelta
import json
from config import DATABASE_URL

Base = declarative_base()


class OptionsSnapshot(Base):
    __tablename__ = "options_snapshots"
    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    ticker = Column(String(10), index=True)
    current_price = Column(Float)
    call_volume = Column(Integer)
    put_volume = Column(Integer)
    call_open_interest = Column(Integer)
    put_open_interest = Column(Integer)
    put_call_ratio_volume = Column(Float)
    put_call_ratio_oi = Column(Float)
    avg_call_iv = Column(Float)
    avg_put_iv = Column(Float)
    historical_volatility = Column(Float)
    iv_skew = Column(Float)
    market_sentiment = Column(String(20))


class AlertRecord(Base):
    __tablename__ = "alerts"
    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    ticker = Column(String(10), index=True)
    alert_type = Column(String(50))
    message = Column(Text)
    severity = Column(String(10))
    acknowledged = Column(Boolean, default=False)


class UnusualActivity(Base):
    __tablename__ = "unusual_activity"
    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    ticker = Column(String(10), index=True)
    option_type = Column(String(4))
    strike = Column(Float)
    expiration = Column(String(10))
    volume = Column(Integer)
    open_interest = Column(Integer)
    vol_oi_ratio = Column(Float)
    implied_volatility = Column(Float)
    last_price = Column(Float)


class AgentLog(Base):
    __tablename__ = "agent_logs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    cycle_number = Column(Integer)
    tickers_analyzed = Column(Integer)
    alerts_generated = Column(Integer)
    unusual_activities = Column(Integer)
    market_sentiment = Column(String(20))
    claude_analysis = Column(Text)
    execution_time_seconds = Column(Float)


class BacktestSignal(Base):
    __tablename__ = "backtest_signals"
    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    ticker = Column(String(10), index=True)
    signal_type = Column(String(50))
    direction = Column(String(10))
    price_at_signal = Column(Float)
    price_after_1d = Column(Float, nullable=True)
    price_after_3d = Column(Float, nullable=True)
    price_after_7d = Column(Float, nullable=True)
    outcome = Column(String(20), nullable=True)
    details = Column(Text, nullable=True)


class OptionsDatabase:
    def __init__(self):
        self.engine = create_engine(DATABASE_URL, echo=False)
        Base.metadata.create_all(self.engine)
        Session = sessionmaker(bind=self.engine)
        self.session = Session()
        self.cycle_count = self._get_cycle_count()

    def _get_cycle_count(self):
        last = self.session.query(func.max(AgentLog.cycle_number)).scalar()
        return (last or 0)

    def save_snapshot(self, analysis):
        for ticker, data in analysis.get("summary", {}).items():
            s = OptionsSnapshot(
                timestamp=datetime.fromisoformat(analysis["timestamp"]),
                ticker=ticker, current_price=data.get("current_price", 0),
                call_volume=data.get("call_volume", 0), put_volume=data.get("put_volume", 0),
                call_open_interest=data.get("call_open_interest", 0),
                put_open_interest=data.get("put_open_interest", 0),
                put_call_ratio_volume=data.get("put_call_ratio_volume", 0),
                put_call_ratio_oi=data.get("put_call_ratio_oi", 0),
                avg_call_iv=data.get("avg_call_iv", 0), avg_put_iv=data.get("avg_put_iv", 0),
                historical_volatility=data.get("historical_volatility", 0),
                iv_skew=data.get("iv_skew", 0),
                market_sentiment=analysis.get("market_sentiment", ""))
            self.session.add(s)
        self.session.commit()

    def get_ticker_history(self, ticker, days=30):
        cutoff = datetime.utcnow() - timedelta(days=days)
        snaps = self.session.query(OptionsSnapshot).filter(
            OptionsSnapshot.ticker == ticker, OptionsSnapshot.timestamp >= cutoff
        ).order_by(OptionsSnapshot.timestamp.asc()).all()
        return [{"timestamp": s.timestamp.isoformat(), "price": s.current_price,
                 "call_volume": s.call_volume, "put_volume": s.put_volume,
                 "pcr_volume": s.put_call_ratio_volume, "pcr_oi": s.put_call_ratio_oi,
                 "call_iv": s.avg_call_iv, "put_iv": s.avg_put_iv,
                 "hv": s.historical_volatility, "iv_skew": s.iv_skew} for s in snaps]

    def get_all_tickers_latest(self):
        subq = self.session.query(
            OptionsSnapshot.ticker, func.max(OptionsSnapshot.timestamp).label("max_ts")
        ).group_by(OptionsSnapshot.ticker).subquery()
        latest = self.session.query(OptionsSnapshot).join(
            subq, (OptionsSnapshot.ticker == subq.c.ticker) & (OptionsSnapshot.timestamp == subq.c.max_ts)
        ).all()
        return [{"ticker": s.ticker, "timestamp": s.timestamp.isoformat(),
                 "price": s.current_price, "pcr_volume": s.put_call_ratio_volume,
                 "call_iv": s.avg_call_iv, "put_iv": s.avg_put_iv,
                 "iv_skew": s.iv_skew, "sentiment": s.market_sentiment} for s in latest]

    def save_alerts(self, alerts):
        for a in alerts:
            self.session.add(AlertRecord(
                ticker=a.get("ticker", ""), alert_type=a.get("type", ""),
                message=a.get("message", ""), severity=a.get("severity", "medium")))
        self.session.commit()

    def get_recent_alerts(self, hours=24):
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        alerts = self.session.query(AlertRecord).filter(
            AlertRecord.timestamp >= cutoff).order_by(AlertRecord.timestamp.desc()).all()
        return [{"id": a.id, "timestamp": a.timestamp.isoformat(), "ticker": a.ticker,
                 "type": a.alert_type, "message": a.message, "severity": a.severity,
                 "acknowledged": a.acknowledged} for a in alerts]

    def save_unusual_activity(self, activities):
        for act in activities:
            self.session.add(UnusualActivity(
                ticker=act.get("ticker", ""), option_type=act.get("type", ""),
                strike=act.get("strike", 0), expiration=act.get("expiration", ""),
                volume=act.get("volume", 0), open_interest=act.get("open_interest", 0),
                vol_oi_ratio=act.get("vol_oi_ratio", 0),
                implied_volatility=act.get("implied_volatility", 0),
                last_price=act.get("last_price", 0)))
        self.session.commit()

    def get_unusual_history(self, ticker=None, days=7):
        cutoff = datetime.utcnow() - timedelta(days=days)
        q = self.session.query(UnusualActivity).filter(UnusualActivity.timestamp >= cutoff)
        if ticker:
            q = q.filter(UnusualActivity.ticker == ticker)
        acts = q.order_by(UnusualActivity.timestamp.desc()).limit(50).all()
        return [{"timestamp": a.timestamp.isoformat(), "ticker": a.ticker,
                 "type": a.option_type, "strike": a.strike, "expiration": a.expiration,
                 "volume": a.volume, "oi": a.open_interest,
                 "vol_oi_ratio": a.vol_oi_ratio, "iv": a.implied_volatility} for a in acts]

    def save_agent_log(self, analysis, claude_response, exec_time):
        self.cycle_count += 1
        self.session.add(AgentLog(
            cycle_number=self.cycle_count,
            tickers_analyzed=len(analysis.get("tickers_analyzed", [])),
            alerts_generated=len(analysis.get("alerts", [])),
            unusual_activities=len(analysis.get("unusual_activity", [])),
            market_sentiment=analysis.get("market_sentiment", ""),
            claude_analysis=claude_response[:5000], execution_time_seconds=exec_time))
        self.session.commit()

    def save_backtest_signal(self, signal):
        r = BacktestSignal(
            ticker=signal.get("ticker", ""), signal_type=signal.get("signal_type", ""),
            direction=signal.get("direction", ""), price_at_signal=signal.get("price_at_signal", 0),
            details=json.dumps(signal.get("details", {})))
        self.session.add(r)
        self.session.commit()
        return r.id

    def update_backtest_outcome(self, signal_id, price_1d=None, price_3d=None, price_7d=None, outcome=None):
        s = self.session.query(BacktestSignal).filter_by(id=signal_id).first()
        if s:
            if price_1d is not None: s.price_after_1d = price_1d
            if price_3d is not None: s.price_after_3d = price_3d
            if price_7d is not None: s.price_after_7d = price_7d
            if outcome: s.outcome = outcome
            self.session.commit()

    def get_backtest_signals(self, ticker=None, days=30):
        cutoff = datetime.utcnow() - timedelta(days=days)
        q = self.session.query(BacktestSignal).filter(BacktestSignal.timestamp >= cutoff)
        if ticker:
            q = q.filter(BacktestSignal.ticker == ticker)
        sigs = q.order_by(BacktestSignal.timestamp.desc()).all()
        return [{"id": s.id, "timestamp": s.timestamp.isoformat(), "ticker": s.ticker,
                 "signal_type": s.signal_type, "direction": s.direction,
                 "price_at_signal": s.price_at_signal, "price_after_1d": s.price_after_1d,
                 "price_after_3d": s.price_after_3d, "price_after_7d": s.price_after_7d,
                 "outcome": s.outcome,
                 "details": json.loads(s.details) if s.details else {}} for s in sigs]

    def get_database_stats(self):
        return {
            "total_snapshots": self.session.query(OptionsSnapshot).count(),
            "total_alerts": self.session.query(AlertRecord).count(),
            "total_unusual": self.session.query(UnusualActivity).count(),
            "total_cycles": self.session.query(AgentLog).count(),
            "total_signals": self.session.query(BacktestSignal).count(),
            "unique_tickers": self.session.query(func.count(func.distinct(OptionsSnapshot.ticker))).scalar() or 0,
        }

    def close(self):
        self.session.close()
'''

# ============================================================
# dashboard/__init__.py
# ============================================================
FILES["dashboard/__init__.py"] = '''from .app import create_app
'''

# ============================================================
# dashboard/app.py
# ============================================================
FILES["dashboard/app.py"] = '''"""
Dashboard Web con Flask + SocketIO
"""

from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO
import threading

db_instance = None
agent_instance = None


def create_app(database=None, agent=None):
    global db_instance, agent_instance
    db_instance = database
    agent_instance = agent

    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config["SECRET_KEY"] = "options-monitor-secret"
    socketio = SocketIO(app, cors_allowed_origins="*")

    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/api/latest")
    def api_latest():
        if db_instance:
            return jsonify({"status": "ok", "data": db_instance.get_all_tickers_latest()})
        return jsonify({"status": "error", "message": "DB not available"})

    @app.route("/api/history/<ticker>")
    def api_history(ticker):
        days = request.args.get("days", 30, type=int)
        if db_instance:
            return jsonify({"status": "ok", "ticker": ticker, "data": db_instance.get_ticker_history(ticker, days)})
        return jsonify({"status": "error"})

    @app.route("/api/alerts")
    def api_alerts():
        hours = request.args.get("hours", 24, type=int)
        if db_instance:
            return jsonify({"status": "ok", "data": db_instance.get_recent_alerts(hours)})
        return jsonify({"status": "error"})

    @app.route("/api/unusual")
    def api_unusual():
        ticker = request.args.get("ticker", None)
        days = request.args.get("days", 7, type=int)
        if db_instance:
            return jsonify({"status": "ok", "data": db_instance.get_unusual_history(ticker, days)})
        return jsonify({"status": "error"})

    @app.route("/api/backtest")
    def api_backtest():
        if db_instance:
            return jsonify({"status": "ok", "data": db_instance.get_backtest_signals(days=30)})
        return jsonify({"status": "error"})

    @app.route("/api/stats")
    def api_stats():
        if db_instance:
            return jsonify({"status": "ok", "data": db_instance.get_database_stats()})
        return jsonify({"status": "error"})

    @app.route("/api/run-cycle", methods=["POST"])
    def api_run_cycle():
        if agent_instance:
            def run_async():
                result = agent_instance.run_cycle()
                socketio.emit("cycle_complete", result)
            threading.Thread(target=run_async).start()
            return jsonify({"status": "ok", "message": "Cycle started"})
        return jsonify({"status": "error"})

    @app.route("/api/ask", methods=["POST"])
    def api_ask():
        if agent_instance:
            q = request.json.get("question", "")
            if q:
                return jsonify({"status": "ok", "response": agent_instance._call_claude(q)})
        return jsonify({"status": "error"})

    @socketio.on("connect")
    def handle_connect():
        print("  🌐 Dashboard client connected")

    @socketio.on("request_update")
    def handle_update():
        if db_instance:
            socketio.emit("data_update", {"data": db_instance.get_all_tickers_latest()})

    return app, socketio
'''

# ============================================================
# dashboard/templates/index.html
# ============================================================
FILES["dashboard/templates/index.html"] = '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🤖 Options Monitor Agent</title>
    <link rel="stylesheet" href="/static/style.css">
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.7.2/socket.io.js"></script>
</head>
<body>
    <div class="container">
        <header class="header">
            <div class="header-title">
                <h1>🤖 Options Monitor Agent</h1>
                <p class="subtitle">Real-time Options Analytics | Powered by Claude AI</p>
            </div>
            <div class="header-actions">
                <button class="btn btn-primary" onclick="refreshData()">🔄 Refresh</button>
                <button id="btn-run-cycle" class="btn btn-success" onclick="runCycle()">▶️ Run Cycle</button>
                <span id="last-update" class="last-update">-</span>
            </div>
        </header>

        <div class="stats-bar">
            <div class="stat-card"><div class="stat-label">Sentiment</div><div class="stat-value" id="sentiment-value">-</div></div>
            <div class="stat-card"><div class="stat-label">P/C Ratio</div><div class="stat-value" id="pcr-value">-</div></div>
            <div class="stat-card"><div class="stat-label">Tickers</div><div class="stat-value" id="tickers-count">-</div></div>
            <div class="stat-card"><div class="stat-label">Snapshots</div><div class="stat-value" id="snapshots-count">-</div></div>
            <div class="stat-card"><div class="stat-label">Alerts</div><div class="stat-value" id="alerts-count">-</div></div>
            <div class="stat-card"><div class="stat-label">BT Accuracy</div><div class="stat-value" id="accuracy-value">-</div></div>
        </div>

        <div class="main-grid">
            <div class="card full-width">
                <h2 class="card-title">📋 Watchlist</h2>
                <div class="table-container">
                    <table id="tickers-table">
                        <thead><tr><th>Ticker</th><th>Price</th><th>P/C Ratio</th><th>Call IV%</th><th>Put IV%</th><th>IV Skew</th><th>Sentiment</th><th>Updated</th></tr></thead>
                        <tbody id="tickers-body"><tr><td colspan="8" class="loading">Loading...</td></tr></tbody>
                    </table>
                </div>
            </div>

            <div class="card"><h2 class="card-title">📊 Implied Volatility</h2><canvas id="iv-chart"></canvas></div>
            <div class="card"><h2 class="card-title">📈 Put/Call Ratio</h2><canvas id="pcr-chart"></canvas></div>

            <div class="card"><h2 class="card-title">⚠️ Alerts</h2><div id="alerts-container" class="alerts-list"><p class="loading">Loading...</p></div></div>
            <div class="card"><h2 class="card-title">🔥 Unusual Activity</h2><div id="unusual-container" class="alerts-list"><p class="loading">Loading...</p></div></div>

            <div class="card full-width">
                <h2 class="card-title">📈 History <select id="ticker-select" onchange="loadTickerHistory()"><option value="">Select...</option></select></h2>
                <canvas id="history-chart"></canvas>
            </div>

            <div class="card full-width">
                <h2 class="card-title">🤖 Ask the Agent</h2>
                <div class="chat-container">
                    <div id="chat-messages" class="chat-messages">
                        <div class="chat-msg bot">Hi! Ask me about options data.</div>
                    </div>
                    <div class="chat-input-container">
                        <input type="text" id="chat-input" placeholder="Ask about options..." onkeypress="if(event.key===\'Enter\')sendChat()">
                        <button class="btn btn-primary" onclick="sendChat()">Send</button>
                    </div>
                </div>
            </div>

            <div class="card full-width">
                <h2 class="card-title">📊 Backtest Results</h2>
                <div id="backtest-container"><p class="loading">Loading...</p></div>
            </div>
        </div>

        <footer class="footer"><p>Options Monitor Agent v2.0 | Claude AI | Yahoo Finance</p></footer>
    </div>
    <script src="/static/app.js"></script>
</body>
</html>
'''

# ============================================================
# dashboard/static/style.css
# ============================================================
FILES["dashboard/static/style.css"] = ''':root {
    --bg-primary: #0a0e1a; --bg-secondary: #111827; --bg-card: #1a2332;
    --bg-card-hover: #1e293b; --text-primary: #e2e8f0; --text-secondary: #94a3b8;
    --accent-blue: #3b82f6; --accent-green: #10b981; --accent-red: #ef4444;
    --accent-yellow: #f59e0b; --accent-cyan: #06b6d4; --border: #2d3748;
    --shadow: 0 4px 6px -1px rgba(0,0,0,0.3);
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: 'Segoe UI', system-ui, sans-serif; background: var(--bg-primary); color: var(--text-primary); min-height: 100vh; line-height: 1.6; }
.container { max-width: 1600px; margin: 0 auto; padding: 20px; }
.header { display: flex; justify-content: space-between; align-items: center; padding: 20px 30px; background: var(--bg-secondary); border-radius: 16px; margin-bottom: 20px; border: 1px solid var(--border); }
.header h1 { font-size: 1.8rem; background: linear-gradient(135deg, var(--accent-cyan), var(--accent-blue)); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
.subtitle { color: var(--text-secondary); font-size: 0.9rem; }
.header-actions { display: flex; align-items: center; gap: 12px; }
.last-update { color: var(--text-secondary); font-size: 0.8rem; }
.btn { padding: 8px 20px; border: none; border-radius: 8px; cursor: pointer; font-size: 0.9rem; font-weight: 600; transition: all 0.2s; }
.btn:hover { transform: translateY(-2px); box-shadow: var(--shadow); }
.btn-primary { background: var(--accent-blue); color: white; }
.btn-success { background: var(--accent-green); color: white; }
.stats-bar { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 16px; margin-bottom: 20px; }
.stat-card { background: var(--bg-card); padding: 20px; border-radius: 12px; border: 1px solid var(--border); text-align: center; transition: transform 0.2s; }
.stat-card:hover { transform: translateY(-2px); }
.stat-label { color: var(--text-secondary); font-size: 0.8rem; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 8px; }
.stat-value { font-size: 1.5rem; font-weight: 700; color: var(--accent-cyan); }
.main-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
.card { background: var(--bg-card); border-radius: 12px; padding: 24px; border: 1px solid var(--border); box-shadow: var(--shadow); }
.card.full-width { grid-column: 1 / -1; }
.card-title { font-size: 1.1rem; margin-bottom: 16px; color: var(--accent-cyan); display: flex; align-items: center; gap: 10px; }
.card-title select { background: var(--bg-secondary); color: var(--text-primary); border: 1px solid var(--border); padding: 4px 8px; border-radius: 6px; margin-left: auto; }
.table-container { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; }
th { background: var(--bg-secondary); padding: 12px 16px; text-align: left; font-weight: 600; color: var(--accent-cyan); font-size: 0.85rem; text-transform: uppercase; border-bottom: 2px solid var(--border); }
td { padding: 10px 16px; border-bottom: 1px solid var(--border); font-size: 0.9rem; }
tr:hover { background: var(--bg-card-hover); }
.loading { text-align: center; color: var(--text-secondary); padding: 40px; }
.alerts-list { max-height: 400px; overflow-y: auto; }
.alert-item { padding: 10px 14px; margin-bottom: 8px; border-radius: 8px; border-left: 4px solid; font-size: 0.85rem; }
.alert-high { border-left-color: var(--accent-red); background: rgba(239,68,68,0.1); }
.alert-medium { border-left-color: var(--accent-yellow); background: rgba(245,158,11,0.1); }
.alert-low { border-left-color: var(--accent-green); background: rgba(16,185,129,0.1); }
.alert-ticker { font-weight: 700; color: var(--accent-cyan); }
.alert-time { color: var(--text-secondary); font-size: 0.75rem; }
.chat-container { display: flex; flex-direction: column; height: 400px; }
.chat-messages { flex: 1; overflow-y: auto; padding: 16px; background: var(--bg-secondary); border-radius: 8px; margin-bottom: 12px; }
.chat-msg { padding: 10px 14px; margin-bottom: 10px; border-radius: 12px; max-width: 80%; font-size: 0.9rem; line-height: 1.5; white-space: pre-wrap; }
.chat-msg.user { background: var(--accent-blue); color: white; margin-left: auto; border-bottom-right-radius: 4px; }
.chat-msg.bot { background: var(--bg-card-hover); color: var(--text-primary); border-bottom-left-radius: 4px; }
.chat-input-container { display: flex; gap: 10px; }
.chat-input-container input { flex: 1; padding: 10px 16px; background: var(--bg-secondary); border: 1px solid var(--border); border-radius: 8px; color: var(--text-primary); font-size: 0.9rem; }
.chat-input-container input:focus { outline: none; border-color: var(--accent-blue); }
.badge { display: inline-block; padding: 3px 10px; border-radius: 20px; font-size: 0.8rem; font-weight: 600; }
.badge-bullish { background: rgba(16,185,129,0.2); color: var(--accent-green); }
.badge-bearish { background: rgba(239,68,68,0.2); color: var(--accent-red); }
.badge-neutral { background: rgba(245,158,11,0.2); color: var(--accent-yellow); }
.footer { text-align: center; padding: 20px; color: var(--text-secondary); font-size: 0.8rem; margin-top: 30px; }
::-webkit-scrollbar { width: 6px; }
::-webkit-scrollbar-track { background: var(--bg-secondary); }
::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
@media (max-width: 768px) { .main-grid { grid-template-columns: 1fr; } .header { flex-direction: column; gap: 12px; } .stats-bar { grid-template-columns: repeat(2, 1fr); } }
'''

# ============================================================
# dashboard/static/app.js
# ============================================================
FILES["dashboard/static/app.js"] = '''let ivChart=null,pcrChart=null,historyChart=null;
const socket=io(),API="";

document.addEventListener("DOMContentLoaded",()=>{refreshData();setInterval(refreshData,60000)});
socket.on("cycle_complete",()=>{showNotif("Cycle done!","success");refreshData()});

async function fetchJSON(u){try{const r=await fetch(u);return await r.json()}catch(e){return{status:"error"}}}

async function refreshData(){
    document.getElementById("last-update").textContent="Last: "+new Date().toLocaleTimeString();
    const[lat,alt,unu,sta,bt]=await Promise.all([fetchJSON("/api/latest"),fetchJSON("/api/alerts?hours=24"),fetchJSON("/api/unusual?days=7"),fetchJSON("/api/stats"),fetchJSON("/api/backtest")]);
    if(lat.status==="ok"){updateTable(lat.data);updateCharts(lat.data);updateSelect(lat.data)}
    if(alt.status==="ok")updateAlerts(alt.data);
    if(unu.status==="ok")updateUnusual(unu.data);
    if(sta.status==="ok")document.getElementById("snapshots-count").textContent=(sta.data.total_snapshots||0).toLocaleString();
    if(bt.status==="ok")updateBacktest(bt.data);
}

function updateTable(data){
    const tb=document.getElementById("tickers-body");
    if(!data||!data.length){tb.innerHTML='<tr><td colspan="8" class="loading">No data. Run a cycle.</td></tr>';return}
    document.getElementById("tickers-count").textContent=data.length;
    tb.innerHTML=data.map(d=>{
        const p=d.pcr_volume||0,pc=p>1.2?"badge-bearish":p<0.8?"badge-bullish":"badge-neutral",pe=p>1.2?"🐻":p<0.8?"🐂":"😐";
        const sc=d.sentiment?.includes("BEAR")?"badge-bearish":d.sentiment?.includes("BULL")?"badge-bullish":"badge-neutral";
        return`<tr onclick="selectTicker('${d.ticker}')" style="cursor:pointer"><td><b>${d.ticker}</b></td><td>
$$
{(d.price||0).toLocaleString("en-US",{minimumFractionDigits:2})}</td><td><span class="badge ${pc}">${p.toFixed(2)} ${pe}</span></td><td>${(d.call_iv||0).toFixed(1)}%</td><td>${(d.put_iv||0).toFixed(1)}%</td><td>${(d.iv_skew||0).toFixed(1)}%</td><td><span class="badge ${sc}">${d.sentiment||"-"}</span></td><td class="alert-time">${d.timestamp?new Date(d.timestamp).toLocaleString():"-"}</td></tr>`
    }).join("")
}

function updateCharts(data){
    if(!data||!data.length)return;
    const t=data.map(d=>d.ticker),ci=data.map(d=>d.call_iv||0),pi=data.map(d=>d.put_iv||0),pc=data.map(d=>d.pcr_volume||0);
    const ctx1=document.getElementById("iv-chart").getContext("2d");
    if(ivChart)ivChart.destroy();
    ivChart=new Chart(ctx1,{type:"bar",data:{labels:t,datasets:[{label:"Call IV%",data:ci,backgroundColor:"rgba(16,185,129,0.7)",borderRadius:6},{label:"Put IV%",data:pi,backgroundColor:"rgba(239,68,68,0.7)",borderRadius:6}]},options:{responsive:true,plugins:{legend:{labels:{color:"#94a3b8"}}},scales:{x:{ticks:{color:"#94a3b8"},grid:{color:"rgba(45,55,72,0.5)"}},y:{ticks:{color:"#94a3b8"},grid:{color:"rgba(45,55,72,0.5)"}}}}});
    const ctx2=document.getElementById("pcr-chart").getContext("2d");
    if(pcrChart)pcrChart.destroy();
    pcrChart=new Chart(ctx2,{type:"bar",data:{labels:t,datasets:[{label:"P/C Ratio",data:pc,backgroundColor:pc.map(p=>p>1.2?"rgba(239,68,68,0.7)":p<0.8?"rgba(16,185,129,0.7)":"rgba(245,158,11,0.7)"),borderRadius:6}]},options:{responsive:true,plugins:{legend:{labels:{color:"#94a3b8"}}},scales:{x:{ticks:{color:"#94a3b8"},grid:{color:"rgba(45,55,72,0.5)"}},y:{ticks:{color:"#94a3b8"},grid:{color:"rgba(45,55,72,0.5)"}}}}});
    const avg=pc.reduce((a,b)=>a+b,0)/pc.length;
    const se=document.getElementById("sentiment-value"),pe=document.getElementById("pcr-value");
    pe.textContent=avg.toFixed(3);
    if(avg>1.2){se.textContent="🐻 BEARISH";se.style.color="#ef4444"}else if(avg<0.8){se.textContent="🐂 BULLISH";se.style.color="#10b981"}else{se.textContent="😐 NEUTRAL";se.style.color="#f59e0b"}
}

function updateAlerts(alerts){
    const c=document.getElementById("alerts-container");document.getElementById("alerts-count").textContent=alerts.length;
    if(!alerts.length){c.innerHTML='<p class="loading">No alerts ✅</p>';return}
    c.innerHTML=alerts.slice(0,20).map(a=>{const i=a.severity==="high"?"🔴":"🟡";return`<div class="alert-item alert-${a.severity||"medium"}">${i} <span class="alert-ticker">[${a.ticker}]</span> ${a.message}<div class="alert-time">${a.type} · ${new Date(a.timestamp).toLocaleString()}</div></div>`}).join("")
}

function updateUnusual(acts){
    const c=document.getElementById("unusual-container");
    if(!acts.length){c.innerHTML='<p class="loading">No unusual activity</p>';return}
    c.innerHTML=acts.slice(0,15).map(u=>`<div class="alert-item alert-medium">${u.type==="CALL"?"📗":"📕"} <span class="alert-ticker">${u.ticker}</span> ${u.type}
$$
{u.strike?.toFixed(2)} | Vol:${(u.volume||0).toLocaleString()} OI:${(u.oi||0).toLocaleString()} <b>Vol/OI:${u.vol_oi_ratio}x</b> IV:${u.iv}%<div class="alert-time">Exp:${u.expiration} · ${new Date(u.timestamp).toLocaleString()}</div></div>`).join("")
}

function updateBacktest(sigs){
    const c=document.getElementById("backtest-container");
    if(!sigs.length){c.innerHTML='<p class="loading">No signals yet.</p>';return}
    const ev=sigs.filter(s=>s.outcome==="CORRECT"||s.outcome==="INCORRECT"),co=ev.filter(s=>s.outcome==="CORRECT").length,ac=ev.length?((co/ev.length)*100).toFixed(1):"-";
    document.getElementById("accuracy-value").textContent=ev.length?ac+"%":"-";
    let h=`<div class="table-container"><table><thead><tr><th>Date</th><th>Ticker</th><th>Signal</th><th>Dir</th><th>Price</th><th>+1D</th><th>+3D</th><th>+7D</th><th>Result</th></tr></thead><tbody>`;
    sigs.slice(0,30).forEach(s=>{const oc=s.outcome==="CORRECT"?"badge-bullish":s.outcome==="INCORRECT"?"badge-bearish":"badge-neutral";const fp=p=>p?"$"+p.toFixed(2):"-";h+=`<tr><td class="alert-time">${new Date(s.timestamp).toLocaleDateString()}</td><td><b>${s.ticker}</b></td><td>${s.signal_type}</td><td>${s.direction==="BULLISH"?"🐂":"🐻"} ${s.direction}</td><td>${fp(s.price_at_signal)}</td><td>${fp(s.price_after_1d)}</td><td>${fp(s.price_after_3d)}</td><td>${fp(s.price_after_7d)}</td><td><span class="badge ${oc}">${s.outcome||"PENDING"}</span></td></tr>`});
    h+="</tbody></table></div>";c.innerHTML=h
}

function updateSelect(data){const s=document.getElementById("ticker-select"),v=s.value;s.innerHTML='<option value="">Select...</option>';data.forEach(d=>{const o=document.createElement("option");o.value=d.ticker;o.textContent=d.ticker;if(d.ticker===v)o.selected=true;s.appendChild(o)})}

function selectTicker(t){document.getElementById("ticker-select").value=t;loadTickerHistory()}

async function loadTickerHistory(){
    const t=document.getElementById("ticker-select").value;if(!t)return;
    const r=await fetchJSON(`/api/history/${t}?days=30`);if(r.status!=="ok"||!r.data.length)return;
    const d=r.data,l=d.map(x=>new Date(x.timestamp).toLocaleString()),p=d.map(x=>x.price),ci=d.map(x=>x.call_iv),pi=d.map(x=>x.put_iv);
    const ctx=document.getElementById("history-chart").getContext("2d");
    if(historyChart)historyChart.destroy();
    historyChart=new Chart(ctx,{type:"line",data:{labels:l,datasets:[{label:t+" Price",data:p,borderColor:"#06b6d4",yAxisID:"y1",tension:.3,fill:false},{label:"Call IV%",data:ci,borderColor:"#10b981",borderDash:[5,5],yAxisID:"y2",tension:.3},{label:"Put IV%",data:pi,borderColor:"#ef4444",borderDash:[5,5],yAxisID:"y2",tension:.3}]},options:{responsive:true,interaction:{intersect:false,mode:"index"},plugins:{legend:{labels:{color:"#94a3b8"}}},scales:{x:{ticks:{color:"#94a3b8",maxTicksLimit:12},grid:{color:"rgba(45,55,72,0.3)"}},y1:{position:"left",ticks:{color:"#06b6d4"},grid:{color:"rgba(45,55,72,0.3)"},title:{display:true,text:"Price ($)",color:"#06b6d4"}},y2:{position:"right",ticks:{color:"#10b981"},grid:{display:false},title:{display:true,text:"IV (%)",color:"#10b981"}}}}})
}

async function runCycle(){
    const b=document.getElementById("btn-run-cycle");b.disabled=true;b.textContent="⏳ Running...";
    try{await fetch("/api/run-cycle",{method:"POST"});showNotif("Cycle started!","info")}catch(e){showNotif("Error","error")}
    setTimeout(()=>{b.disabled=false;b.textContent="▶️ Run Cycle"},5000)
}

async function sendChat(){
    const inp=document.getElementById("chat-input"),q=inp.value.trim();if(!q)return;
    const msgs=document.getElementById("chat-messages");
    msgs.innerHTML+=`<div class="chat-msg user">${q.replace(/</g,"&lt;")}</div>`;inp.value="";
    const lid="l"+Date.now();msgs.innerHTML+=`<div class="chat-msg bot" id="${lid}">🤔 Thinking...</div>`;msgs.scrollTop=msgs.scrollHeight;
    try{const r=await fetch("/api/ask",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({question:q})});const d=await r.json();document.getElementById(lid).textContent=d.status==="ok"?d.response:"❌ Error"}catch(e){document.getElementById(lid).textContent="❌ Connection error"}
    msgs.scrollTop=msgs.scrollHeight
}

function showNotif(msg,type="info"){
    const c={info:"#3b82f6",success:"#10b981",error:"#ef4444"}[type]||"#3b82f6";
    const n=document.createElement("div");
    n.style.cssText=`position:fixed;top:20px;right:20px;padding:14px 24px;background:${c};color:white;border-radius:10px;font-weight:600;z-index:10000;box-shadow:0 4px 12px rgba(0,0,0,0.3)`;
    n.textContent=msg;document.body.appendChild(n);
    setTimeout(()=>{n.style.opacity="0";n.style.transition="opacity 0.3s";setTimeout(()=>n.remove(),300)},3000)
}
'''

# ============================================================
# agent.py
# ============================================================
FILES["agent.py"] = '''"""
Agente Autonomo de Monitoreo de Opciones v2.0
"""

import json, time
from datetime import datetime
from anthropic import Anthropic
from config import ANTHROPIC_API_KEY, WATCHLIST, AGENT_CONFIG, NOTIFICATION_CONFIG
from tools.options_scraper import get_multiple_options
from tools.analysis_tool import analyze_options_data, generate_report_chart, generate_interactive_chart
from tools.greeks_calculator import GreeksCalculator
from tools.notification_tool import display_analysis, console
from tools.email_notifier import EmailNotifier
from tools.telegram_notifier import TelegramNotifier
from tools.backtester import Backtester
from memory.memory_store import AgentMemory
from memory.database import OptionsDatabase


class OptionsMonitorAgent:
    def __init__(self):
        self.client = Anthropic(api_key=ANTHROPIC_API_KEY)
        self.conversation_history = []
        self.memory = AgentMemory()
        self.db = OptionsDatabase()
        self.greeks_calc = GreeksCalculator()
        self.email_notifier = EmailNotifier()
        self.telegram_notifier = TelegramNotifier()
        self.backtester = Backtester(database=self.db)
        self.cycle_count = 0
        self.last_analysis = None

        self.system_prompt = """Eres un agente autonomo experto en analisis de opciones financieras (puts y calls).
Tienes acceso a datos en tiempo real de opciones, Greeks (Delta, Gamma, Theta, Vega), volatilidad implicita e historica.

Tu trabajo es:
1. OBSERVAR: Recibir datos de opciones
2. ANALIZAR: Identificar patrones y anomalias
3. ALERTAR: Señalar cambios significativos
4. INTERPRETAR: Dar contexto usando Greeks y volatilidad
5. RECOMENDAR: Interpretaciones del sentimiento

Capacidades:
- Greeks: Delta (direccion), Gamma (aceleracion), Theta (time decay), Vega (sensibilidad IV)
- IV vs HV: Detectar divergencias
- IV Skew: Diferencia entre IV puts vs calls
- Smart Money: Volumen/OI ratio alto
- Put/Call Ratio: Analisis de sentimiento

Reglas:
- Explica tu razonamiento paso a paso
- Se conciso pero preciso
- Usa emojis
- NUNCA des consejos de inversion directos
- Menciona riesgos y limitaciones

Formato:
1. 📊 RESUMEN EJECUTIVO
2. 🔍 TOP PICKS
3. 📐 GREEKS INSIGHTS
4. ⚠️ ALERTAS
5. 🔥 SMART MONEY
6. 🧠 INTERPRETACION
7. 📋 PROXIMOS PASOS"""

    def _call_claude(self, user_message):
        self.conversation_history.append({"role": "user", "content": user_message})
        try:
            response = self.client.messages.create(
                model=AGENT_CONFIG["model"], max_tokens=AGENT_CONFIG["max_tokens"],
                temperature=AGENT_CONFIG["temperature"], system=self.system_prompt,
                messages=self.conversation_history)
            msg = response.content[0].text
            self.conversation_history.append({"role": "assistant", "content": msg})
            if len(self.conversation_history) > 20:
                self.conversation_history = self.conversation_history[-16:]
            return msg
        except Exception as e:
            err = f"Error with Claude: {e}"
            console.print(f"[red]{err}[/red]")
            return err

    def run_cycle(self):
        start = time.time()
        self.cycle_count += 1
        result = {"cycle": self.cycle_count, "timestamp": datetime.now().isoformat(), "status": "running"}

        console.print(f"\\n[bold white on blue] 🔄 CYCLE #{self.cycle_count} [/bold white on blue]")
        console.print(f"[dim]{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}[/dim]\\n")

        # PHASE 1: OBSERVE
        console.print("[bold yellow]🔭 PHASE 1: OBSERVING...[/bold yellow]")
        console.print(f"   Monitoring: {', '.join(WATCHLIST)}")
        raw_data = get_multiple_options(WATCHLIST)
        ok = [d for d in raw_data if d.get("status") == "success"]
        fail = [d for d in raw_data if d.get("status") == "error"]
        console.print(f"   ✅ Got: {len(ok)}/{len(WATCHLIST)}")

        # PHASE 2: GREEKS
        console.print("\\n[bold yellow]📐 PHASE 2: GREEKS...[/bold yellow]")
        for i, data in enumerate(raw_data):
            if data.get("status") == "success":
                raw_data[i] = self.greeks_calc.enrich_options_with_greeks(data)
                console.print(f"   ✅ Greeks for {data['ticker']}")

        # PHASE 3: ANALYZE
        console.print("\\n[bold yellow]📊 PHASE 3: ANALYZING...[/bold yellow]")
        analysis = analyze_options_data(raw_data)
        chart_path = generate_report_chart(analysis)
        try:
            generate_interactive_chart(analysis)
        except Exception:
            pass
        changes = self.memory.detect_significant_changes(analysis, AGENT_CONFIG["alert_threshold_percent"])
        if changes:
            console.print(f"   🔄 Changes detected: {len(changes)}")

        # PHASE 4: THINK
        console.print("\\n[bold yellow]🧠 PHASE 4: THINKING (Claude)...[/bold yellow]")
        context = self._build_context(analysis, changes)
        claude_out = self._call_claude(context)

        # PHASE 5: REPORT
        console.print("\\n[bold yellow]📢 PHASE 5: REPORTING...[/bold yellow]")
        display_analysis(analysis, chart_path)
        console.print(f"\\n[bold magenta]{'='*60}[/bold magenta]")
        console.print(f"[bold magenta]🤖 AGENT ANALYSIS (Claude) - Cycle #{self.cycle_count}[/bold magenta]")
        console.print(f"[bold magenta]{'='*60}[/bold magenta]")
        console.print(claude_out)
        console.print(f"[bold magenta]{'='*60}[/bold magenta]\\n")

        # PHASE 6: NOTIFY
        console.print("[bold yellow]📬 PHASE 6: NOTIFYING...[/bold yellow]")
        self.email_notifier.send_report(analysis, chart_path)
        self.telegram_notifier.send_report(analysis, chart_path)
        high_alerts = [a for a in analysis.get("alerts", []) if a.get("severity") == "high"]
        if high_alerts:
            self.email_notifier.send_alert(high_alerts)
            self.telegram_notifier.send_alert(high_alerts)

        # PHASE 7: STORE
        console.print("\\n[bold yellow]💾 PHASE 7: STORING...[/bold yellow]")
        self.memory.store_analysis(analysis)
        self.db.save_snapshot(analysis)
        self.db.save_alerts(analysis.get("alerts", []))
        self.db.save_unusual_activity(analysis.get("unusual_activity", []))
        exec_time = time.time() - start
        self.db.save_agent_log(analysis, claude_out, exec_time)
        console.print("   ✅ Saved to SQLite + JSON")

        # PHASE 8: BACKTEST
        console.print("\\n[bold yellow]📈 PHASE 8: BACKTESTING...[/bold yellow]")
        new_sigs = self.backtester.record_signals_from_analysis(analysis)
        if self.cycle_count % 5 == 0:
            self.backtester.generate_backtest_report()

        exec_time = time.time() - start
        result.update({"status": "completed", "tickers_analyzed": len(ok), "alerts": len(analysis.get("alerts", [])),
            "unusual": len(analysis.get("unusual_activity", [])), "changes": len(changes),
            "signals": len(new_sigs), "sentiment": analysis.get("market_sentiment", ""),
            "time": round(exec_time, 2)})
        self.last_analysis = analysis
        console.print(f"\\n[bold green]✅ Cycle #{self.cycle_count} done in {exec_time:.1f}s[/bold green]\\n")
        return result

    def _build_context(self, analysis, changes):
        hist = self.memory.get_history_summary()
        stats = self.db.get_database_stats()
        clean = {}
        for t, d in analysis.get("summary", {}).items():
            clean[t] = {k: v for k, v in d.items() if k not in ("calls_raw_df", "puts_raw_df")}
        ctx = f"""=== OPTIONS DATA ===
Cycle: #{self.cycle_count} | {analysis['timestamp']}
Tickers: {', '.join(analysis.get('tickers_analyzed', []))}

=== AGENT STATE ===
{hist}
DB: {json.dumps(stats)}

=== SUMMARY (with Greeks) ===
{json.dumps(clean, indent=2, default=str)}

=== ALERTS ({len(analysis.get('alerts', []))}) ===
{json.dumps(analysis.get('alerts', []), indent=2)}

=== UNUSUAL ACTIVITY ({len(analysis.get('unusual_activity', []))}) ===
{json.dumps(analysis.get('unusual_activity', []), indent=2)}

=== MARKET ===
Sentiment: {analysis.get('market_sentiment', 'N/A')}
P/C: {analysis.get('overall_put_call_ratio', 'N/A')}
Call Vol: {analysis.get('total_call_volume', 0):,} | Put Vol: {analysis.get('total_put_volume', 0):,}
"""
        if changes:
            ctx += f"\\n=== CHANGES ===\\n{json.dumps(changes, indent=2)}\\n"
        ctx += "\\nAnalyze this data. Focus on Greeks, IV vs HV, IV Skew, Smart Money, and changes."
        return ctx

    def interactive_mode(self):
        console.print("\\n[bold green]💬 Interactive Mode[/bold green]")
        console.print("[dim]Commands: backtest, history <TICKER>, stats, refresh, exit[/dim]\\n")
        while True:
            try:
                inp = input("You > ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not inp:
                continue
            if inp.lower() in ("exit", "quit", "salir"):
                break
            if inp.lower() == "backtest":
                self.backtester.generate_backtest_report(); continue
            if inp.lower() == "stats":
                console.print(json.dumps(self.db.get_database_stats(), indent=2)); continue
            if inp.lower() == "refresh":
                self.run_cycle(); continue
            if inp.lower().startswith("history "):
                t = inp.split(" ")[1].upper()
                h = self.db.get_ticker_history(t, 7)
                for x in h[-10:]:
                    console.print(f"  {x['timestamp']} | ${x['price']:,.2f} | P/C:{x['pcr_volume']:.2f} | IV:C{x['call_iv']:.1f}% P{x['put_iv']:.1f}%")
                continue
            response = self._call_claude(inp)
            console.print(f"\\n🤖 [bold cyan]Agent:[/bold cyan]\\n{response}\\n")

    def cleanup(self):
        self.db.close()
        console.print("[dim]Resources released.[/dim]")
'''

# ============================================================
# main.py
# ============================================================
FILES["main.py"] = '''"""
🚀 Options Monitor Agent v2.0 - Main Entry Point
"""

import schedule, time, sys, threading
from rich.console import Console
from agent import OptionsMonitorAgent
from config import AGENT_CONFIG, WATCHLIST, DASHBOARD_CONFIG, NOTIFICATION_CONFIG

console = Console()


def show_banner():
    console.print("\\n[bold cyan]╔══════════════════════════════════════════════════╗[/bold cyan]")
    console.print("[bold cyan]║[/bold cyan]   [bold white]🤖 OPTIONS MONITOR AGENT v2.0[/bold white]                   [bold cyan]║[/bold cyan]")
    console.print("[bold cyan]║[/bold cyan]   [dim]Autonomous Options Analytics[/dim]                    [bold cyan]║[/bold cyan]")
    console.print("[bold cyan]║[/bold cyan]   [dim]Powered by Claude AI[/dim]                            [bold cyan]║[/bold cyan]")
    console.print("[bold cyan]╚══════════════════════════════════════════════════╝[/bold cyan]")
    console.print(f"\\n  📋 Watchlist ({len(WATCHLIST)}): {', '.join(WATCHLIST)}")
    console.print(f"  ⏱️  Interval: {AGENT_CONFIG['monitor_interval_minutes']}min | 🧠 {AGENT_CONFIG['model']}")
    console.print(f"  📐 Greeks: ✅ | 🗄️ SQLite: ✅ | 📧 Email: {'✅' if NOTIFICATION_CONFIG['enable_email'] else '❌'} | 📱 Telegram: {'✅' if NOTIFICATION_CONFIG['enable_telegram'] else '❌'}")
    console.print(f"  🌐 Dashboard: port {DASHBOARD_CONFIG['port']}\\n")


def run_dashboard(agent):
    try:
        from dashboard.app import create_app
        app, socketio = create_app(database=agent.db, agent=agent)
        console.print(f"  🌐 Dashboard: http://localhost:{DASHBOARD_CONFIG['port']}")
        socketio.run(app, host=DASHBOARD_CONFIG["host"], port=DASHBOARD_CONFIG["port"],
                     debug=False, allow_unsafe_werkzeug=True, use_reloader=False)
    except Exception as e:
        console.print(f"  [red]Dashboard error: {e}[/red]")


def main():
    show_banner()
    agent = OptionsMonitorAgent()

    if len(sys.argv) > 1:
        mode = sys.argv[1]
    else:
        console.print("[bold]Select mode:[/bold]")
        console.print("  [cyan]1)[/cyan] 🔄 Continuous monitoring")
        console.print("  [cyan]2)[/cyan] 📊 Single analysis")
        console.print("  [cyan]3)[/cyan] 💬 Interactive")
        console.print("  [cyan]4)[/cyan] 🌐 Dashboard + Monitor")
        console.print("  [cyan]5)[/cyan] 🌐 Dashboard only")
        console.print("  [cyan]6)[/cyan] 📈 Backtest report")
        console.print("  [cyan]7)[/cyan] 🔄+💬 Analysis + Interactive\\n")
        mode = input("Choice (1-7): ").strip()

    try:
        if mode == "1":
            agent.run_cycle()
            schedule.every(AGENT_CONFIG["monitor_interval_minutes"]).minutes.do(agent.run_cycle)
            console.print(f"[dim]Next in {AGENT_CONFIG['monitor_interval_minutes']}min. Ctrl+C to stop.[/dim]")
            while True: schedule.run_pending(); time.sleep(1)
        elif mode == "2":
            agent.run_cycle()
        elif mode == "3":
            agent.run_cycle(); agent.interactive_mode()
        elif mode == "4":
            threading.Thread(target=run_dashboard, args=(agent,), daemon=True).start()
            time.sleep(2); agent.run_cycle()
            schedule.every(AGENT_CONFIG["monitor_interval_minutes"]).minutes.do(agent.run_cycle)
            console.print(f"\\n[bold]🌐 http://localhost:{DASHBOARD_CONFIG['port']}[/bold]")
            while True: schedule.run_pending(); time.sleep(1)
        elif mode == "5":
            run_dashboard(agent)
        elif mode == "6":
            agent.backtester.generate_backtest_report()
        elif mode == "7":
            agent.run_cycle(); agent.interactive_mode()
        else:
            console.print("[red]Invalid option[/red]")
    except KeyboardInterrupt:
        console.print("\\n[yellow]⛔ Stopped.[/yellow]")
    finally:
        agent.cleanup()


if __name__ == "__main__":
    main()
'''

# ============================================================
# README.md
# ============================================================
FILES["README.md"] = '''# 🤖 Options Monitor Agent v2.0

Autonomous options monitoring agent powered by **Claude AI**.

## Features
- 📊 Real-time options monitoring (calls & puts)
- 📐 Full Greeks (Delta, Gamma, Theta, Vega, Rho)
- 🧠 Claude AI analysis & interpretation
- 🗄️ SQLite persistent database
- 📧 Email notifications & alerts
- 📱 Telegram real-time alerts
- 🌐 Interactive web dashboard
- 📈 Signal backtesting
- 🔥 Smart money detection
- 🔄 Continuous monitoring

## Quick Start

```bash
python setup_project.py          # Generate project
cd options_monitor_agent
python -m venv venv
source venv/bin/activate          # Linux/Mac
pip install -r requirements.txt
cp .env.example .env              # Edit with your API key
python main.py

def create_project():
    """Crea toda la estructura del proyecto."""

    print("=" * 60)
    print("🤖 OPTIONS MONITOR AGENT v2.0 - Project Generator")
    print("=" * 60)

    # Crear directorio principal
    if os.path.exists(PROJECT_NAME):
        response = input(f"\n⚠️  '{PROJECT_NAME}/' already exists. Overwrite? (y/n): ").strip().lower()
        if response != 'y':
            print("❌ Cancelled.")
            return

    # Directorios necesarios
    directories = [
        PROJECT_NAME,
        os.path.join(PROJECT_NAME, "tools"),
        os.path.join(PROJECT_NAME, "memory"),
        os.path.join(PROJECT_NAME, "dashboard"),
        os.path.join(PROJECT_NAME, "dashboard", "templates"),
        os.path.join(PROJECT_NAME, "dashboard", "static"),
        os.path.join(PROJECT_NAME, "reports"),
        os.path.join(PROJECT_NAME, "backtest_results"),
    ]

    print("\n📁 Creating directories...")
    for d in directories:
        os.makedirs(d, exist_ok=True)
        print(f"   ✅ {d}/")

    # Escribir archivos
    print("\n📝 Writing files...")
    total_lines = 0
    total_files = 0

    for filepath, content in FILES.items():
        full_path = os.path.join(PROJECT_NAME, filepath)

        # Asegurar que el directorio padre existe
        parent_dir = os.path.dirname(full_path)
        if parent_dir:
            os.makedirs(parent_dir, exist_ok=True)

        # Escribir archivo
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(content.strip() + "\n")

        lines = len(content.strip().split("\n"))
        total_lines += lines
        total_files += 1
        print(f"   ✅ {filepath} ({lines} lines)")

    # Crear .env desde .env.example
    env_example = os.path.join(PROJECT_NAME, ".env.example")
    env_file = os.path.join(PROJECT_NAME, ".env")
    if os.path.exists(env_example) and not os.path.exists(env_file):
        import shutil
        shutil.copy(env_example, env_file)
        print(f"   ✅ .env (copied from .env.example)")

    # Crear .gitignore
    gitignore_content = """# Python
__pycache__/
*.py[cod]
*$py.class
*.egg-info/
dist/
build/
venv/
.venv/

# Environment
.env

# Database
*.db
*.sqlite3

# Reports
reports/
backtest_results/

# Memory
memory/history.json
memory/*.db

# IDE
.vscode/
.idea/
*.swp
*.swo

# OS
.DS_Store
Thumbs.db
'''

def create_project():
    """Crea toda la estructura del proyecto."""
    import shutil
    print("=" * 60)
    print("OPTIONS MONITOR AGENT v2.0 - Project Generator")
    print("=" * 60)
    if os.path.exists(PROJECT_NAME):
        resp = input(f"\n'{PROJECT_NAME}/' already exists. Overwrite? (y/N): ")
        if resp.strip().lower() != 'y':
            print("Cancelled.")
            return
        shutil.rmtree(PROJECT_NAME)
    dirs = [
        PROJECT_NAME,
        os.path.join(PROJECT_NAME, "reports"),
        os.path.join(PROJECT_NAME, "backtest_results"),
        os.path.join(PROJECT_NAME, "memory"),
        os.path.join(PROJECT_NAME, "logs"),
    ]
    print("\nCreating directories...")
    for d in dirs:
        os.makedirs(d, exist_ok=True)
        print(f"  OK {d}/")
    print("\nCreating files...")
    total_files = 0
    total_lines = 0
    for filepath, content in FILES.items():
        full_path = os.path.join(PROJECT_NAME, filepath)
        parent = os.path.dirname(full_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(content.strip() + "\n")
        lines = len(content.strip().split("\n"))
        total_lines += lines
        total_files += 1
        print(f"  OK {filepath} ({lines} lines)")
    env_ex = os.path.join(PROJECT_NAME, ".env.example")
    env_f = os.path.join(PROJECT_NAME, ".env")
    if os.path.exists(env_ex) and not os.path.exists(env_f):
        shutil.copy(env_ex, env_f)
        print("  OK .env (copied from .env.example)")
        total_files += 1
    gi_content = (
        "__pycache__/\n*.py[cod]\n*$py.class\n*.egg-info/\n"
        "dist/\nbuild/\nvenv/\n.venv/\n.env\n*.sqlite3\n"
        "reports/\nbacktest_results/\nmemory/history.json\n"
        "memory/*.db\nlogs/\n.DS_Store\nThumbs.db\n"
    )
    gi_path = os.path.join(PROJECT_NAME, ".gitignore")
    with open(gi_path, "w", encoding="utf-8") as f:
        f.write(gi_content)
    print("  OK .gitignore")
    total_files += 1
    print("\n" + "=" * 60)
    print("PROJECT GENERATED SUCCESSFULLY!")
    print("=" * 60)
    print(f"\nSummary:")
    print(f"  Directory: ./{PROJECT_NAME}/")
    print(f"  Files created: {total_files}")
    print(f"  Total lines: {total_lines:,}")
    print(f"\nNext steps:")
    print(f"  1. cd {PROJECT_NAME}")
    print(f"  2. python -m venv venv")
    print(f"  3. source venv/bin/activate  # Linux/Mac")
    print(f"  4. pip install -r requirements.txt")
    print(f"  5. Edit .env with your ANTHROPIC_API_KEY")
    print(f"  6. python main.py")
    print(f"\nDashboard at: http://localhost:5000")
    print("=" * 60 + "\n")
# ============================================================
# ENTRY POINT
# ============================================================
if __name__ == "__main__":
    create_project()