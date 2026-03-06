""" Generate synthetic options chains using Black-Scholes model """
import math
from datetime import datetime, timedelta
from scipy.stats import norm

def black_scholes_call(S, K, T, r, sigma):
    """Calculate Black-Scholes call option price"""
    if T <= 0 or sigma <= 0:
        return max(S - K, 0)
    d1 = (math.log(S/K) + (r + 0.5*sigma**2)*T) / (sigma*math.sqrt(T))
    d2 = d1 - sigma*math.sqrt(T)
    return S*norm.cdf(d1) - K*math.exp(-r*T)*norm.cdf(d2)

def black_scholes_put(S, K, T, r, sigma):
    """Calculate Black-Scholes put option price"""
    if T <= 0 or sigma <= 0:
        return max(K - S, 0)
    d1 = (math.log(S/K) + (r + 0.5*sigma**2)*T) / (sigma*math.sqrt(T))
    d2 = d1 - sigma*math.sqrt(T)
    return K*math.exp(-r*T)*norm.cdf(-d2) - S*norm.cdf(-d1)

def generate_synthetic_options(ticker, current_price, historical_volatility, stock_data):
    """Generate realistic synthetic options chain based on Black-Scholes"""
    # Use historical volatility as IV estimate (convert from percentage)
    iv = historical_volatility / 100.0
    r = 0.03  # risk-free rate
    
    # Generate strikes around current price (±20% in 2.5% increments)
    strikes = []
    price_step = current_price * 0.025  # 2.5% steps
    for i in range(-8, 9):  # 17 strikes total
        strike = round(current_price + (i * price_step), 2)
        if strike > 0:
            strikes.append(strike)
    
    # Generate 3 expiration dates (1 month, 3 months, 6 months)
    expirations = [
        (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d'),
        (datetime.now() + timedelta(days=90)).strftime('%Y-%m-%d'),
        (datetime.now() + timedelta(days=180)).strftime('%Y-%m-%d')
    ]
    
    all_calls = []
    all_puts = []
    
    for exp_date in expirations:
        days_to_expiry = (datetime.strptime(exp_date, '%Y-%m-%d') - datetime.now()).days
        T = days_to_expiry / 365.0
        
        for strike in strikes:
            # Calculate theoretical prices
            call_price = black_scholes_call(current_price, strike, T, r, iv)
            put_price = black_scholes_put(current_price, strike, T, r, iv)
            
            # Add bid-ask spread (1-2% of price)
            call_spread = max(call_price * 0.015, 0.01)
            put_spread = max(put_price * 0.015, 0.01)
            
            # CALL option
            all_calls.append({
                'strike': strike,
                'lastPrice': round(call_price, 2),
                'bid': round(call_price - call_spread, 2),
                'ask': round(call_price + call_spread, 2),
                'impliedVolatility': round(iv, 4),
                'volume': 0,
                'openInterest': 0,
                'inTheMoney': current_price > strike,
                'expiration': exp_date,
                'type': 'CALL',
                'daysToExpiry': days_to_expiry,
                'source': 'synthetic'
            })
            
            # PUT option
            all_puts.append({
                'strike': strike,
                'lastPrice': round(put_price, 2),
                'bid': round(put_price - put_spread, 2),
                'ask': round(put_price + put_spread, 2),
                'impliedVolatility': round(iv, 4),
                'volume': 0,
                'openInterest': 0,
                'inTheMoney': current_price < strike,
                'expiration': exp_date,
                'type': 'PUT',
                'daysToExpiry': days_to_expiry,
                'source': 'synthetic'
            })
    
    return {
        'ticker': ticker,
        'current_price': current_price,
        'timestamp': datetime.now().isoformat(),
        'stock_data': stock_data,
        'historical_volatility': round(historical_volatility, 2),
        'expirations_analyzed': expirations,
        'calls': all_calls,
        'puts': all_puts,
        'calls_count': len(all_calls),
        'puts_count': len(all_puts),
        'put_call_ratio': round(len(all_puts) / len(all_calls), 4) if all_calls else 0,
        'status': 'success',
        'source': 'synthetic_black_scholes',
        'note': f'Synthetic options generated using Black-Scholes with {round(historical_volatility, 1)}% historical volatility'
    }
