"""
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
                K = float(opt.get("strike", 0) or 0)
                iv = float(opt.get("impliedVolatility", 0) or 0)
                days = int(float(opt.get("daysToExpiry", 0) or 0))
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
