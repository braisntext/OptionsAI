"""
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

                prices = {"price_1d": None, "price_3d": None, "price_7d": None}
                for days_check, attr in [(1, "price_1d"), (3, "price_3d"), (7, "price_7d")]:
                    if days_since >= days_check:
                        target = signal_time + timedelta(days=days_check)
                        tz = hist.index.tz
                        after = hist[hist.index >= pd.Timestamp(target, tz=tz)]
                        if not after.empty:
                            prices[attr] = float(after.iloc[0]["Close"])

                price_1d = prices["price_1d"]
                price_3d = prices["price_3d"]
                price_7d = prices["price_7d"]

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

        console.print(f"\n[bold cyan]📊 BACKTEST: {accuracy:.1f}% accuracy ({correct}/{len(evaluated)})[/bold cyan]")

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
