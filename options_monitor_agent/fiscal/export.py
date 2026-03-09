"""
Fiscal data export — CSV and printable HTML for accountants (gestorías).
Aggregates across all statements for a given user + tax year.
"""

import csv
import io
from datetime import datetime

from . import database as db
from .tax_engine import get_aggregated_summary, CASILLA_DESCRIPTIONS


def generate_csv(email, tax_year):
    """Generate a multi-section CSV export with all fiscal data for a year."""
    stmt_ids = db.get_user_statement_ids(email, tax_year)
    if not stmt_ids:
        return None

    summary = get_aggregated_summary(email, tax_year)
    trades = db.get_trades_multi(stmt_ids)
    dividends = db.get_dividends_multi(stmt_ids)
    interest = db.get_interest_multi(stmt_ids)
    withholdings = db.get_withholdings_multi(stmt_ids)

    buf = io.StringIO()
    w = csv.writer(buf, delimiter=';')

    # Header
    w.writerow([f'Resumen Fiscal {tax_year}'])
    w.writerow([f'Generado: {datetime.now().strftime("%Y-%m-%d %H:%M")}'])
    brokers = ', '.join(set(s['broker'] for s in summary['statements']))
    w.writerow([f'Brokers: {brokers}'])
    w.writerow([])

    # Casillas summary
    w.writerow(['RESUMEN CASILLAS'])
    w.writerow(['Casilla', 'Descripción', 'Importe EUR'])
    for cas in ('0027', '0029', '0328', '0588', 'retenciones'):
        data = summary['casillas'].get(cas, {})
        w.writerow([cas, CASILLA_DESCRIPTIONS.get(cas, ''), f"{data.get('total', 0):.2f}"])
    w.writerow([])

    # P&L breakdown
    w.writerow(['DESGLOSE P&L POR TIPO'])
    w.writerow(['Tipo', 'Ganancias EUR', 'Pérdidas EUR', 'Neto EUR', 'Operaciones'])
    for cat in ('stocks', 'options', 'forex'):
        p = summary['pnl'].get(cat, {})
        label = {'stocks': 'Acciones', 'options': 'Opciones', 'forex': 'Forex'}[cat]
        w.writerow([label, f"{p.get('gains', 0):.2f}", f"{p.get('losses', 0):.2f}",
                     f"{p.get('net', 0):.2f}", p.get('count', 0)])
    w.writerow([])

    # Trades
    stock_trades = [t for t in trades if t.get('asset_category') == 'Stocks']
    option_trades = [t for t in trades if t.get('asset_category') != 'Stocks']

    if stock_trades:
        w.writerow(['OPERACIONES — ACCIONES'])
        w.writerow(['Broker', 'Fecha', 'Símbolo', 'Descripción', 'Cantidad',
                     'Precio', 'Divisa', 'Importe EUR', 'Coste EUR', 'Comisión EUR', 'P/L EUR', 'Código'])
        for t in stock_trades:
            w.writerow([t.get('broker', ''), t.get('trade_date', ''), t.get('symbol', ''),
                         t.get('description', ''), t.get('quantity', ''),
                         f"{t.get('trade_price', 0):.4f}", t.get('currency', ''),
                         f"{t.get('proceeds_eur', 0):.2f}", f"{t.get('basis_eur', 0):.2f}",
                         f"{t.get('commission_eur', 0):.2f}", f"{t.get('realized_pl_eur', 0):.2f}",
                         t.get('code', '')])
        w.writerow([])

    if option_trades:
        w.writerow(['OPERACIONES — OPCIONES'])
        w.writerow(['Broker', 'Fecha', 'Subyacente', 'Tipo', 'Strike', 'Vencimiento',
                     'Cantidad', 'Precio', 'Divisa', 'Importe EUR', 'Coste EUR',
                     'Comisión EUR', 'P/L EUR', 'Código'])
        for t in option_trades:
            w.writerow([t.get('broker', ''), t.get('trade_date', ''),
                         t.get('underlying', t.get('symbol', '')),
                         t.get('option_type', ''), t.get('strike', ''), t.get('expiry', ''),
                         t.get('quantity', ''), f"{t.get('trade_price', 0):.4f}",
                         t.get('currency', ''), f"{t.get('proceeds_eur', 0):.2f}",
                         f"{t.get('basis_eur', 0):.2f}", f"{t.get('commission_eur', 0):.2f}",
                         f"{t.get('realized_pl_eur', 0):.2f}", t.get('code', '')])
        w.writerow([])

    # Dividends
    if dividends:
        w.writerow(['DIVIDENDOS'])
        w.writerow(['Broker', 'Fecha', 'Símbolo', 'Descripción', 'Importe bruto', 'Divisa', 'Importe EUR'])
        for d in dividends:
            w.writerow([d.get('broker', ''), d.get('pay_date', ''), d.get('symbol', ''),
                         d.get('description', ''), f"{d.get('gross_amount', 0):.2f}",
                         d.get('currency', ''), f"{d.get('gross_amount_eur', 0):.2f}"])
        w.writerow([])

    # Interest
    if interest:
        w.writerow(['INTERESES'])
        w.writerow(['Broker', 'Fecha', 'Descripción', 'Importe', 'Divisa', 'Importe EUR'])
        for i in interest:
            w.writerow([i.get('broker', ''), i.get('pay_date', ''), i.get('description', ''),
                         f"{i.get('amount', 0):.2f}", i.get('currency', ''),
                         f"{i.get('amount_eur', 0):.2f}"])
        w.writerow([])

    # Withholdings
    if withholdings:
        w.writerow(['RETENCIONES'])
        w.writerow(['Broker', 'Fecha', 'Símbolo', 'País', 'Tipo', 'Importe', 'Divisa', 'Importe EUR'])
        for wh in withholdings:
            w.writerow([wh.get('broker', ''), wh.get('pay_date', ''), wh.get('symbol', ''),
                         wh.get('country', ''), wh.get('tax_type', ''),
                         f"{wh.get('amount', 0):.2f}", wh.get('currency', ''),
                         f"{wh.get('amount_eur', 0):.2f}"])

    return buf.getvalue()


def _esc(text):
    """HTML-escape a string."""
    if text is None:
        return ''
    return str(text).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')


def _fmt(val, decimals=2):
    """Format a number for display."""
    if val is None:
        return '0.00'
    return f"{float(val):,.{decimals}f}"


def _color(val):
    """CSS color class for positive/negative."""
    if val is None:
        return ''
    return 'color:#16a34a' if float(val) >= 0 else 'color:#dc2626'


def generate_html(email, tax_year):
    """Generate a standalone, printable HTML report for an accountant."""
    stmt_ids = db.get_user_statement_ids(email, tax_year)
    if not stmt_ids:
        return None

    summary = get_aggregated_summary(email, tax_year)
    trades = db.get_trades_multi(stmt_ids)
    dividends = db.get_dividends_multi(stmt_ids)
    interest = db.get_interest_multi(stmt_ids)
    withholdings = db.get_withholdings_multi(stmt_ids)

    brokers = ', '.join(set(s['broker'] for s in summary['statements']))
    now = datetime.now().strftime('%Y-%m-%d %H:%M')

    # Build casillas rows
    casillas_rows = ''
    for cas in ('0027', '0029', '0328', '0588', 'retenciones'):
        data = summary['casillas'].get(cas, {})
        total = data.get('total', 0)
        casillas_rows += f'''<tr>
            <td><strong>{_esc(cas)}</strong></td>
            <td>{_esc(CASILLA_DESCRIPTIONS.get(cas, ''))}</td>
            <td style="text-align:right;{_color(total)}">{_fmt(total)} €</td>
        </tr>'''

    # P&L rows
    pnl_rows = ''
    total_net = 0
    for cat in ('stocks', 'options', 'forex'):
        p = summary['pnl'].get(cat, {})
        label = {'stocks': 'Acciones', 'options': 'Opciones', 'forex': 'Forex'}[cat]
        net = p.get('net', 0)
        total_net += net
        pnl_rows += f'''<tr>
            <td>{label}</td>
            <td style="text-align:right;color:#16a34a">{_fmt(p.get('gains', 0))} €</td>
            <td style="text-align:right;color:#dc2626">{_fmt(p.get('losses', 0))} €</td>
            <td style="text-align:right;{_color(net)}">{_fmt(net)} €</td>
            <td style="text-align:center">{p.get('count', 0)}</td>
        </tr>'''
    pnl_rows += f'''<tr style="font-weight:700;border-top:2px solid #333">
        <td>Total</td><td></td><td></td>
        <td style="text-align:right;{_color(total_net)}">{_fmt(total_net)} €</td><td></td>
    </tr>'''

    # Income summary
    inc = summary['income']

    # Trades table
    trades_rows = ''
    for t in trades:
        pl = t.get('realized_pl_eur', 0) or 0
        cat_label = 'Opción' if t.get('asset_category') != 'Stocks' else 'Acción'
        symbol = t.get('underlying', t.get('symbol', '')) if cat_label == 'Opción' else t.get('symbol', '')
        trades_rows += f'''<tr>
            <td>{_esc(t.get('broker',''))}</td><td>{_esc(t.get('trade_date',''))}</td>
            <td>{cat_label}</td><td>{_esc(symbol)}</td>
            <td style="text-align:right">{_esc(t.get('quantity',''))}</td>
            <td style="text-align:right">{_fmt(t.get('proceeds_eur',0))} €</td>
            <td style="text-align:right">{_fmt(t.get('basis_eur',0))} €</td>
            <td style="text-align:right">{_fmt(t.get('commission_eur',0))} €</td>
            <td style="text-align:right;{_color(pl)}">{_fmt(pl)} €</td>
        </tr>'''

    # Dividends table
    div_rows = ''
    for d in dividends:
        div_rows += f'''<tr>
            <td>{_esc(d.get('broker',''))}</td><td>{_esc(d.get('pay_date',''))}</td>
            <td>{_esc(d.get('symbol',''))}</td><td>{_esc(d.get('description',''))}</td>
            <td style="text-align:right">{_fmt(d.get('gross_amount_eur',0))} €</td>
        </tr>'''

    # Interest table
    int_rows = ''
    for i in interest:
        int_rows += f'''<tr>
            <td>{_esc(i.get('broker',''))}</td><td>{_esc(i.get('pay_date',''))}</td>
            <td>{_esc(i.get('description',''))}</td>
            <td style="text-align:right">{_fmt(i.get('amount_eur',0))} €</td>
        </tr>'''

    # Withholdings table
    wh_rows = ''
    for wh in withholdings:
        wh_rows += f'''<tr>
            <td>{_esc(wh.get('broker',''))}</td><td>{_esc(wh.get('pay_date',''))}</td>
            <td>{_esc(wh.get('symbol',''))}</td><td>{_esc(wh.get('country',''))}</td>
            <td>{_esc(wh.get('tax_type',''))}</td>
            <td style="text-align:right;color:#dc2626">{_fmt(wh.get('amount_eur',0))} €</td>
        </tr>'''

    return f'''<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<title>Informe Fiscal {tax_year}</title>
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ font-family: 'Segoe UI', system-ui, sans-serif; font-size:11pt; color:#1a1a1a; background:#fff; padding:2cm; }}
  h1 {{ font-size:18pt; margin-bottom:4px; }}
  h2 {{ font-size:13pt; margin:24px 0 8px; padding-bottom:4px; border-bottom:2px solid #333; }}
  .meta {{ font-size:9pt; color:#666; margin-bottom:20px; }}
  table {{ width:100%; border-collapse:collapse; margin-bottom:16px; font-size:9.5pt; }}
  th {{ background:#f0f0f0; text-align:left; padding:6px 8px; border:1px solid #ddd; font-weight:600; }}
  td {{ padding:5px 8px; border:1px solid #eee; }}
  tr:nth-child(even) {{ background:#fafafa; }}
  .summary-grid {{ display:grid; grid-template-columns:1fr 1fr; gap:16px; margin-bottom:20px; }}
  .summary-box {{ border:1px solid #ddd; border-radius:8px; padding:12px; }}
  .summary-box h3 {{ font-size:11pt; margin-bottom:8px; }}
  .summary-box .amount {{ font-size:14pt; font-weight:700; }}
  @media print {{
    body {{ padding:1cm; }}
    h2 {{ page-break-after:avoid; }}
    table {{ page-break-inside:auto; }}
    tr {{ page-break-inside:avoid; }}
  }}
</style>
</head>
<body>
<h1>📋 Informe Fiscal — Ejercicio {tax_year}</h1>
<p class="meta">Generado: {_esc(now)} &nbsp;|&nbsp; Brokers: {_esc(brokers)} &nbsp;|&nbsp; Usuario: {_esc(email)}</p>

<h2>Resumen por Casillas IRPF</h2>
<table>
  <thead><tr><th>Casilla</th><th>Concepto</th><th style="text-align:right">Importe</th></tr></thead>
  <tbody>{casillas_rows}</tbody>
</table>

<h2>Desglose de Pérdidas y Ganancias</h2>
<table>
  <thead><tr><th>Tipo</th><th style="text-align:right">Ganancias</th><th style="text-align:right">Pérdidas</th><th style="text-align:right">Neto</th><th style="text-align:center">Oper.</th></tr></thead>
  <tbody>{pnl_rows}</tbody>
</table>

<div class="summary-grid">
  <div class="summary-box">
    <h3>💰 Rendimientos del Capital</h3>
    <p>Dividendos brutos: <span class="amount" style="color:#16a34a">{_fmt(inc['dividends']['gross'])} €</span></p>
    <p>Intereses: <span class="amount" style="color:#16a34a">{_fmt(inc['interest']['total'])} €</span></p>
    <p>Dividendos netos (tras retenciones ext.): <span class="amount">{_fmt(inc['net_dividends'])} €</span></p>
  </div>
  <div class="summary-box">
    <h3>🏛️ Retenciones</h3>
    <p>Retención extranjera (0588): <span class="amount">{_fmt(inc['withholdings']['foreign'])} €</span></p>
    <p>Retención española: <span class="amount">{_fmt(inc['withholdings']['domestic'])} €</span></p>
    <p>Total: <span class="amount">{_fmt(inc['withholdings']['total'])} €</span></p>
  </div>
</div>

<h2>Detalle de Operaciones ({len(trades)})</h2>
<table>
  <thead><tr><th>Broker</th><th>Fecha</th><th>Tipo</th><th>Símbolo</th><th style="text-align:right">Cant.</th><th style="text-align:right">Importe €</th><th style="text-align:right">Coste €</th><th style="text-align:right">Com. €</th><th style="text-align:right">P/L €</th></tr></thead>
  <tbody>{trades_rows if trades_rows else '<tr><td colspan="9" style="text-align:center;color:#999">Sin operaciones</td></tr>'}</tbody>
</table>

<h2>Dividendos ({len(dividends)})</h2>
<table>
  <thead><tr><th>Broker</th><th>Fecha</th><th>Símbolo</th><th>Descripción</th><th style="text-align:right">Importe €</th></tr></thead>
  <tbody>{div_rows if div_rows else '<tr><td colspan="5" style="text-align:center;color:#999">Sin dividendos</td></tr>'}</tbody>
</table>

<h2>Intereses ({len(interest)})</h2>
<table>
  <thead><tr><th>Broker</th><th>Fecha</th><th>Descripción</th><th style="text-align:right">Importe €</th></tr></thead>
  <tbody>{int_rows if int_rows else '<tr><td colspan="4" style="text-align:center;color:#999">Sin intereses</td></tr>'}</tbody>
</table>

<h2>Retenciones ({len(withholdings)})</h2>
<table>
  <thead><tr><th>Broker</th><th>Fecha</th><th>Símbolo</th><th>País</th><th>Tipo</th><th style="text-align:right">Importe €</th></tr></thead>
  <tbody>{wh_rows if wh_rows else '<tr><td colspan="6" style="text-align:center;color:#999">Sin retenciones</td></tr>'}</tbody>
</table>

<p style="margin-top:30px;font-size:8pt;color:#999;text-align:center">
  Documento generado automáticamente por Small Smart Tools — Importador Fiscal. Los datos proceden de los extractos importados y deben ser revisados por un profesional.
</p>
</body>
</html>'''
