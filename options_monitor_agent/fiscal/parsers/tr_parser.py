"""
Trade Republic dual-PDF parser.

Processes two Trade Republic PDFs together:
  1. Tax Report  ("Informe de Actividad") — trades with ISINs, quantities, dates
  2. Account Statement ("Resumen de Estado de Cuenta") — dividends, interest, buy costs

Tax Report provides:
  - Clave I:  ETF purchases (quantities, dates)
  - Clave V:  Stock/bond buys (A) and sells (C) with quantities, dates, sell proceeds

Account Statement provides:
  - Dividends, interest payments
  - Transaction amounts used to fill buy costs from the Tax Report

Both PDFs are required for a complete import.
"""

import io
import re
from collections import defaultdict

from . import BrokerParser, ParsedStatement, register_parser

# ── Shared helpers ───────────────────────────────────────────────────────────

_ISIN_RE = re.compile(r'\b([A-Z]{2}[A-Z0-9]{9}\d)\b')

_MONTHS_ES = {
    'ene': 1, 'feb': 2, 'mar': 3, 'abr': 4, 'may': 5, 'jun': 6,
    'jul': 7, 'ago': 8, 'sept': 9, 'sep': 9, 'oct': 10, 'nov': 11, 'dic': 12,
}


def _parse_eur(text):
    """Parse European number '19.938,04' → 19938.04."""
    text = text.replace('\xa0', ' ').replace('€', '').strip()
    if not text:
        return 0.0
    m = re.match(r'[\d.,]+', text)
    if not m:
        return 0.0
    s = m.group().replace('.', '').replace(',', '.')
    try:
        return float(s)
    except ValueError:
        return 0.0


def _parse_date_dotted(text):
    """Parse '15.05.2024' → '2024-05-15'."""
    m = re.match(r'(\d{2})\.(\d{2})\.(\d{4})', text.strip())
    return f'{m.group(3)}-{m.group(2)}-{m.group(1)}' if m else None


def _parse_es_date(date_str, year):
    """Parse '11 ene' + year → '2024-01-11'."""
    parts = date_str.strip().split()
    if len(parts) < 2:
        return None
    try:
        day = int(parts[0])
        month = _MONTHS_ES.get(parts[1].lower().rstrip('.'))
        if not month:
            return None
        return f'{year:04d}-{month:02d}-{day:02d}'
    except (ValueError, IndexError):
        return None


# ── Tax Report column thresholds (from word x-coordinates) ───────────────────
_TR_ORIGIN  = 430   # A / C
_TR_QTY     = 465   # Número de valores
_TR_DATE1   = 520   # Fecha de incorporación  (buys)
_TR_DATE2   = 580   # Fecha de extinción      (sells)
_TR_FX      = 630   # Tipo de cambio
_TR_VEXT    = 665   # Valoración fecha extinción (sell value)
_TR_V31     = 720   # Valor 31/12 EUR (end-of-year value, NOT cost)

# ── Account Statement column thresholds ──────────────────────────────────────
_AS_CONTENT  = 80
_AS_ENTRADA  = 420
_AS_SALIDA   = 462
_AS_BALANCE  = 500

_TYPE_PREFIXES = [
    'Pago de intereses', 'Transacción con tarjeta', 'Transferencia',
    'Recompensa', 'Rendimientos', 'Comercio',
]

# ── Section markers for skipping header/footer lines ─────────────────────────
_TR_SKIP = {
    'Clientela:', 'Período:', 'Moneda:', 'Report ID:', 'Página',
    'Modelo 720', 'Modelo 721',
    'ISIN - Valor', 'Origen del', 'Número de', 'Fecha de', 'Tipo de',
    'Domicilio', 'Valoración en', 'Valor 31/12',
    'bien o', 'valores', 'incorporación', 'extinción', 'cambio',
    'derecho', 'activos', 'Total', 'Descargo', 'Notas explicativas',
    'Declaración informativa',
}

_AS_SKIP = {
    'FECHA', 'TIPO', 'DESCRIPCIÓN', 'ENTRADA', 'SALIDA', 'BALANCE',
    'Página', 'Creado en', 'Trade Republic Bank',
    'RESUMEN DE ESTADO', 'PRODUCTO', 'Cuenta de valores',
    'TRANSACCIONES DE CUENTA', 'DISCLAIMER', 'Estimado Cliente',
    'Brunnenstraße', 'AG Charlottenburg', 'ID-IVA',
}


def _group_lines(words, y_tol=5):
    """Group pdfplumber words into lines by y-coordinate."""
    if not words:
        return []
    ws = sorted(words, key=lambda w: (w['top'], w['x0']))
    lines, cur, cy = [], [], None
    for w in ws:
        if cy is not None and abs(w['top'] - cy) > y_tol:
            if cur:
                lines.append(sorted(cur, key=lambda w: w['x0']))
            cur, cy = [], None
        cur.append(w)
        cy = w['top'] if cy is None else (cy + w['top']) / 2
    if cur:
        lines.append(sorted(cur, key=lambda w: w['x0']))
    return lines


# ═════════════════════════════════════════════════════════════════════════════
@register_parser
class TradeRepublicParser(BrokerParser):

    @property
    def broker_name(self):
        return 'TRADE_REPUBLIC'

    # ── Detection ────────────────────────────────────────────────────────

    def detect(self, content):
        if isinstance(content, (bytes, bytearray)):
            text = self._quick_text(content)
        else:
            text = content
        return 'Trade Republic' in text and (
            'INFORME DE ACTIVIDAD' in text
            or 'RESUMEN DE ESTADO DE CUENTA' in text
            or 'TRANSACCIONES DE CUENTA' in text
        )

    # ── Main entry point ─────────────────────────────────────────────────

    def parse(self, content, extra_content=None, **kwargs):
        if not isinstance(content, (bytes, bytearray)):
            raise ValueError('Trade Republic parser requires PDF bytes')

        # Classify each PDF
        tax_report = None
        acct_stmt = None

        text1 = self._quick_text(content)
        if 'INFORME DE ACTIVIDAD' in text1:
            tax_report = content
        else:
            acct_stmt = content

        if extra_content and isinstance(extra_content, (bytes, bytearray)):
            text2 = self._quick_text(extra_content)
            if 'INFORME DE ACTIVIDAD' in text2:
                tax_report = extra_content
            else:
                acct_stmt = extra_content

        if not tax_report or not acct_stmt:
            raise ValueError(
                'Trade Republic requiere dos PDFs: '
                'el Informe Fiscal (Informe de Actividad) y '
                'el Extracto de Cuenta (Resumen de Estado de Cuenta). '
                'Sube ambos archivos a la vez.'
            )

        # 1. Tax Report → trades (buys + sells)
        trades, tax_year, account_id = self._parse_tax_report(tax_report)

        # 2. Account Statement → dividends, interest, and buy cost lookup
        dividends, interest, cost_map = self._parse_account_statement(
            acct_stmt, tax_year
        )

        # 3. Fill buy costs from Account Statement
        self._fill_buy_costs(trades, cost_map)

        result = ParsedStatement(
            broker='TRADE_REPUBLIC',
            account_id=account_id,
            tax_year=tax_year,
            base_currency='EUR',
        )
        result.trades = trades
        result.dividends = dividends
        result.interest = interest
        result.withholdings = []
        result.forex = []
        result.positions = []
        return result

    # ── Quick text for detection ─────────────────────────────────────────

    def _quick_text(self, pdf_bytes):
        try:
            import pdfplumber
            pdf = pdfplumber.open(io.BytesIO(pdf_bytes))
            text = (pdf.pages[0].extract_text() or '')
            if len(pdf.pages) > 1:
                text += '\n' + (pdf.pages[1].extract_text() or '')
            pdf.close()
            return text
        except Exception:
            return ''

    # ═════════════════════════════════════════════════════════════════════
    #  TAX REPORT PARSING  (Informe de Actividad)
    # ═════════════════════════════════════════════════════════════════════

    def _parse_tax_report(self, pdf_bytes):
        import pdfplumber
        pdf = pdfplumber.open(io.BytesIO(pdf_bytes))

        # Metadata from first 3 pages
        header = '\n'.join(
            (p.extract_text() or '') for p in pdf.pages[:3]
        )
        tax_year = self._tr_year(header)
        account_id = self._tr_account(header)

        trades = []
        current_isin = ''
        current_name = ''
        in_data = False

        for page in pdf.pages[3:]:  # Skip cover, header, index
            page_text = page.extract_text() or ''

            if 'Clave I' in page_text or 'Clave V' in page_text:
                in_data = True
            if in_data and ('Modelo 721' in page_text
                            or 'Descargo de responsabilidad' in page_text):
                break
            if not in_data or 'Clave C' in page_text:
                continue

            words = page.extract_words(x_tolerance=3, y_tolerance=3)
            for line in _group_lines(words):
                text = ' '.join(w['text'] for w in line)

                if any(m in text for m in _TR_SKIP):
                    continue

                # ISIN header: "AT0000831706 - Wienerberger"
                isin_m = _ISIN_RE.search(text)
                if isin_m and ' - ' in text:
                    current_isin = isin_m.group(1)
                    idx = text.find(' - ')
                    current_name = text[idx + 3:].strip()
                    continue

                if not current_isin:
                    continue

                t = self._tr_parse_row(line, current_isin, current_name)
                if t:
                    trades.append(t)

        pdf.close()
        trades.sort(key=lambda t: t['trade_date'])
        return trades, tax_year, account_id

    # ── Tax Report metadata ──────────────────────────────────────────────

    def _tr_year(self, text):
        m = re.search(r'Período:\s*\d{2}\.\d{2}\.(\d{4})\s*-\s*\d{2}\.\d{2}\.(\d{4})', text)
        if m:
            return int(m.group(2))
        m = re.search(r'DICIEMBRE DE (\d{4})', text)
        return int(m.group(1)) if m else 0

    def _tr_account(self, text):
        m = re.search(r'Clientela:\s*(\d+)', text)
        return m.group(1) if m else ''

    # ── Tax Report: parse one data row ───────────────────────────────────

    def _tr_parse_row(self, line_words, isin, name):
        """
        Extract trade from a Clave I/V data row.
        Returns a trade dict or None.
        """
        origin = None
        qty = None
        date_str = None
        sell_value = None
        asset_type = 'Stocks'

        for w in line_words:
            x, txt = w['x0'], w['text']

            if x < 170:
                low = txt.lower()
                if 'renta fija' in low or 'bond' in low:
                    asset_type = 'Bonds'
                elif any(k in low for k in ('inversión', 'instituciones', 'colectiva')):
                    asset_type = 'Funds'
            elif _TR_ORIGIN <= x < _TR_QTY:
                if txt in ('A', 'C'):
                    origin = txt
            elif _TR_QTY <= x < _TR_DATE1:
                v = _parse_eur(txt)
                if v > 0:
                    qty = v
            elif _TR_DATE1 <= x < _TR_DATE2:
                d = _parse_date_dotted(txt)
                if d:
                    date_str = d
            elif _TR_DATE2 <= x < _TR_FX:
                d = _parse_date_dotted(txt)
                if d:
                    date_str = d
            elif _TR_VEXT <= x < _TR_V31:
                v = _parse_eur(txt)
                if v > 0:
                    sell_value = v

        if not origin or not qty or not date_str:
            return None

        is_buy = (origin == 'A')
        signed_qty = abs(qty) if is_buy else -abs(qty)
        proceeds = sell_value if not is_buy and sell_value else 0.0
        price = round(abs(proceeds / qty), 6) if proceeds and qty else 0.0

        return {
            'asset_category': asset_type,
            'currency': 'EUR',
            'symbol': isin,
            'description': name or isin,
            'trade_date': date_str,
            'quantity': signed_qty,
            'trade_price': price,
            'proceeds': proceeds,
            'commission': 1.0,
            'basis': 0.0,          # filled later from Account Statement
            'realized_pl': 0.0,
            'code': '',
            'multiplier': 1,
            'underlying': isin,
            'expiry': None,
            'strike': None,
            'option_type': None,
        }

    # ═════════════════════════════════════════════════════════════════════
    #  ACCOUNT STATEMENT PARSING  (Resumen de Estado de Cuenta)
    # ═════════════════════════════════════════════════════════════════════

    def _parse_account_statement(self, pdf_bytes, tax_year):
        """
        Extract from the Account Statement:
          - dividends  (list of dicts)
          - interest   (list of dicts)
          - cost_map   { (ISIN, date): amount }  for buy-cost matching
        """
        import pdfplumber
        pdf = pdfplumber.open(io.BytesIO(pdf_bytes))

        first_text = pdf.pages[0].extract_text() or ''
        year = self._as_year(first_text) or tax_year

        dividends = []
        interest = []
        cost_map = defaultdict(float)

        for page in pdf.pages:
            for txn in self._as_page_txns(page, year):
                cat = txn['cat']
                if cat == 'dividend':
                    dividends.append(txn['data'])
                elif cat == 'interest':
                    interest.append(txn['data'])
                elif cat == 'buy_cost':
                    key = (txn['isin'], txn['date'])
                    cost_map[key] += txn['amount']

        pdf.close()
        return dividends, interest, dict(cost_map)

    # ── Account Statement metadata ───────────────────────────────────────

    def _as_year(self, text):
        m = re.search(r'(\d{1,2}\s+\w+\s+(\d{4}))\s*-\s*(\d{1,2}\s+\w+\s+(\d{4}))', text)
        if m:
            return int(m.group(4))
        m = re.search(r'\b(20\d{2})\b', text)
        return int(m.group(1)) if m else None

    # ── Account Statement: page-level extraction ─────────────────────────

    def _as_page_txns(self, page, year):
        """Yield classified transactions from one Account Statement page."""
        words = page.extract_words(keep_blank_chars=True, x_tolerance=2, y_tolerance=2)
        lines = _group_lines(words)
        i = 0
        while i < len(lines):
            text = ' '.join(w['text'] for w in lines[i])
            if any(m in text for m in _AS_SKIP):
                i += 1
                continue

            txn, consumed = self._as_parse_block(lines, i, year)
            if txn:
                yield txn
            i += max(consumed, 1)

    def _as_parse_block(self, lines, start, year):
        """Parse one transaction block (possibly multi-line) from Account Statement."""
        if start >= len(lines):
            return None, 1

        date_parts, content_parts, amt_in, amt_out = self._as_cols(lines[start])
        consumed = 1

        for off in range(1, 4):
            nxt = start + off
            if nxt >= len(lines):
                break
            nxt_text = ' '.join(w['text'] for w in lines[nxt])
            if re.match(r'^\d{1,2}\s+(ene|feb|mar|abr|may|jun|jul|ago|sept?|oct|nov|dic)\b',
                        nxt_text.strip().lower()):
                break
            consumed = off + 1
            d2, c2, ai2, ao2 = self._as_cols(lines[nxt])
            date_parts.extend(d2)
            content_parts.extend(c2)
            if ai2 and not amt_in:
                amt_in = ai2
            if ao2 and not amt_out:
                amt_out = ao2

        date_str = _parse_es_date(' '.join(date_parts), year)
        if not date_str:
            return None, consumed

        content = ' '.join(content_parts)
        tipo, desc = self._as_split_type(content)
        return self._as_classify(date_str, tipo, desc, amt_in, amt_out), consumed

    def _as_cols(self, line_words):
        """Split Account Statement line into date / content / entrada / salida."""
        date_p, content_p, ain, aout = [], [], 0.0, 0.0
        for w in line_words:
            x, txt = w['x0'], w['text']
            if x < _AS_CONTENT:
                date_p.append(txt)
            elif x < _AS_ENTRADA:
                content_p.append(txt)
            elif x < _AS_SALIDA:
                v = _parse_eur(txt)
                if v > 0 and ain == 0:
                    ain = v
            elif x < _AS_BALANCE:
                v = _parse_eur(txt)
                if v > 0 and aout == 0:
                    aout = v
        return date_p, content_p, ain, aout

    def _as_split_type(self, content):
        for prefix in _TYPE_PREFIXES:
            if content.startswith(prefix):
                return prefix, content[len(prefix):].strip()
        return '', content

    # ── Account Statement classification ─────────────────────────────────

    def _as_classify(self, date, tipo, desc, amt_in, amt_out):
        """Classify Account Statement row into dividend / interest / buy_cost / None."""
        desc_low = desc.lower()
        tipo_low = tipo.lower()
        amount = amt_in or amt_out

        # Skip non-financial
        if 'transacción' in tipo_low or 'con tarjeta' in tipo_low:
            return None
        if 'transferencia' in tipo_low or 'ingreso aceptado' in desc_low:
            return None
        if 'recompensa' in tipo_low or 'saveback' in desc_low:
            return None

        # ── Interest (non-bond) ──
        if ('pago de' in tipo_low and 'intereses' in tipo_low) or \
           ('interest payment' in desc_low and 'for isin' not in desc_low):
            return {
                'cat': 'interest',
                'data': {
                    'currency': 'EUR',
                    'pay_date': date,
                    'description': f'Trade Republic interest: {tipo} {desc}'.strip(),
                    'amount': amount,
                },
            }

        # ── Bond interest ──
        if 'interest payment for isin' in desc_low:
            if amt_out > 0 and amt_in == 0:
                return None
            isin = _ISIN_RE.search(desc)
            isin = isin.group(1) if isin else ''
            return {
                'cat': 'interest',
                'data': {
                    'currency': 'EUR',
                    'pay_date': date,
                    'description': f'Bond interest {isin}: {desc.strip()}',
                    'amount': amount,
                },
            }

        # ── Dividend ──
        if 'cash dividend for isin' in desc_low:
            isin_m = _ISIN_RE.search(desc)
            isin = isin_m.group(1) if isin_m else ''
            name = ''
            if isin:
                idx = desc.find(isin)
                if idx >= 0:
                    rest = desc[idx + len(isin):].strip()
                    name = re.sub(r',?\s*quantity:.*$', '', rest).strip()
                    name = re.sub(r'\s+\d{10,}.*$', '', name).strip()
            return {
                'cat': 'dividend',
                'data': {
                    'currency': 'EUR',
                    'pay_date': date,
                    'symbol': isin,
                    'description': name or f'Dividend {isin}',
                    'gross_amount': amount,
                    'is_in_lieu': 0,
                },
            }

        # ── Rendimiento / corporate event ──
        if ('rendimiento' in desc_low or 'rendimiento' in tipo_low) and \
           'cash dividend' not in desc_low and 'interest payment' not in desc_low:
            isin_m = _ISIN_RE.search(desc)
            if isin_m:
                isin = isin_m.group(1)
                name = ''
                idx = desc.find(isin)
                if idx >= 0:
                    rest = desc[idx + len(isin):].strip()
                    name = re.sub(r',?\s*quantity:.*$', '', rest).strip()
                return {
                    'cat': 'dividend',
                    'data': {
                        'currency': 'EUR',
                        'pay_date': date,
                        'symbol': isin,
                        'description': name or isin,
                        'gross_amount': amount,
                        'is_in_lieu': 0,
                    },
                }

        # ── Buy cost (for matching with Tax Report buys) ──
        isin_m = _ISIN_RE.search(desc)
        if not isin_m:
            return None
        isin = isin_m.group(1)

        is_buy = False
        if 'buy trade' in desc_low or 'compra' in desc_low or \
           'savings plan' in desc_low:
            is_buy = True
        elif 'sell trade' in desc_low or 'venta' in desc_low:
            return None  # sells already have proceeds from Tax Report
        elif 'comercio' in tipo_low:
            is_buy = 'sell' not in desc_low and 'venta' not in desc_low
        else:
            return None

        if is_buy and amt_out > 0:
            return {
                'cat': 'buy_cost',
                'isin': isin,
                'date': date,
                'amount': amt_out,
            }

        return None

    # ═════════════════════════════════════════════════════════════════════
    #  COST MATCHING — fill buy basis from Account Statement
    # ═════════════════════════════════════════════════════════════════════

    def _fill_buy_costs(self, trades, cost_map):
        """
        Match Tax Report buys with Account Statement costs.
        cost_map: { (ISIN, date): total_cost }
        """
        buy_groups = defaultdict(list)
        for t in trades:
            if t['quantity'] > 0:
                key = (t['symbol'], t['trade_date'])
                buy_groups[key].append(t)

        for key, group in buy_groups.items():
            cost = cost_map.get(key, 0.0)
            if cost > 0:
                total_qty = sum(t['quantity'] for t in group)
                for t in group:
                    share = t['quantity'] / total_qty if total_qty else 1.0
                    t['basis'] = round(cost * share, 2)
                    t['trade_price'] = round(
                        (t['basis'] - t['commission']) / t['quantity'], 6
                    ) if t['quantity'] else 0.0
            else:
                for t in group:
                    t['code'] = 'NO_COST'
