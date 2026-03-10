"""
Trade Republic Account Statement PDF parser.

Trade Republic PDFs have a transaction log format with columns:
  FECHA | TIPO | DESCRIPCIÓN | ENTRADA DE DINERO | SALIDA DE DINERO | BALANCE

Two description formats exist:
  Format A (older):  "Ejecución Negociación Compra/Venta directa ..." — no quantity
  Format B (newer):  "Buy/Sell trade ISIN NAME, quantity: N" — has quantity

All amounts are in EUR.
"""

import io
import re
from collections import defaultdict
from datetime import datetime

from . import BrokerParser, ParsedStatement, register_parser

# ── Column position thresholds (from word x-coordinates in the PDF) ──────────
_COL_CONTENT = 80    # Type+Description starts (TYPE is prefix of this)
_COL_ENTRADA = 420   # Money-in column starts
_COL_SALIDA = 462    # Money-out column starts
_COL_BALANCE = 500   # Balance column starts

# Known TYPE prefixes (stripped from combined type+description text)
_TYPE_PREFIXES = [
    'Pago de intereses',
    'Transacción con tarjeta',
    'Transferencia',
    'Recompensa',
    'Rendimientos',
    'Comercio',
]

# ISIN pattern: 2 letters + 9 alphanumeric + 1 check digit
_ISIN_RE = re.compile(r'\b([A-Z]{2}[A-Z0-9]{9}\d)\b')

# Spanish month abbreviations → month number
_MONTHS_ES = {
    'ene': 1, 'feb': 2, 'mar': 3, 'abr': 4, 'may': 5, 'jun': 6,
    'jul': 7, 'ago': 8, 'sept': 9, 'sep': 9, 'oct': 10, 'nov': 11, 'dic': 12,
}


def _parse_es_date(date_str, year):
    """Parse '11 ene' + year → '2024-01-11'."""
    date_str = date_str.strip()
    parts = date_str.split()
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


def _parse_eur(text):
    """Parse '19.938,04 €' → 19938.04.  Handles concatenated amounts like '10.001,00\xa0€17.803,99\xa0€'."""
    text = text.replace('\xa0', ' ').replace('€', '').strip()
    if not text:
        return 0.0
    # Extract only the first number (amounts may be concatenated)
    m = re.match(r'[\d.,]+', text)
    if not m:
        return 0.0
    s = m.group()
    # European format: 19.938,04 → remove dots, replace comma with dot
    s = s.replace('.', '').replace(',', '.')
    try:
        return float(s)
    except ValueError:
        return 0.0


def _extract_isin(text):
    """Extract first ISIN from text."""
    m = _ISIN_RE.search(text)
    return m.group(1) if m else ''


def _extract_quantity(text):
    """Extract 'quantity: N' from description. Returns float or None.
    Note: Trade Republic uses English decimal format for quantities (e.g., 1.037376).
    """
    m = re.search(r'quantity:\s*([\d.]+)', text)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass
    return None


def _extract_name_after_isin(text, isin):
    """Extract security name after ISIN in description."""
    if not isin:
        return ''
    idx = text.find(isin)
    if idx < 0:
        return ''
    rest = text[idx + len(isin):].strip()
    # Remove trailing quantity info
    rest = re.sub(r',?\s*quantity:.*$', '', rest).strip()
    # Remove trailing trade ref numbers
    rest = re.sub(r'\s+\d{10,}.*$', '', rest).strip()
    return rest


@register_parser
class TradeRepublicParser(BrokerParser):
    """Parser for Trade Republic Account Statement PDFs."""

    @property
    def broker_name(self):
        return 'TRADE_REPUBLIC'

    def detect(self, content):
        """Detect Trade Republic PDF by looking for characteristic markers."""
        if isinstance(content, (bytes, bytearray)):
            text = self._quick_text(content)
        else:
            text = content
        return 'Trade Republic' in text and ('RESUMEN DE ESTADO DE CUENTA' in text
                                              or 'Account statement' in text.lower()
                                              or 'TRANSACCIONES DE CUENTA' in text)

    def parse(self, content):
        """Parse Trade Republic PDF into normalized ParsedStatement."""
        if not isinstance(content, (bytes, bytearray)):
            raise ValueError('Trade Republic parser requires PDF bytes')

        import pdfplumber
        pdf = pdfplumber.open(io.BytesIO(content))

        # Extract metadata from page 1 text
        first_text = pdf.pages[0].extract_text() or ''
        tax_year = self._extract_year(first_text)
        account_id = self._extract_iban(first_text)
        holder_name = self._extract_holder(first_text)

        # Extract all transactions from all pages
        raw_txns = []
        for page in pdf.pages:
            raw_txns.extend(self._extract_page_transactions(page, tax_year))

        pdf.close()

        # Classify and build normalized data
        trades = []
        dividends = []
        interest = []

        for txn in raw_txns:
            cat = txn.get('category')
            if cat == 'trade':
                trades.append(txn['data'])
            elif cat == 'dividend':
                dividends.append(txn['data'])
            elif cat == 'interest':
                interest.append(txn['data'])

        # Group Format-A trades (no quantity) by ISIN+date+side to merge fills
        trades = self._merge_format_a_trades(trades)

        result = ParsedStatement(
            broker='TRADE_REPUBLIC',
            account_id=account_id,
            tax_year=tax_year,
            base_currency='EUR',
            holder_name=holder_name,
        )
        result.trades = trades
        result.dividends = dividends
        result.interest = interest
        # Trade Republic doesn't report withholdings or forex separately
        result.withholdings = []
        result.forex = []
        result.positions = []

        return result

    # ── Metadata extraction ──────────────────────────────────────────────

    def _extract_year(self, text):
        """Extract tax year from '01 ene 2024 - 31 dic 2024'."""
        m = re.search(r'(\d{1,2}\s+\w+\s+(\d{4}))\s*-\s*(\d{1,2}\s+\w+\s+(\d{4}))', text)
        if m:
            return int(m.group(4))
        # Fallback: look for 4-digit year
        m = re.search(r'\b(20\d{2})\b', text)
        return int(m.group(1)) if m else 0

    def _extract_iban(self, text):
        """Extract IBAN from header."""
        m = re.search(r'IBAN\s+([A-Z]{2}\d{2}[A-Z0-9]{4,30})', text)
        return m.group(1) if m else ''

    def _extract_holder(self, text):
        """Extract holder name (first line of PDF)."""
        lines = text.split('\n')
        if lines:
            first = lines[0].strip()
            # Name is before 'FECHA'
            idx = first.find('FECHA')
            if idx > 0:
                return first[:idx].strip()
            return first[:60]
        return ''

    def _quick_text(self, pdf_bytes):
        """Extract text from first page only for detection."""
        try:
            import pdfplumber
            pdf = pdfplumber.open(io.BytesIO(pdf_bytes))
            text = pdf.pages[0].extract_text() or ''
            pdf.close()
            return text
        except Exception:
            return ''

    # ── Page-level transaction extraction ────────────────────────────────

    def _extract_page_transactions(self, page, year):
        """Extract all transactions from one PDF page using word positions."""
        words = page.extract_words(keep_blank_chars=True, x_tolerance=2, y_tolerance=2)
        if not words:
            return []

        # Sort all words by y then x
        words_sorted = sorted(words, key=lambda w: (w['top'], w['x0']))

        # Group words into lines using gap-based clustering (5px gap)
        lines = []
        current_line = []
        current_y = None
        for w in words_sorted:
            if current_y is None or abs(w['top'] - current_y) <= 5:
                current_line.append((w['x0'], w['text']))
                if current_y is None:
                    current_y = w['top']
                else:
                    # Update y to running average for better grouping
                    current_y = (current_y + w['top']) / 2
            else:
                if current_line:
                    lines.append(sorted(current_line, key=lambda w: w[0]))
                current_line = [(w['x0'], w['text'])]
                current_y = w['top']
        if current_line:
            lines.append(sorted(current_line, key=lambda w: w[0]))

        # Parse transactions from lines
        transactions = []
        i = 0
        while i < len(lines):
            words_in_line = lines[i]
            full_text = ' '.join(t for _, t in words_in_line)

            if self._is_header_or_footer(full_text):
                i += 1
                continue

            # Try to parse a transaction starting at this line
            txn, lines_consumed = self._parse_transaction_block(lines, i, year)
            if txn:
                transactions.append(txn)
            i += max(lines_consumed, 1)

        return transactions

    def _is_header_or_footer(self, text):
        """Detect header/footer lines to skip."""
        skip_markers = [
            'FECHA', 'TIPO', 'DESCRIPCIÓN', 'ENTRADA', 'SALIDA', 'BALANCE',
            'Página', 'Creado en', 'Trade Republic Bank',
            'RESUMEN DE ESTADO', 'PRODUCTO', 'Cuenta de valores',
            'TRANSACCIONES DE CUENTA', 'DISCLAIMER', 'Estimado Cliente',
            'Brunnenstraße', 'AG Charlottenburg', 'ID-IVA',
        ]
        for marker in skip_markers:
            if marker in text:
                return True
        return False

    def _parse_transaction_block(self, lines, start_idx, year):
        """
        Parse a transaction block starting at start_idx.
        Returns (transaction_dict, lines_consumed).
        """
        if start_idx >= len(lines):
            return None, 1

        words1 = lines[start_idx]
        lines_consumed = 1

        # Extract columns: DATE (x<80), CONTENT (80-420), amounts (420+)
        date_parts, content_parts, amount_in, amount_out = self._split_columns(words1)

        # Check next lines for continuation (not starting with a date pattern)
        for offset in range(1, 4):
            next_idx = start_idx + offset
            if next_idx >= len(lines):
                break
            next_words = lines[next_idx]
            next_text = ' '.join(t for _, t in next_words)

            # Is this a new transaction? (starts with "DD mmm" date pattern)
            if re.match(r'^\d{1,2}\s+(ene|feb|mar|abr|may|jun|jul|ago|sept?|oct|nov|dic)\b',
                        next_text.strip().lower()):
                break

            # Continuation line
            lines_consumed = offset + 1
            d2, c2, ai2, ao2 = self._split_columns(next_words)
            date_parts.extend(d2)
            content_parts.extend(c2)
            if ai2 and not amount_in:
                amount_in = ai2
            if ao2 and not amount_out:
                amount_out = ao2

        # Parse date
        date_str = ' '.join(date_parts).strip()
        trade_date = _parse_es_date(date_str, year)
        if not trade_date:
            return None, lines_consumed

        # Split content into TYPE and DESCRIPTION
        content = ' '.join(content_parts).strip()
        tipo, desc = self._split_type_desc(content)

        return self._classify_transaction(
            trade_date, tipo, desc, amount_in, amount_out
        ), lines_consumed

    def _split_columns(self, words_in_line):
        """Split words into date, content, amount_in (ENTRADA) and amount_out (SALIDA).
        Distinguishing columns matters for interest/dividends (detect reversals).
        """
        date_parts = []
        content_parts = []
        amount_in = 0.0   # ENTRADA column (money received)
        amount_out = 0.0  # SALIDA column (money paid)

        for x, text in words_in_line:
            if x < _COL_CONTENT:
                date_parts.append(text)
            elif x < _COL_ENTRADA:
                content_parts.append(text)
            elif x < _COL_SALIDA:
                # ENTRADA column — money in
                parsed = _parse_eur(text)
                if parsed > 0 and amount_in == 0:
                    amount_in = parsed
            elif x < _COL_BALANCE:
                # SALIDA column — money out
                parsed = _parse_eur(text)
                if parsed > 0 and amount_out == 0:
                    amount_out = parsed
            # else: balance column — skip

        return date_parts, content_parts, amount_in, amount_out

    def _split_type_desc(self, content):
        """Split combined 'Comercio Buy trade ES01...' into type and description."""
        for prefix in _TYPE_PREFIXES:
            if content.startswith(prefix):
                rest = content[len(prefix):].strip()
                return prefix, rest
        return '', content

    # ── Transaction classification ───────────────────────────────────────

    def _classify_transaction(self, date, tipo, desc, amount_in, amount_out):
        """Classify a transaction into trade/dividend/interest/skip.
        amount_in = ENTRADA (money received), amount_out = SALIDA (money paid).
        """
        tx_amount = amount_in or amount_out  # whichever is non-zero
        desc_lower = desc.lower()
        tipo_lower = tipo.lower()

        # ── Skip non-financial transactions ──
        if 'transacción' in tipo_lower or 'con tarjeta' in tipo_lower:
            return None  # Card payment
        if 'transferencia' in tipo_lower or 'ingreso aceptado' in desc_lower:
            return None  # Bank transfer
        if 'recompensa' in tipo_lower or 'saveback' in desc_lower:
            return None  # Saveback reward

        # ── Interest payment ──
        if ('pago de' in tipo_lower and 'intereses' in tipo_lower) or \
           ('interest payment' in desc_lower and 'for isin' not in desc_lower):
            return {
                'category': 'interest',
                'data': {
                    'currency': 'EUR',
                    'pay_date': date,
                    'description': f'Trade Republic interest: {tipo} {desc}'.strip(),
                    'amount': tx_amount,
                },
            }

        # ── Bond / instrument interest (Interest Payment for ISIN) ──
        if 'interest payment for isin' in desc_lower:
            isin = _extract_isin(desc)
            # SALIDA entries are reversals/debits — skip them
            if amount_out > 0 and amount_in == 0:
                return None
            return {
                'category': 'interest',
                'data': {
                    'currency': 'EUR',
                    'pay_date': date,
                    'description': f'Bond interest {isin}: {desc.strip()}',
                    'amount': tx_amount,
                },
            }

        # ── Dividend ──
        if 'cash dividend for isin' in desc_lower:
            isin = _extract_isin(desc)
            name = _extract_name_after_isin(desc, isin)
            return {
                'category': 'dividend',
                'data': {
                    'currency': 'EUR',
                    'pay_date': date,
                    'symbol': isin,
                    'description': name or f'Dividend {isin}',
                    'gross_amount': tx_amount,
                    'is_in_lieu': 0,
                },
            }

        # Corporate event / Rendimiento with ISIN (dividend or distribution)
        if ('rendimiento' in desc_lower or 'rendimiento' in tipo_lower) and \
           'cash dividend' not in desc_lower and 'interest payment' not in desc_lower:
            isin = _extract_isin(desc)
            if isin:
                name = _extract_name_after_isin(desc, isin)
                return {
                    'category': 'dividend',
                    'data': {
                        'currency': 'EUR',
                        'pay_date': date,
                        'symbol': isin,
                        'description': name or isin,
                        'gross_amount': tx_amount,
                        'is_in_lieu': 0,
                    },
                }

        # ── Trade: Format B — "Buy/Sell trade ISIN NAME, quantity: N" ──
        buy_b = re.search(r'Buy trade\s+(\S+)\s+(.+?)(?:,\s*quantity:\s*([\d.]+))?$', desc)
        sell_b = re.search(r'Sell trade\s+(\S+)\s+(.+?)(?:,\s*quantity:\s*([\d.]+))?$', desc)

        if buy_b or sell_b:
            match = buy_b or sell_b
            is_buy = buy_b is not None
            isin = match.group(1)
            name_raw = match.group(2).strip()
            qty_str = match.group(3)

            quantity = float(qty_str) if qty_str else None

            # Savings plan entries have "Savings plan execution" in desc
            is_savings_plan = 'savings plan' in desc_lower

            return self._build_trade(
                isin, name_raw, date, is_buy, tx_amount, quantity, is_savings_plan
            )

        # ── Trade: Format A — "Compra directa Compra ISIN ..." ──
        if 'compra directa' in desc_lower or 'compra' in desc_lower:
            isin = _extract_isin(desc)
            if isin:
                name = _extract_name_after_isin(desc, isin)
                return self._build_trade(
                    isin, name, date, True, tx_amount, None, False
                )

        if 'venta directa' in desc_lower or ('venta' in desc_lower and 'comercio' in tipo_lower):
            isin = _extract_isin(desc)
            if isin:
                name = _extract_name_after_isin(desc, isin)
                return self._build_trade(
                    isin, name, date, False, tx_amount, None, False
                )

        # ── Savings plan (alternative format) ──
        if 'savings plan execution' in desc_lower or 'savings plan' in desc_lower:
            isin = _extract_isin(desc)
            qty = _extract_quantity(desc)
            if isin:
                name = _extract_name_after_isin(desc, isin)
                return self._build_trade(
                    isin, name, date, True, tx_amount, qty, True
                )

        # ── Generic "Comercio" with ISIN — catch remaining trades ──
        if 'comercio' in tipo_lower:
            isin = _extract_isin(desc)
            if isin:
                name = _extract_name_after_isin(desc, isin)
                # Determine direction from keywords
                is_buy = 'sell' not in desc_lower and 'venta' not in desc_lower
                qty = _extract_quantity(desc)
                return self._build_trade(
                    isin, name, date, is_buy, tx_amount, qty, False
                )

        return None  # Unrecognized

    # ── Trade builder ────────────────────────────────────────────────────

    def _build_trade(self, isin, name, date, is_buy, total_amount, quantity, is_savings_plan):
        """Build a normalized trade dict."""
        commission = 0.0 if is_savings_plan else 1.0

        if quantity and quantity > 0:
            trade_price = round((total_amount - commission) / quantity, 6) if is_buy else \
                          round((total_amount + commission) / quantity, 6)
        else:
            # No quantity available — will be merged/approximated later
            trade_price = total_amount
            quantity = None  # flag for merge step

        # Tax engine convention: positive qty = buy, negative qty = sell
        if quantity is not None:
            signed_qty = abs(quantity) if is_buy else -abs(quantity)
        else:
            signed_qty = None  # flag for merge step

        trade = {
            'asset_category': 'Stocks',
            'currency': 'EUR',
            'symbol': isin,
            'description': name or isin,
            'trade_date': date,
            'quantity': signed_qty,
            'trade_price': abs(trade_price),
            'proceeds': total_amount if not is_buy else 0.0,
            'commission': commission,
            'basis': total_amount if is_buy else 0.0,
            'realized_pl': 0.0,  # FIFO engine calculates this
            'code': '',
            'multiplier': 1,
            'underlying': isin,
            'expiry': None,
            'strike': None,
            'option_type': None,
            '_is_buy': is_buy,
            '_has_quantity': quantity is not None,
        }
        return {'category': 'trade', 'data': trade}

    # ── Merge Format-A trades ────────────────────────────────────────────

    def _merge_format_a_trades(self, trades):
        """
        Group Format-A trades (no quantity) by ISIN + date + side:
        multiple fills of the same order become one aggregated trade.
        Trades WITH quantity (Format B) pass through unchanged.
        """
        result = []
        # Key: (isin, date, is_buy) → list of trades to merge
        merge_groups = defaultdict(list)

        for t in trades:
            if t.get('_has_quantity'):
                # Format B — remove internal flags and keep as-is
                t.pop('_is_buy', None)
                t.pop('_has_quantity', None)
                result.append(t)
            else:
                key = (t['symbol'], t['trade_date'], t.get('_is_buy', True))
                merge_groups[key].append(t)

        # Merge each group
        for (isin, date, is_buy), group in merge_groups.items():
            if is_buy:
                total = sum(t['basis'] for t in group)
            else:
                total = sum(t['proceeds'] for t in group)
            total_commission = sum(t['commission'] for t in group)

            merged = group[0].copy()
            merged['quantity'] = 1.0 if is_buy else -1.0  # signed qty
            merged['trade_price'] = total
            if is_buy:
                merged['basis'] = total
                merged['proceeds'] = 0.0
            else:
                merged['proceeds'] = total
                merged['basis'] = 0.0
            merged['commission'] = total_commission
            merged.pop('_is_buy', None)
            merged.pop('_has_quantity', None)
            result.append(merged)

        # Sort by date
        result.sort(key=lambda t: t['trade_date'])
        return result
