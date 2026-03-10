"""
Fiscal Import — Flask blueprint with all API routes.
"""

import os
import re
from flask import Blueprint, request, jsonify, session, render_template, Response

# Path setup
import sys
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_DASHBOARD_DIR = os.path.join(_THIS_DIR, '..', 'dashboard')
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

from . import database as db
from .exchange_rates import to_eur, ensure_rates_cached
from .parsers import detect_broker, get_parser, available_brokers
from .tax_engine import calculate_taxes, get_tax_summary, get_aggregated_summary, CASILLA_DESCRIPTIONS
from .export import generate_csv, generate_html

fiscal_bp = Blueprint('fiscal', __name__)


@fiscal_bp.before_request
def _check_fiscal_access():
    """Fiscal app requires a paid plan."""
    email = session.get('email', '').lower()
    if not email:
        return jsonify({'status': 'error', 'message': 'No autenticado'}), 401
    # Import here to avoid circular imports at module level
    sys.path.insert(0, _DASHBOARD_DIR) if _DASHBOARD_DIR not in sys.path else None
    from subscribers import has_app_access
    if not has_app_access(email, 'fiscal'):
        return jsonify({'status': 'error', 'message': 'Fiscal requiere un plan de pago'}), 403

# Max upload size: 5 MB
MAX_FILE_SIZE = 5 * 1024 * 1024
ALLOWED_EXTENSIONS = {'.csv', '.pdf'}


def _get_email():
    return session.get('email', '').lower()


def _validate_file(file_obj):
    """Validate uploaded file. Returns (content, error).
    For PDFs: returns raw bytes.
    For CSVs: returns decoded text string.
    """
    if not file_obj or not file_obj.filename:
        return None, 'No se ha seleccionado ningún archivo'

    filename = file_obj.filename
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        return None, f'Formato no soportado: {ext}. Use CSV o PDF.'

    content = file_obj.read()
    if len(content) > MAX_FILE_SIZE:
        return None, f'Archivo demasiado grande (máx {MAX_FILE_SIZE // 1024 // 1024} MB)'

    if len(content) == 0:
        return None, 'El archivo está vacío'

    # PDF files: return raw bytes (parsers handle binary directly)
    if ext == '.pdf':
        return content, None

    # CSV files: decode to text
    try:
        text = content.decode('utf-8')
    except UnicodeDecodeError:
        try:
            text = content.decode('latin-1')
        except Exception:
            return None, 'No se puede leer el archivo. Asegúrese de que es un CSV válido.'

    return text, None


# ── Upload & Parse ───────────────────────────────────────────────────────────

@fiscal_bp.route('/api/fiscal/upload', methods=['POST'])
def upload_statement():
    """Upload and parse a broker statement CSV."""
    email = _get_email()
    if not email:
        return jsonify({'status': 'error', 'message': 'No autenticado'}), 401

    file_obj = request.files.get('file')
    content, error = _validate_file(file_obj)
    if error:
        return jsonify({'status': 'error', 'message': error}), 400

    # Optional second file (required for Trade Republic)
    extra_content = None
    file_obj2 = request.files.get('file2')
    if file_obj2 and file_obj2.filename:
        extra_content, error2 = _validate_file(file_obj2)
        if error2:
            return jsonify({'status': 'error', 'message': f'Segundo archivo: {error2}'}), 400

    # Detect or use specified broker
    broker_name = request.form.get('broker', '').strip()
    if broker_name:
        parser = get_parser(broker_name)
        if not parser:
            return jsonify({'status': 'error',
                           'message': f'Broker no soportado: {broker_name}'}), 400
    else:
        parser = detect_broker(content)
        if not parser and extra_content:
            parser = detect_broker(extra_content)
        if not parser:
            return jsonify({'status': 'error',
                           'message': 'No se pudo detectar el broker. Selecciónelo manualmente.'}), 400

    # Parse (pass extra_content for brokers that need multiple files)
    try:
        parsed = parser.parse(content, extra_content=extra_content)
    except Exception as e:
        return jsonify({'status': 'error',
                       'message': f'Error al parsear el archivo: {str(e)[:200]}'}), 400

    if not parsed.tax_year:
        return jsonify({'status': 'error',
                       'message': 'No se pudo determinar el año fiscal'}), 400

    # Ensure exchange rates are cached for this year
    try:
        ensure_rates_cached(parsed.tax_year)
    except Exception:
        pass  # Will try to fetch on demand later

    # Create statement record
    stmt_id = db.create_statement(
        email=email,
        broker=parsed.broker,
        tax_year=parsed.tax_year,
        filename=file_obj.filename,
        account_id=parsed.account_id,
        base_currency=parsed.base_currency,
    )

    # Convert all amounts to EUR and store
    try:
        _convert_and_store(stmt_id, parsed)
        # Calculate taxes
        tax_results = calculate_taxes(stmt_id)
        db.update_statement_status(stmt_id, 'completed')
    except Exception as e:
        db.update_statement_status(stmt_id, 'error', str(e)[:500])
        return jsonify({'status': 'error',
                       'message': f'Error procesando datos: {str(e)[:200]}'}), 500

    # Auto-import into Investments app
    inv_imported = None
    try:
        from options_monitor_agent.investments.import_fiscal import import_fiscal_statements
        inv_imported = import_fiscal_statements(email, [stmt_id])
    except Exception:
        pass  # Non-critical — user can import manually later

    return jsonify({
        'status': 'ok',
        'statement_id': stmt_id,
        'broker': parsed.broker,
        'tax_year': parsed.tax_year,
        'account': parsed.account_id,
        'summary': {
            'trades': len(parsed.trades),
            'dividends': len(parsed.dividends),
            'interest': len(parsed.interest),
            'withholdings': len(parsed.withholdings),
            'forex': len(parsed.forex),
            'positions': len(parsed.positions),
        },
        'tax_results': len(tax_results),
        'investments_imported': inv_imported,
    })


def _convert_and_store(stmt_id, parsed):
    """Convert parsed data to EUR and store in database."""

    # Trades — convert to EUR
    for t in parsed.trades:
        date = t['trade_date']
        ccy = t['currency']
        t['proceeds_eur'] = to_eur(t['proceeds'], ccy, date)
        t['commission_eur'] = to_eur(t.get('commission', 0), ccy, date)
        t['basis_eur'] = to_eur(t.get('basis', 0), ccy, date)
        t['realized_pl_eur'] = to_eur(t.get('realized_pl', 0), ccy, date)
        rate = None
        if ccy != 'EUR':
            from .exchange_rates import get_rate
            rate = get_rate(ccy, date)
        t['exchange_rate'] = rate

    db.insert_trades(stmt_id, parsed.trades)

    # Dividends
    for d in parsed.dividends:
        d['gross_amount_eur'] = to_eur(d['gross_amount'], d['currency'], d['pay_date'])
        if d['currency'] != 'EUR':
            from .exchange_rates import get_rate
            d['exchange_rate'] = get_rate(d['currency'], d['pay_date'])
    db.insert_dividends(stmt_id, parsed.dividends)

    # Interest
    for i in parsed.interest:
        i['amount_eur'] = to_eur(i['amount'], i['currency'], i['pay_date'])
        if i['currency'] != 'EUR':
            from .exchange_rates import get_rate
            i['exchange_rate'] = get_rate(i['currency'], i['pay_date'])
    db.insert_interest(stmt_id, parsed.interest)

    # Withholdings
    for w in parsed.withholdings:
        w['amount_eur'] = to_eur(w['amount'], w['currency'], w['pay_date'])
        if w['currency'] != 'EUR':
            from .exchange_rates import get_rate
            w['exchange_rate'] = get_rate(w['currency'], w['pay_date'])
    db.insert_withholdings(stmt_id, parsed.withholdings)

    # Forex
    db.insert_forex(stmt_id, parsed.forex)

    # Open positions — convert to EUR
    for p in parsed.positions:
        ccy = p['currency']
        # Use year-end date for positions
        stmt = db.get_statement(stmt_id)
        date = f"{stmt['tax_year']}-12-31"
        p['cost_basis_eur'] = to_eur(p.get('cost_basis', 0), ccy, date)
        p['market_value_eur'] = to_eur(p.get('market_value', 0), ccy, date)
        p['unrealized_pl_eur'] = to_eur(p.get('unrealized_pl', 0), ccy, date)
    db.insert_positions(stmt_id, parsed.positions)


# ── Data retrieval endpoints ─────────────────────────────────────────────────

@fiscal_bp.route('/api/fiscal/statements')
def list_statements():
    """List all statements for the authenticated user."""
    email = _get_email()
    if not email:
        return jsonify({'status': 'error', 'message': 'No autenticado'}), 401
    statements = db.get_user_statements(email)
    return jsonify({'status': 'ok', 'statements': statements})


@fiscal_bp.route('/api/fiscal/statement/<int:stmt_id>')
def get_statement_detail(stmt_id):
    """Get full detail for one statement."""
    email = _get_email()
    if not email:
        return jsonify({'status': 'error', 'message': 'No autenticado'}), 401

    stmt = db.get_statement(stmt_id, email)
    if not stmt:
        return jsonify({'status': 'error', 'message': 'Extracto no encontrado'}), 404

    return jsonify({
        'status': 'ok',
        'statement': stmt,
        'trades': db.get_trades(stmt_id),
        'dividends': db.get_dividends(stmt_id),
        'interest': db.get_interest(stmt_id),
        'withholdings': db.get_withholdings(stmt_id),
        'forex': db.get_forex(stmt_id),
        'positions': db.get_positions(stmt_id),
    })


@fiscal_bp.route('/api/fiscal/statement/<int:stmt_id>/taxes')
def get_taxes(stmt_id):
    """Get calculated tax results for a statement."""
    email = _get_email()
    if not email:
        return jsonify({'status': 'error', 'message': 'No autenticado'}), 401

    stmt = db.get_statement(stmt_id, email)
    if not stmt:
        return jsonify({'status': 'error', 'message': 'Extracto no encontrado'}), 404

    summary = get_tax_summary(stmt_id)

    return jsonify({
        'status': 'ok',
        'tax_year': stmt['tax_year'],
        'broker': stmt['broker'],
        'summary': summary,
        'casilla_descriptions': CASILLA_DESCRIPTIONS,
    })


@fiscal_bp.route('/api/fiscal/statement/<int:stmt_id>/trades')
def get_trades_api(stmt_id):
    """Get trades for a statement, optionally filtered."""
    email = _get_email()
    if not email:
        return jsonify({'status': 'error', 'message': 'No autenticado'}), 401

    stmt = db.get_statement(stmt_id, email)
    if not stmt:
        return jsonify({'status': 'error', 'message': 'Extracto no encontrado'}), 404

    category = request.args.get('category')
    return jsonify({'status': 'ok', 'trades': db.get_trades(stmt_id, category)})


@fiscal_bp.route('/api/fiscal/statement/<int:stmt_id>/dividends')
def get_dividends_api(stmt_id):
    email = _get_email()
    if not email:
        return jsonify({'status': 'error', 'message': 'No autenticado'}), 401
    stmt = db.get_statement(stmt_id, email)
    if not stmt:
        return jsonify({'status': 'error', 'message': 'Extracto no encontrado'}), 404
    return jsonify({'status': 'ok', 'dividends': db.get_dividends(stmt_id)})


@fiscal_bp.route('/api/fiscal/statement/<int:stmt_id>/interest')
def get_interest_api(stmt_id):
    email = _get_email()
    if not email:
        return jsonify({'status': 'error', 'message': 'No autenticado'}), 401
    stmt = db.get_statement(stmt_id, email)
    if not stmt:
        return jsonify({'status': 'error', 'message': 'Extracto no encontrado'}), 404
    return jsonify({'status': 'ok', 'interest': db.get_interest(stmt_id)})


@fiscal_bp.route('/api/fiscal/statement/<int:stmt_id>/withholdings')
def get_withholdings_api(stmt_id):
    email = _get_email()
    if not email:
        return jsonify({'status': 'error', 'message': 'No autenticado'}), 401
    stmt = db.get_statement(stmt_id, email)
    if not stmt:
        return jsonify({'status': 'error', 'message': 'Extracto no encontrado'}), 404
    return jsonify({'status': 'ok', 'withholdings': db.get_withholdings(stmt_id)})


@fiscal_bp.route('/api/fiscal/statement/<int:stmt_id>/forex')
def get_forex_api(stmt_id):
    email = _get_email()
    if not email:
        return jsonify({'status': 'error', 'message': 'No autenticado'}), 401
    stmt = db.get_statement(stmt_id, email)
    if not stmt:
        return jsonify({'status': 'error', 'message': 'Extracto no encontrado'}), 404
    return jsonify({'status': 'ok', 'forex': db.get_forex(stmt_id)})


@fiscal_bp.route('/api/fiscal/statement/<int:stmt_id>/positions')
def get_positions_api(stmt_id):
    email = _get_email()
    if not email:
        return jsonify({'status': 'error', 'message': 'No autenticado'}), 401
    stmt = db.get_statement(stmt_id, email)
    if not stmt:
        return jsonify({'status': 'error', 'message': 'Extracto no encontrado'}), 404
    return jsonify({'status': 'ok', 'positions': db.get_positions(stmt_id)})


@fiscal_bp.route('/api/fiscal/brokers')
def list_brokers():
    """List available broker parsers."""
    return jsonify({'status': 'ok', 'brokers': available_brokers()})


@fiscal_bp.route('/api/fiscal/statement/<int:stmt_id>', methods=['DELETE'])
def delete_statement(stmt_id):
    """Delete a statement and all associated data."""
    email = _get_email()
    if not email:
        return jsonify({'status': 'error', 'message': 'No autenticado'}), 401

    stmt = db.get_statement(stmt_id, email)
    if not stmt:
        return jsonify({'status': 'error', 'message': 'Extracto no encontrado'}), 404

    # Delete related data from Investments app first
    try:
        from options_monitor_agent.investments.import_fiscal import delete_fiscal_from_investments
        delete_fiscal_from_investments(email, stmt_id)
    except Exception:
        pass  # Investments module may not have data for this statement

    with db._conn() as c:
        c.execute('DELETE FROM fiscal_statements WHERE id = ?', (stmt_id,))
        c.commit()

    return jsonify({'status': 'ok', 'message': 'Extracto eliminado'})


# ── Cross-statement aggregation routes ────────────────────────────────────────

@fiscal_bp.route('/api/fiscal/years')
def list_years():
    """List tax years with statement metadata."""
    email = _get_email()
    if not email:
        return jsonify({'status': 'error', 'message': 'No autenticado'}), 401
    years = db.get_user_years(email)
    return jsonify({'status': 'ok', 'years': years})


@fiscal_bp.route('/api/fiscal/summary')
def fiscal_summary():
    """Aggregated P&L and income across all statements for a year."""
    email = _get_email()
    if not email:
        return jsonify({'status': 'error', 'message': 'No autenticado'}), 401

    year = request.args.get('year', type=int)
    if not year:
        return jsonify({'status': 'error', 'message': 'Parámetro year requerido'}), 400

    data = get_aggregated_summary(email, year)
    if not data:
        return jsonify({'status': 'error', 'message': 'No hay datos para el año indicado'}), 404

    return jsonify({'status': 'ok', **data})


@fiscal_bp.route('/api/fiscal/export')
def export_data():
    """Export fiscal data for a year in CSV or HTML format."""
    email = _get_email()
    if not email:
        return jsonify({'status': 'error', 'message': 'No autenticado'}), 401

    year = request.args.get('year', type=int)
    fmt = request.args.get('format', 'csv')

    if not year:
        return jsonify({'status': 'error', 'message': 'Parámetro year requerido'}), 400

    if fmt == 'csv':
        content = generate_csv(email, year)
        if not content:
            return jsonify({'status': 'error', 'message': 'No hay datos'}), 404
        return Response(content, mimetype='text/csv; charset=utf-8',
                        headers={'Content-Disposition': f'attachment; filename=fiscal_{year}_resumen.csv'})
    elif fmt == 'html':
        content = generate_html(email, year)
        if not content:
            return jsonify({'status': 'error', 'message': 'No hay datos'}), 404
        return Response(content, mimetype='text/html; charset=utf-8')
    else:
        return jsonify({'status': 'error', 'message': 'Formato no soportado (csv o html)'}), 400
