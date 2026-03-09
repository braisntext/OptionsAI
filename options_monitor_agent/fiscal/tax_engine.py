"""
Spanish tax calculation engine.
Maps parsed broker data to IRPF (Renta) casillas.

Key casillas:
- 0027: Intereses de cuentas bancarias
- 0029: Dividendos y participaciones en beneficios
- 0328-0335: Ganancias y pérdidas patrimoniales (transmisiones)
- 0588: Deducción por doble imposición internacional

Rules:
- Options expired (Ep): loss = premium paid, gain = premium received
- Assignment (A): premium integrates into stock cost basis
- AutoFX (AFx): not a separate taxable event, integrates into underlying
- FIFO for stock lot matching
- All amounts must be in EUR at ECB rate on transaction date
"""

from collections import defaultdict
from . import database as db
from .exchange_rates import to_eur


def calculate_taxes(stmt_id):
    """
    Run full tax calculation for a statement.
    Returns list of tax result dicts ready for insert_tax_results.
    """
    trades = db.get_trades(stmt_id)
    dividends = db.get_dividends(stmt_id)
    interest = db.get_interest(stmt_id)
    withholdings = db.get_withholdings(stmt_id)
    forex = db.get_forex(stmt_id)

    results = []

    # 1. Stock gains/losses (casillas 0328-0335)
    stock_results = _calculate_stock_gains(trades)
    results.extend(stock_results)

    # 2. Options gains/losses (casillas 0328-0335)
    option_results = _calculate_option_gains(trades)
    results.extend(option_results)

    # 3. Dividends (casilla 0029)
    div_results = _calculate_dividends(dividends)
    results.extend(div_results)

    # 4. Interest (casilla 0027)
    int_results = _calculate_interest(interest)
    results.extend(int_results)

    # 5. Withholding taxes
    wh_results = _calculate_withholdings(withholdings)
    results.extend(wh_results)

    # 6. Forex P/L (casillas 0328-0335, only non-AFx)
    fx_results = _calculate_forex(forex)
    results.extend(fx_results)

    # Save to DB
    db.insert_tax_results(stmt_id, results)

    return results


# ── Stock Gains ──────────────────────────────────────────────────────────────

def _calculate_stock_gains(trades):
    """
    Calculate realized gains/losses from stock trades.
    Uses FIFO matching. Only considers closed positions.
    """
    stock_trades = [t for t in trades if t['asset_category'] == 'Stocks']

    # Group by symbol
    by_symbol = defaultdict(list)
    for t in stock_trades:
        by_symbol[t['symbol']].append(t)

    results = []
    total_gain_eur = 0

    for symbol, symbol_trades in by_symbol.items():
        # Separate buys and sells
        buys = []
        sells = []
        for t in sorted(symbol_trades, key=lambda x: x['trade_date']):
            qty = t['quantity']
            if qty > 0:
                # Negative proceeds = purchase
                buys.append(t)
            elif qty < 0:
                sells.append(t)

        # FIFO matching
        for sell in sells:
            sell_qty = abs(sell['quantity'])
            sell_date = sell['trade_date']
            sell_price_eur = _trade_price_eur(sell)

            remaining = sell_qty
            cost_basis_eur = 0
            buy_date = None

            for buy in buys:
                if remaining <= 0:
                    break
                available = buy.get('_remaining', buy['quantity'])
                if available <= 0:
                    continue

                matched = min(remaining, available)
                buy_price_eur = _trade_price_eur(buy)
                cost_basis_eur += matched * buy_price_eur
                if buy_date is None:
                    buy_date = buy['trade_date']

                buy['_remaining'] = available - matched
                remaining -= matched

            proceeds_eur = sell_qty * sell_price_eur
            gain_eur = proceeds_eur - cost_basis_eur
            # Subtract commission in EUR
            comm_eur = abs(sell.get('commission_eur') or
                          to_eur(sell.get('commission', 0), sell['currency'], sell_date) or 0)
            gain_eur -= comm_eur
            total_gain_eur += gain_eur

            results.append({
                'casilla': '0328',
                'category': 'stocks',
                'description': f'{symbol}: venta {sell_qty} acciones',
                'amount_eur': round(gain_eur, 2),
                'details': {
                    'symbol': symbol,
                    'sell_date': sell_date,
                    'buy_date': buy_date,
                    'quantity': sell_qty,
                    'proceeds_eur': round(proceeds_eur, 2),
                    'cost_basis_eur': round(cost_basis_eur, 2),
                    'commission_eur': round(comm_eur, 2),
                }
            })

    return results


# ── Option Gains ─────────────────────────────────────────────────────────────

def _calculate_option_gains(trades):
    """
    Calculate realized gains/losses from option trades.

    Key rules:
    - Sell to open (O) + Buy to close (C): gain = premium received - premium paid - commissions
    - Sell to open (O) + Expired (Ep): gain = full premium received - commissions
    - Assignment (A): premium integrates into stock cost → NOT a separate P/L event
    """
    option_trades = [t for t in trades if t['asset_category'] == 'Options']

    # Group by symbol (each unique option contract)
    by_symbol = defaultdict(list)
    for t in option_trades:
        by_symbol[t['symbol']].append(t)

    results = []

    for symbol, symbol_trades in by_symbol.items():
        sorted_trades = sorted(symbol_trades, key=lambda x: x['trade_date'])

        opens = []
        closes = []

        for t in sorted_trades:
            code = t.get('code', '')
            codes = set(c.strip() for c in code.split(';'))

            if 'O' in codes:
                opens.append(t)
            elif 'C' in codes or 'Ep' in codes:
                closes.append(t)

        # Match open → close
        for i, close in enumerate(closes):
            close_code = set(c.strip() for c in close.get('code', '').split(';'))

            # Assignment: premium goes into stock cost basis, skip as option P/L
            if 'A' in close_code:
                continue

            # Find matching open
            if i < len(opens):
                open_trade = opens[i]
            else:
                open_trade = None

            if open_trade:
                # Premium received (open sell) in EUR
                open_date = open_trade['trade_date']
                premium_received_eur = abs(
                    open_trade.get('proceeds_eur') or
                    to_eur(open_trade['proceeds'], open_trade['currency'], open_date) or 0
                )

                # Premium paid to close (often 0 for expired)
                close_date = close['trade_date']
                premium_paid_eur = abs(
                    close.get('proceeds_eur') or
                    to_eur(close.get('proceeds', 0), close['currency'], close_date) or 0
                )

                # Commissions
                comm_open_eur = abs(
                    open_trade.get('commission_eur') or
                    to_eur(open_trade.get('commission', 0), open_trade['currency'], open_date) or 0
                )
                comm_close_eur = abs(
                    close.get('commission_eur') or
                    to_eur(close.get('commission', 0), close['currency'], close_date) or 0
                )

                gain_eur = premium_received_eur - premium_paid_eur - comm_open_eur - comm_close_eur

                is_expired = 'Ep' in close_code

                results.append({
                    'casilla': '0328',
                    'category': 'options',
                    'description': f'{symbol}: {"expirada" if is_expired else "cerrada"}',
                    'amount_eur': round(gain_eur, 2),
                    'details': {
                        'symbol': symbol,
                        'underlying': open_trade.get('underlying', ''),
                        'option_type': open_trade.get('option_type', ''),
                        'strike': open_trade.get('strike'),
                        'expiry': open_trade.get('expiry', ''),
                        'open_date': open_date,
                        'close_date': close_date,
                        'premium_received_eur': round(premium_received_eur, 2),
                        'premium_paid_eur': round(premium_paid_eur, 2),
                        'commission_eur': round(comm_open_eur + comm_close_eur, 2),
                        'expired': is_expired,
                    }
                })

    return results


# ── Dividends ────────────────────────────────────────────────────────────────

def _calculate_dividends(dividends):
    """Aggregate dividends for casilla 0029."""
    results = []
    total_eur = 0

    for d in dividends:
        amount_eur = d.get('gross_amount_eur') or to_eur(
            d['gross_amount'], d['currency'], d['pay_date']
        ) or 0
        total_eur += amount_eur

        results.append({
            'casilla': '0029',
            'category': 'dividends',
            'description': f'{d["symbol"]}: {"pago en lieu" if d.get("is_in_lieu") else "dividendo"} ({d["pay_date"]})',
            'amount_eur': round(amount_eur, 2),
            'details': {
                'symbol': d['symbol'],
                'pay_date': d['pay_date'],
                'gross_amount': d['gross_amount'],
                'currency': d['currency'],
                'description': d.get('description', ''),
            }
        })

    return results


# ── Interest ─────────────────────────────────────────────────────────────────

def _calculate_interest(interest):
    """Aggregate interest for casilla 0027."""
    results = []

    for i in interest:
        amount_eur = i.get('amount_eur') or to_eur(
            i['amount'], i['currency'], i['pay_date']
        ) or 0

        results.append({
            'casilla': '0027',
            'category': 'interest',
            'description': f'Intereses ({i["pay_date"]})',
            'amount_eur': round(amount_eur, 2),
            'details': {
                'pay_date': i['pay_date'],
                'amount': i['amount'],
                'currency': i['currency'],
                'description': i.get('description', ''),
            }
        })

    return results


# ── Withholding Taxes ────────────────────────────────────────────────────────

def _calculate_withholdings(withholdings):
    """
    Calculate withholding tax deductions.
    - Foreign withholdings (US) → casilla 0588 (doble imposición internacional)
    - Spanish withholdings → retenciones (reduce tax payable)
    """
    results = []

    for w in withholdings:
        amount_eur = w.get('amount_eur') or to_eur(
            w['amount'], w['currency'], w['pay_date']
        ) or 0

        country = w.get('country', '')

        if country == 'ES':
            casilla = 'retenciones'
            description = f'Retención española ({w["pay_date"]})'
        else:
            casilla = '0588'
            description = f'Retención en origen {country} ({w["pay_date"]})'

        results.append({
            'casilla': casilla,
            'category': 'withholdings',
            'description': description,
            'amount_eur': round(abs(amount_eur), 2),  # store as positive
            'details': {
                'pay_date': w['pay_date'],
                'amount': w['amount'],
                'currency': w['currency'],
                'country': country,
                'tax_type': w.get('tax_type', ''),
                'symbol': w.get('symbol', ''),
                'description': w.get('description', ''),
            }
        })

    return results


# ── Forex P/L ────────────────────────────────────────────────────────────────

def _calculate_forex(forex):
    """
    Calculate forex gains/losses.
    Only manual forex trades count — AFx (auto conversions from trading) don't.
    """
    results = []

    for f in forex:
        if f.get('is_auto_fx'):
            continue  # AutoFX doesn't generate separate taxable event

        mtm_eur = f.get('mtm_eur', 0)
        if mtm_eur == 0:
            continue

        results.append({
            'casilla': '0328',
            'category': 'forex',
            'description': f'Forex {f["symbol"]} ({f["trade_date"]})',
            'amount_eur': round(mtm_eur, 2),
            'details': {
                'symbol': f['symbol'],
                'trade_date': f['trade_date'],
                'quantity': f['quantity'],
                'trade_price': f['trade_price'],
                'proceeds': f['proceeds'],
                'currency': f['currency'],
            }
        })

    return results


# ── Helpers ──────────────────────────────────────────────────────────────────

def _trade_price_eur(trade):
    """Get per-unit trade price in EUR."""
    if trade['currency'] == 'EUR':
        return abs(trade['trade_price'])
    # Use pre-calculated EUR values if available
    if trade.get('proceeds_eur') and trade['quantity']:
        return abs(trade['proceeds_eur'] / trade['quantity'])
    # Convert
    eur = to_eur(abs(trade['trade_price']), trade['currency'], trade['trade_date'])
    return eur or 0


# ── Summary ──────────────────────────────────────────────────────────────────

def get_tax_summary(stmt_id):
    """
    Get a summary of tax results grouped by casilla.
    Returns dict: {casilla: {total, items: [...]}}
    """
    results = db.get_tax_results(stmt_id)

    summary = {}
    for r in results:
        casilla = r['casilla']
        if casilla not in summary:
            summary[casilla] = {
                'casilla': casilla,
                'total': 0,
                'items': [],
            }
        summary[casilla]['total'] += r['amount_eur']
        summary[casilla]['items'].append(r)

    # Round totals
    for k in summary:
        summary[k]['total'] = round(summary[k]['total'], 2)

    return summary


CASILLA_DESCRIPTIONS = {
    '0027': 'Intereses de cuentas bancarias y depósitos',
    '0029': 'Dividendos y participaciones en beneficios',
    '0328': 'Ganancias y pérdidas patrimoniales — transmisión de elementos patrimoniales (valor de transmisión)',
    '0331': 'Ganancias y pérdidas patrimoniales — transmisión de elementos patrimoniales (valor de adquisición)',
    '0588': 'Deducción por doble imposición internacional — rentas obtenidas en el extranjero',
    'retenciones': 'Retenciones e ingresos a cuenta ya practicados (reducen cuota)',
}


def get_aggregated_summary(email, tax_year):
    """
    Aggregate P&L and income data across all statements for a user+year.
    Returns a dict with: statements, pnl (by asset type), income, casillas.
    """
    stmt_ids = db.get_user_statement_ids(email, tax_year)
    if not stmt_ids:
        return None

    # Statements metadata
    stmts = []
    for sid in stmt_ids:
        s = db.get_statement(sid, email)
        if s:
            stmts.append({
                'id': s['id'], 'broker': s['broker'],
                'account_id': s['account_id'], 'status': s['status'],
            })

    # Tax results across all statements
    tax_results = db.get_tax_results_multi(stmt_ids)

    # P&L by asset type
    pnl = {}
    for cat in ('stocks', 'options', 'forex'):
        gains = sum(r['amount_eur'] for r in tax_results
                    if r['category'] == cat and r['amount_eur'] > 0)
        losses = sum(r['amount_eur'] for r in tax_results
                     if r['category'] == cat and r['amount_eur'] < 0)
        count = sum(1 for r in tax_results if r['category'] == cat)
        pnl[cat] = {
            'gains': round(gains, 2),
            'losses': round(losses, 2),
            'net': round(gains + losses, 2),
            'count': count,
        }

    # Income
    div_total = sum(r['amount_eur'] for r in tax_results if r['category'] == 'dividends')
    div_count = sum(1 for r in tax_results if r['category'] == 'dividends')
    int_total = sum(r['amount_eur'] for r in tax_results if r['category'] == 'interest')
    int_count = sum(1 for r in tax_results if r['category'] == 'interest')

    wh_foreign = sum(r['amount_eur'] for r in tax_results
                     if r['category'] == 'withholdings' and r['casilla'] == '0588')
    wh_domestic = sum(r['amount_eur'] for r in tax_results
                      if r['category'] == 'withholdings' and r['casilla'] == 'retenciones')
    wh_count = sum(1 for r in tax_results if r['category'] == 'withholdings')

    income = {
        'dividends': {'gross': round(div_total, 2), 'count': div_count},
        'interest': {'total': round(int_total, 2), 'count': int_count},
        'withholdings': {
            'total': round(wh_foreign + wh_domestic, 2),
            'foreign': round(wh_foreign, 2),
            'domestic': round(wh_domestic, 2),
            'count': wh_count,
        },
        'net_dividends': round(div_total - wh_foreign, 2),
    }

    # Casillas aggregation
    casillas = {}
    for r in tax_results:
        cas = r['casilla']
        if cas not in casillas:
            casillas[cas] = {'total': 0, 'description': CASILLA_DESCRIPTIONS.get(cas, cas)}
        casillas[cas]['total'] += r['amount_eur']
    for k in casillas:
        casillas[k]['total'] = round(casillas[k]['total'], 2)

    return {
        'tax_year': tax_year,
        'statements': stmts,
        'pnl': pnl,
        'income': income,
        'casillas': casillas,
    }
