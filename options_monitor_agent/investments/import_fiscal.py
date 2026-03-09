"""
Import from Fiscal module — maps fiscal trades/dividends to investment data.
"""

from datetime import datetime, timedelta
from options_monitor_agent.fiscal import database as fiscal_db
from . import database as db
from .fifo_engine import rebuild_positions

# Asset categories worth importing (skip Forex, Bond Interest, etc.)
IMPORTABLE_CATEGORIES = {'Stocks', 'Equity and Index Options'}


def delete_fiscal_from_investments(email, stmt_id):
    """Delete all investment data that was imported from a fiscal statement,
    then rebuild FIFO for the affected symbols."""
    source_ref = str(stmt_id)
    affected = db.delete_by_source(email, 'fiscal_import', source_ref)
    for acct_id, symbol in affected:
        rebuild_positions(email, account_id=acct_id, symbol=symbol)
    return len(affected)


def get_available_fiscal_statements(email):
    """Get fiscal statements available for import, with import status."""
    statements = fiscal_db.get_user_statements(email)
    result = []
    for stmt in statements:
        if stmt['status'] != 'completed':
            continue
        stmt_id = str(stmt['id'])
        already_imported = db.check_duplicate_by_source(email, 'fiscal_import', stmt_id)
        trades = fiscal_db.get_trades(stmt['id'])
        divs = fiscal_db.get_dividends(stmt['id'])
        importable_trades = [t for t in trades if t.get('asset_category') in IMPORTABLE_CATEGORIES]

        result.append({
            'id': stmt['id'],
            'broker': stmt['broker'],
            'tax_year': stmt['tax_year'],
            'account_id': stmt.get('account_id', ''),
            'trade_count': len(importable_trades),
            'dividend_count': len(divs),
            'already_imported': already_imported,
        })
    return result


def import_fiscal_statements(email, statement_ids):
    """
    Import trades and dividends from fiscal statements into investments.
    Returns summary dict.
    """
    total_tx = 0
    total_div = 0
    total_skipped = 0
    affected_symbols = set()

    for stmt_id in statement_ids:
        stmt = fiscal_db.get_statement(stmt_id, email)
        if not stmt:
            continue

        source_ref = str(stmt_id)

        # Skip if already imported
        if db.check_duplicate_by_source(email, 'fiscal_import', source_ref):
            total_skipped += 1
            continue

        broker = stmt['broker']
        acct_name = stmt.get('account_id', '') or ''
        account_id = db.get_or_create_account(email, broker, acct_name)

        # Import trades
        trades = fiscal_db.get_trades(stmt_id)
        withholdings = fiscal_db.get_withholdings(stmt_id)
        tx_inserts = []
        for t in trades:
            if t.get('asset_category') not in IMPORTABLE_CATEGORIES:
                continue

            mapped = _map_fiscal_trade(t, source_ref, account_id)
            if mapped:
                tx_inserts.append(mapped)
                affected_symbols.add((account_id, mapped['symbol']))

        if tx_inserts:
            db.insert_transactions_bulk(email, tx_inserts)
            total_tx += len(tx_inserts)

        # Import dividends
        dividends = fiscal_db.get_dividends(stmt_id)
        div_inserts = []
        for d in dividends:
            mapped = _map_fiscal_dividend(d, stmt, account_id, withholdings, source_ref)
            if mapped:
                div_inserts.append(mapped)

        if div_inserts:
            db.insert_dividends_bulk(email, div_inserts)
            total_div += len(div_inserts)

    # Rebuild FIFO for all affected symbols
    for acct_id, symbol in affected_symbols:
        rebuild_positions(email, account_id=acct_id, symbol=symbol)

    return {
        'transactions': total_tx,
        'dividends': total_div,
        'skipped_statements': total_skipped,
        'statements_processed': len(statement_ids) - total_skipped,
    }


def _map_fiscal_trade(fiscal_trade, source_ref, account_id):
    """Map a fiscal_trades row to an investment_transactions dict."""
    qty = fiscal_trade.get('quantity', 0)
    if qty == 0:
        return None

    is_buy = qty > 0
    abs_qty = abs(qty)

    # Compute price_eur
    if is_buy:
        basis_eur = fiscal_trade.get('basis_eur')
        price_eur = (abs(basis_eur) / abs_qty) if basis_eur and abs_qty else None
    else:
        proceeds_eur = fiscal_trade.get('proceeds_eur')
        price_eur = (abs(proceeds_eur) / abs_qty) if proceeds_eur and abs_qty else None

    return {
        'account_id': account_id,
        'symbol': fiscal_trade['symbol'],
        'description': fiscal_trade.get('description'),
        'tx_type': 'buy' if is_buy else 'sell',
        'tx_date': fiscal_trade['trade_date'],
        'quantity': abs_qty,
        'price': abs(fiscal_trade.get('trade_price', 0)),
        'currency': fiscal_trade.get('currency', 'EUR'),
        'price_eur': price_eur,
        'commission': abs(fiscal_trade.get('commission', 0)),
        'commission_eur': abs(fiscal_trade.get('commission_eur', 0)),
        'exchange_rate': fiscal_trade.get('exchange_rate'),
        'source': 'fiscal_import',
        'source_ref': source_ref,
    }


def _map_fiscal_dividend(fiscal_div, stmt, account_id, withholdings, source_ref):
    """Map a fiscal dividend + matched withholding to investment_dividends."""
    wh = _find_matching_withholding(fiscal_div, withholdings)

    return {
        'account_id': account_id,
        'symbol': fiscal_div['symbol'],
        'pay_date': fiscal_div['pay_date'],
        'amount': fiscal_div['gross_amount'],
        'currency': fiscal_div.get('currency', 'EUR'),
        'amount_eur': fiscal_div.get('gross_amount_eur') or 0,
        'exchange_rate': fiscal_div.get('exchange_rate'),
        'withholding': abs(wh['amount']) if wh else 0,
        'withholding_eur': abs(wh.get('amount_eur', 0)) if wh else 0,
        'source': 'fiscal_import',
        'source_ref': source_ref,
    }


def _find_matching_withholding(dividend, withholdings):
    """Find withholding tax matching a dividend by symbol + date proximity."""
    symbol = dividend.get('symbol', '')
    pay_date = dividend.get('pay_date', '')

    if not pay_date:
        return None

    try:
        div_dt = datetime.strptime(pay_date, '%Y-%m-%d')
    except (ValueError, TypeError):
        return None

    best = None
    best_dist = timedelta(days=999)

    for wh in withholdings:
        if wh.get('symbol', '') != symbol:
            continue
        try:
            wh_dt = datetime.strptime(wh['pay_date'], '%Y-%m-%d')
        except (ValueError, TypeError):
            continue
        dist = abs(wh_dt - div_dt)
        if dist < timedelta(days=6) and dist < best_dist:
            best = wh
            best_dist = dist

    return best
