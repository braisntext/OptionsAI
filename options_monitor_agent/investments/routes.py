"""
Investments — Flask blueprint with all API routes for the investment management app.
"""

import os
import re
import sys
from flask import Blueprint, request, jsonify, session

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

from . import database as db
from .fifo_engine import rebuild_positions
from .import_fiscal import get_available_fiscal_statements, import_fiscal_statements
from .price_service import search_symbols, get_live_price, refresh_prices, get_price_history

investments_bp = Blueprint('investments', __name__)


def _get_email():
    return session.get('email', '').lower()


def _auth_guard():
    """Returns (email, error_response). If email is None, return the error."""
    email = _get_email()
    if not email:
        return None, (jsonify({'status': 'error', 'message': 'No autenticado'}), 401)
    return email, None


# ── Accounts ─────────────────────────────────────────────────────────────────

@investments_bp.route('/api/investments/accounts')
def get_accounts():
    email, err = _auth_guard()
    if err:
        return err
    accounts = db.get_accounts(email)
    return jsonify({'status': 'ok', 'accounts': accounts})


@investments_bp.route('/api/investments/accounts', methods=['POST'])
def create_account():
    email, err = _auth_guard()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    broker = (data.get('broker') or '').strip()
    account_name = (data.get('account_name') or '').strip()

    if not broker or len(broker) > 30 or not re.match(r'^[A-Za-z0-9 ]+$', broker):
        return jsonify({'status': 'error', 'message': 'Broker inválido'}), 400
    if len(account_name) > 50:
        return jsonify({'status': 'error', 'message': 'Nombre demasiado largo'}), 400

    try:
        acct_id = db.create_account(email, broker, account_name)
    except Exception:
        return jsonify({'status': 'error', 'message': 'La cuenta ya existe'}), 409

    return jsonify({'status': 'ok', 'id': acct_id}), 201


@investments_bp.route('/api/investments/accounts/<int:acct_id>', methods=['DELETE'])
def delete_account(acct_id):
    email, err = _auth_guard()
    if err:
        return err
    acct = db.get_account(acct_id, email)
    if not acct:
        return jsonify({'status': 'error', 'message': 'Cuenta no encontrada'}), 404
    db.delete_account(acct_id, email)
    return jsonify({'status': 'ok'})


# ── Transactions ─────────────────────────────────────────────────────────────

@investments_bp.route('/api/investments/transactions')
def get_transactions():
    email, err = _auth_guard()
    if err:
        return err

    account_id = request.args.get('account_id', type=int)
    symbol = request.args.get('symbol', '').strip().upper() or None
    tx_type = request.args.get('tx_type', '').strip() or None
    date_from = request.args.get('date_from', '').strip() or None
    date_to = request.args.get('date_to', '').strip() or None
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 50, type=int), 200)

    tx_types = [tx_type] if tx_type else None

    rows, total = db.get_transactions(
        email, account_id=account_id, symbol=symbol,
        tx_types=tx_types, date_from=date_from, date_to=date_to,
        page=page, per_page=per_page
    )

    return jsonify({
        'status': 'ok',
        'transactions': rows,
        'total': total,
        'page': page,
        'per_page': per_page,
    })


@investments_bp.route('/api/investments/transactions', methods=['POST'])
def create_transaction():
    email, err = _auth_guard()
    if err:
        return err

    data = request.get_json(silent=True) or {}

    # Validate required fields
    account_id = data.get('account_id')
    symbol = (data.get('symbol') or '').strip().upper()
    tx_type = (data.get('tx_type') or '').strip()
    tx_date = (data.get('tx_date') or '').strip()
    quantity = data.get('quantity')
    price = data.get('price')

    if not account_id:
        return jsonify({'status': 'error', 'message': 'account_id requerido'}), 400
    if not symbol or len(symbol) > 20 or not re.match(r'^[A-Z0-9.]+$', symbol):
        return jsonify({'status': 'error', 'message': 'Símbolo inválido'}), 400
    if tx_type not in ('buy', 'sell', 'split', 'transfer'):
        return jsonify({'status': 'error', 'message': 'Tipo de transacción inválido'}), 400
    if not tx_date or not re.match(r'^\d{4}-\d{2}-\d{2}$', tx_date):
        return jsonify({'status': 'error', 'message': 'Fecha inválida (YYYY-MM-DD)'}), 400
    try:
        quantity = float(quantity)
        price = float(price)
    except (TypeError, ValueError):
        return jsonify({'status': 'error', 'message': 'Cantidad y precio deben ser numéricos'}), 400
    if quantity <= 0:
        return jsonify({'status': 'error', 'message': 'Cantidad debe ser > 0'}), 400
    if price < 0:
        return jsonify({'status': 'error', 'message': 'Precio no puede ser negativo'}), 400

    # Verify account ownership
    acct = db.get_account(account_id, email)
    if not acct:
        return jsonify({'status': 'error', 'message': 'Cuenta no encontrada'}), 404

    currency = (data.get('currency') or 'EUR').strip().upper()[:3]
    commission = max(float(data.get('commission', 0) or 0), 0)

    # Convert to EUR
    price_eur = None
    commission_eur = 0
    exchange_rate = None
    if currency != 'EUR':
        try:
            from options_monitor_agent.fiscal.exchange_rates import to_eur, get_rate
            price_eur = to_eur(price, currency, tx_date)
            commission_eur = to_eur(commission, currency, tx_date) or 0
            exchange_rate = get_rate(currency, tx_date)
        except Exception:
            pass
    else:
        price_eur = price
        commission_eur = commission

    tx_id = db.insert_transaction(
        email=email,
        account_id=account_id,
        symbol=symbol,
        tx_type=tx_type,
        tx_date=tx_date,
        quantity=quantity,
        price=price,
        currency=currency,
        price_eur=price_eur,
        commission=commission,
        commission_eur=commission_eur,
        exchange_rate=exchange_rate,
        description=data.get('description'),
        notes=data.get('notes'),
    )

    # Rebuild FIFO for this symbol
    rebuild_positions(email, account_id=account_id, symbol=symbol)

    return jsonify({'status': 'ok', 'id': tx_id}), 201


@investments_bp.route('/api/investments/transactions/<int:tx_id>', methods=['DELETE'])
def delete_transaction(tx_id):
    email, err = _auth_guard()
    if err:
        return err

    result = db.delete_transaction(tx_id, email)
    if result is None:
        return jsonify({'status': 'error', 'message': 'Transacción no encontrada'}), 404

    account_id, symbol = result
    rebuild_positions(email, account_id=account_id, symbol=symbol)

    return jsonify({'status': 'ok'})


# ── Import ───────────────────────────────────────────────────────────────────

@investments_bp.route('/api/investments/import/fiscal/available')
def fiscal_available():
    email, err = _auth_guard()
    if err:
        return err
    statements = get_available_fiscal_statements(email)
    return jsonify({'status': 'ok', 'statements': statements})


@investments_bp.route('/api/investments/import/fiscal', methods=['POST'])
def import_from_fiscal():
    email, err = _auth_guard()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    statement_ids = data.get('statement_ids', [])

    if not statement_ids or not isinstance(statement_ids, list):
        return jsonify({'status': 'error', 'message': 'statement_ids requerido'}), 400
    if len(statement_ids) > 50:
        return jsonify({'status': 'error', 'message': 'Máximo 50 statements'}), 400

    # Validate all are ints
    try:
        statement_ids = [int(s) for s in statement_ids]
    except (TypeError, ValueError):
        return jsonify({'status': 'error', 'message': 'IDs inválidos'}), 400

    result = import_fiscal_statements(email, statement_ids)

    return jsonify({'status': 'ok', 'imported': result})


# ── Positions & Portfolio ────────────────────────────────────────────────────

@investments_bp.route('/api/investments/positions')
def get_positions():
    email, err = _auth_guard()
    if err:
        return err

    account_id = request.args.get('account_id', type=int)
    positions = db.get_positions(email, account_id=account_id)

    # Enrich with live market data
    symbols = list({p['symbol'] for p in positions})
    if symbols:
        prices = refresh_prices(symbols)
        for p in positions:
            sym = p['symbol']
            if sym in prices:
                lp = prices[sym]['price_eur']
                p['current_price_eur'] = lp
                p['market_value_eur'] = round(p['quantity'] * lp, 2) if lp else None
                if lp and p['total_cost_eur']:
                    mv = p['quantity'] * lp
                    p['unrealized_pl_eur'] = round(mv - p['total_cost_eur'], 2)
                    p['unrealized_pl_pct'] = round(
                        (mv - p['total_cost_eur']) / p['total_cost_eur'] * 100, 2
                    ) if p['total_cost_eur'] else 0
            else:
                p['current_price_eur'] = None
                p['market_value_eur'] = None
                p['unrealized_pl_eur'] = None
                p['unrealized_pl_pct'] = None

    return jsonify({'status': 'ok', 'positions': positions})


@investments_bp.route('/api/investments/positions/<symbol>')
def get_position_detail(symbol):
    email, err = _auth_guard()
    if err:
        return err
    symbol = symbol.upper()
    detail = db.get_position_detail(email, symbol)

    # Add live price
    price_data = get_live_price(symbol)
    detail['live_price'] = price_data

    return jsonify({'status': 'ok', **detail})


@investments_bp.route('/api/investments/portfolio/summary')
def portfolio_summary():
    email, err = _auth_guard()
    if err:
        return err

    summary = db.get_portfolio_summary(email)

    # Add market value from live positions
    positions = db.get_positions(email)
    symbols = list({p['symbol'] for p in positions})
    total_market_value = 0
    if symbols:
        prices = refresh_prices(symbols)
        for p in positions:
            sym = p['symbol']
            if sym in prices and prices[sym].get('price_eur'):
                total_market_value += p['quantity'] * prices[sym]['price_eur']
            else:
                total_market_value += p['total_cost_eur']  # fallback to cost

    summary['total_market_value_eur'] = round(total_market_value, 2)
    if summary['total_invested_eur'] > 0:
        unrealized = total_market_value - summary['total_invested_eur']
        summary['total_unrealized_pl_eur'] = round(unrealized, 2)
        summary['total_unrealized_pl_pct'] = round(
            unrealized / summary['total_invested_eur'] * 100, 2
        )
    else:
        summary['total_unrealized_pl_eur'] = 0
        summary['total_unrealized_pl_pct'] = 0

    # Allocation
    allocation = []
    for p in positions:
        sym = p['symbol']
        value = total_market_value
        sym_value = p['total_cost_eur']
        if symbols:
            prices_data = refresh_prices([sym])
            if sym in prices_data and prices_data[sym].get('price_eur'):
                sym_value = p['quantity'] * prices_data[sym]['price_eur']
        allocation.append({
            'symbol': sym,
            'value_eur': round(sym_value, 2),
            'pct': round(sym_value / value * 100, 2) if value > 0 else 0,
        })
    allocation.sort(key=lambda x: x['value_eur'], reverse=True)
    summary['allocation'] = allocation[:20]

    return jsonify({'status': 'ok', **summary})


# ── Dividends ────────────────────────────────────────────────────────────────

@investments_bp.route('/api/investments/dividends')
def get_dividends():
    email, err = _auth_guard()
    if err:
        return err

    symbol = request.args.get('symbol', '').strip().upper() or None
    year = request.args.get('year', type=int)
    account_id = request.args.get('account_id', type=int)
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 50, type=int), 200)

    rows, total, total_eur = db.get_dividends(
        email, symbol=symbol, year=year, account_id=account_id,
        page=page, per_page=per_page
    )

    return jsonify({
        'status': 'ok',
        'dividends': rows,
        'total': total,
        'total_amount_eur': round(total_eur, 2),
        'page': page,
    })


@investments_bp.route('/api/investments/dividends', methods=['POST'])
def create_dividend():
    email, err = _auth_guard()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    account_id = data.get('account_id')
    symbol = (data.get('symbol') or '').strip().upper()
    pay_date = (data.get('pay_date') or '').strip()
    amount = data.get('amount')

    if not account_id:
        return jsonify({'status': 'error', 'message': 'account_id requerido'}), 400
    if not symbol:
        return jsonify({'status': 'error', 'message': 'Símbolo requerido'}), 400
    if not pay_date or not re.match(r'^\d{4}-\d{2}-\d{2}$', pay_date):
        return jsonify({'status': 'error', 'message': 'Fecha inválida'}), 400
    try:
        amount = float(amount)
    except (TypeError, ValueError):
        return jsonify({'status': 'error', 'message': 'Importe inválido'}), 400

    acct = db.get_account(account_id, email)
    if not acct:
        return jsonify({'status': 'error', 'message': 'Cuenta no encontrada'}), 404

    currency = (data.get('currency') or 'EUR').strip().upper()[:3]
    withholding = max(float(data.get('withholding', 0) or 0), 0)

    amount_eur = amount
    withholding_eur = withholding
    exchange_rate = None
    if currency != 'EUR':
        try:
            from options_monitor_agent.fiscal.exchange_rates import to_eur, get_rate
            amount_eur = to_eur(amount, currency, pay_date) or 0
            withholding_eur = to_eur(withholding, currency, pay_date) or 0
            exchange_rate = get_rate(currency, pay_date)
        except Exception:
            pass

    div_id = db.insert_dividend(
        email=email,
        account_id=account_id,
        symbol=symbol,
        pay_date=pay_date,
        amount=amount,
        currency=currency,
        amount_eur=amount_eur,
        exchange_rate=exchange_rate,
        withholding=withholding,
        withholding_eur=withholding_eur,
    )

    return jsonify({'status': 'ok', 'id': div_id}), 201


# ── Charts ───────────────────────────────────────────────────────────────────

@investments_bp.route('/api/investments/chart/<symbol>')
def get_chart(symbol):
    email, err = _auth_guard()
    if err:
        return err

    symbol = symbol.upper()
    period = request.args.get('period', '1y')
    data = get_price_history(symbol, period)
    if not data:
        return jsonify({'status': 'error', 'message': 'No se encontraron datos'}), 404

    return jsonify({'status': 'ok', **data})


# ── Symbol Search ────────────────────────────────────────────────────────────

@investments_bp.route('/api/investments/search')
def symbol_search():
    email, err = _auth_guard()
    if err:
        return err

    q = (request.args.get('q') or '').strip()
    if not q or len(q) > 20:
        return jsonify({'status': 'ok', 'results': []})

    results = search_symbols(q)
    return jsonify({'status': 'ok', 'results': results})


# ── Closed Trades ────────────────────────────────────────────────────────────

@investments_bp.route('/api/investments/closed')
def get_closed():
    email, err = _auth_guard()
    if err:
        return err

    symbol = request.args.get('symbol', '').strip().upper() or None
    year = request.args.get('year', type=int)

    rows = db.get_closed_trades(email, symbol=symbol, year=year)
    total_realized = sum(r.get('realized_pl_eur', 0) for r in rows)

    return jsonify({
        'status': 'ok',
        'closed': rows,
        'total_realized_pl_eur': round(total_realized, 2),
    })
