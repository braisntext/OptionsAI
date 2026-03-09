"""
FIFO Engine — Rebuild open lots, closed positions, and aggregate positions
from raw transactions using First-In-First-Out matching.
"""

from collections import deque
from datetime import datetime
from . import database as db


def rebuild_positions(email, account_id=None, symbol=None):
    """
    Recompute FIFO lots, closed positions, and aggregate positions.

    Scope:
      - symbol given → rebuild only that symbol within account
      - account_id given (no symbol) → rebuild all symbols in that account
      - neither → rebuild everything for the user
    """
    scopes = _get_rebuild_scopes(email, account_id, symbol)

    for acct_id, sym in scopes:
        _rebuild_single(email, acct_id, sym)


def _get_rebuild_scopes(email, account_id=None, symbol=None):
    """Determine (account_id, symbol) pairs to rebuild."""
    if account_id and symbol:
        return [(account_id, symbol)]

    accounts = db.get_accounts(email)
    if account_id:
        accounts = [a for a in accounts if a['id'] == account_id]

    scopes = []
    for acct in accounts:
        if symbol:
            scopes.append((acct['id'], symbol))
        else:
            # Get all symbols with transactions in this account
            symbols = _get_account_symbols(email, acct['id'])
            for sym in symbols:
                scopes.append((acct['id'], sym))

    return scopes


def _get_account_symbols(email, account_id):
    """Get distinct symbols with buy/sell/split transactions in an account."""
    txs = db.get_transactions_for_fifo(email, account_id, '%')
    # get_transactions_for_fifo uses exact match, so query directly
    from . import database as _db
    with _db._conn() as c:
        rows = c.execute(
            '''SELECT DISTINCT symbol FROM investment_transactions
               WHERE email = ? COLLATE NOCASE AND account_id = ?
                 AND tx_type IN ('buy','sell','split')''',
            (email.lower(), account_id)
        ).fetchall()
    return [r['symbol'] for r in rows]


def _rebuild_single(email, account_id, symbol):
    """Rebuild FIFO for a single (account, symbol) pair."""
    # 1. Clear computed data
    db.delete_lots(email, account_id, symbol)
    db.delete_closed(email, account_id, symbol)
    db.delete_position(email, account_id, symbol)

    # 2. Fetch transactions in chronological order
    txs = db.get_transactions_for_fifo(email, account_id, symbol)
    if not txs:
        return

    # 3. FIFO matching
    open_lots = deque()

    for tx in txs:
        if tx['tx_type'] == 'buy':
            qty = tx['quantity']
            cost_per_unit = (tx['price_eur'] or tx['price']) + \
                            ((tx['commission_eur'] or tx['commission'] or 0) / qty if qty else 0)
            open_lots.append({
                'tx_id': tx['id'],
                'date': tx['tx_date'],
                'remaining_qty': qty,
                'original_qty': qty,
                'cost_per_unit_eur': cost_per_unit,
            })

        elif tx['tx_type'] == 'sell':
            remaining = tx['quantity']
            sell_qty = tx['quantity']
            sell_price_per_unit = (tx['price_eur'] or tx['price']) - \
                                 ((tx['commission_eur'] or tx['commission'] or 0) / sell_qty if sell_qty else 0)

            while remaining > 0 and open_lots:
                lot = open_lots[0]
                matched = min(remaining, lot['remaining_qty'])

                buy_date = lot['date']
                sell_date = tx['tx_date']
                try:
                    holding_days = (datetime.strptime(sell_date, '%Y-%m-%d') -
                                   datetime.strptime(buy_date, '%Y-%m-%d')).days
                except (ValueError, TypeError):
                    holding_days = 0

                db.insert_closed(
                    email=email,
                    account_id=account_id,
                    symbol=symbol,
                    buy_date=buy_date,
                    sell_date=sell_date,
                    buy_tx_id=lot['tx_id'],
                    sell_tx_id=tx['id'],
                    quantity=matched,
                    cost_eur=round(matched * lot['cost_per_unit_eur'], 6),
                    proceeds_eur=round(matched * sell_price_per_unit, 6),
                    realized_pl_eur=round(matched * (sell_price_per_unit - lot['cost_per_unit_eur']), 6),
                    holding_days=holding_days,
                )

                lot['remaining_qty'] -= matched
                remaining -= matched

                if lot['remaining_qty'] <= 1e-9:
                    open_lots.popleft()

        elif tx['tx_type'] == 'split':
            # tx.quantity = split ratio (e.g., 4 for 4:1 split)
            ratio = tx['quantity']
            if ratio > 0:
                for lot in open_lots:
                    lot['remaining_qty'] *= ratio
                    lot['original_qty'] *= ratio
                    lot['cost_per_unit_eur'] /= ratio

    # 4. Persist remaining open lots
    for lot in open_lots:
        if lot['remaining_qty'] > 1e-9:
            db.insert_lot(
                email=email,
                account_id=account_id,
                symbol=symbol,
                buy_date=lot['date'],
                buy_tx_id=lot['tx_id'],
                original_quantity=lot['original_qty'],
                remaining_quantity=lot['remaining_qty'],
                cost_per_unit_eur=lot['cost_per_unit_eur'],
            )

    # 5. Compute aggregate position
    active_lots = [l for l in open_lots if l['remaining_qty'] > 1e-9]
    if active_lots:
        total_qty = sum(l['remaining_qty'] for l in active_lots)
        total_cost = sum(l['remaining_qty'] * l['cost_per_unit_eur'] for l in active_lots)
        avg_cost = total_cost / total_qty if total_qty > 0 else 0
        earliest_date = min(l['date'] for l in active_lots)

        db.upsert_position(
            email=email,
            account_id=account_id,
            symbol=symbol,
            open_date=earliest_date,
            quantity=round(total_qty, 8),
            avg_cost_eur=round(avg_cost, 6),
            total_cost_eur=round(total_cost, 6),
        )
