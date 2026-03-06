"""
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
        return f"Total analyses: {len(self.history)}\nFirst: {self.history[0]['timestamp']}\nLast: {self.history[-1]['timestamp']}"

    def get_ticker_trend(self, ticker, metric="avg_call_iv", last_n=10):
        trend = []
        for entry in self.history[-last_n:]:
            s = entry.get("analysis", {}).get("summary", {})
            if ticker in s:
                trend.append({"timestamp": entry["timestamp"], "value": s[ticker].get(metric, 0)})
        return trend
