"""
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

def _n(val, default=0):
    """Safely convert any value to float, returning default on failure."""
    if val is None:
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default



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

        if data.get("status") == "no_options":
            analysis["alerts"].append({
                "type": "INFO", "ticker": data.get("ticker", "UNKNOWN"),
                "message": data.get("note", "Sin opciones disponibles (mercado europeo)"), "severity": "low"
            })
            continue
        ticker = data["ticker"]
        analysis["tickers_analyzed"].append(ticker)

        calls = data.get("calls", [])
        puts = data.get("puts", [])

        call_volume = sum(_n(c.get("volume", 0)) for c in calls)
        put_volume = sum(_n(p.get("volume", 0)) for p in puts)
        call_oi = sum(_n(c.get("openInterest", 0)) for c in calls)
        put_oi = sum(_n(p.get("openInterest", 0)) for p in puts)

        # For synthetic options (volume=0), use the data's own put_call_ratio
        is_synthetic = data.get("source") == "synthetic_black_scholes" or (call_volume == 0 and put_volume == 0)
        if is_synthetic:
            # Use count-based ratio from the original data
            data_pcr = _n(data.get("put_call_ratio", 1.0))
            call_volume = max(len(calls), 1)
            put_volume = round(call_volume * data_pcr)

        total_put_volume += put_volume
        total_call_volume += call_volume

        call_ivs = [_n(c.get("impliedVolatility", 0)) for c in calls if c.get("impliedVolatility")]
        put_ivs = [_n(p.get("impliedVolatility", 0)) for p in puts if p.get("impliedVolatility")]

        avg_call_iv = _safe_avg(call_ivs)
        avg_put_iv = _safe_avg(put_ivs)
        iv_skew = avg_put_iv - avg_call_iv

        greeks_agg = _aggregate_greeks(calls, puts)
        # Only detect unusual activity from real market data, not synthetic
        if not is_synthetic:
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
        vol = _n(opt.get("volume", 0))
        oi = _n(opt.get("openInterest", 0))
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
