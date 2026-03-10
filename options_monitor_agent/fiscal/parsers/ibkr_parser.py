"""
Interactive Brokers Activity Statement CSV parser.

IBKR CSV format: multi-section, each row starts with SectionName,Header|Data|SubTotal|Total,...
Sections: Statement, Account Information, Trades, Dividends, Withholding Tax,
          Interest, Open Positions, Forex Balances, Financial Instrument Information, etc.
"""

import csv
import io
import re
from datetime import datetime

from . import BrokerParser, ParsedStatement, register_parser


def _parse_date(date_str):
    """Parse IBKR date formats to ISO string."""
    date_str = date_str.strip().strip('"')
    for fmt in ('%Y-%m-%d, %H:%M:%S', '%Y-%m-%d', '%B %d, %Y'):
        try:
            return datetime.strptime(date_str, fmt).strftime('%Y-%m-%d')
        except ValueError:
            continue
    return date_str


def _parse_float(val):
    """Parse a float from IBKR CSV, handling commas in numbers and empty values."""
    if not val or val == '--':
        return 0.0
    val = val.strip().strip('"')
    # Handle negative numbers with comma in thousands: "-3,522.99"
    val = val.replace(',', '')
    try:
        return float(val)
    except ValueError:
        return 0.0


def _is_data_row(row):
    """Check if row is a Data row (not Header, SubTotal, Total, Notes)."""
    return len(row) > 1 and row[1] == 'Data'


def _is_order_row(row):
    """For trade sections, only parse Order rows (not SubTotal/Total)."""
    return len(row) > 0 and row[0] == 'Order'


@register_parser
class IBKRParser(BrokerParser):
    """Parser for Interactive Brokers Activity Statement CSV exports."""

    @property
    def broker_name(self):
        return 'IBKR'

    def detect(self, content):
        """Detect IBKR CSV by looking for characteristic headers."""
        if isinstance(content, (bytes, bytearray)):
            return False  # IBKR only handles text CSV
        first_lines = content[:500]
        return 'BrokerName' in first_lines and 'Activity Statement' in first_lines

    def parse(self, content):
        """Parse full IBKR Activity Statement CSV."""
        reader = csv.reader(io.StringIO(content))
        rows = list(reader)

        # Group rows by section
        sections = {}
        for row in rows:
            if not row:
                continue
            section = row[0].strip()
            if section not in sections:
                sections[section] = []
            sections[section].append(row)

        # Extract metadata
        account_id = self._extract_field(sections, 'Account Information', 'Account')
        base_currency = self._extract_field(sections, 'Account Information', 'Base Currency') or 'EUR'
        holder_name = self._extract_field(sections, 'Account Information', 'Name')
        period = self._extract_field(sections, 'Statement', 'Period') or ''
        tax_year = self._extract_year(period)

        result = ParsedStatement(
            broker='IBKR',
            account_id=account_id or '',
            tax_year=tax_year,
            base_currency=base_currency,
            holder_name=holder_name or '',
            period_start=self._parse_period_start(period),
            period_end=self._parse_period_end(period),
        )

        # Build instrument info lookup
        instruments = self._parse_instruments(sections)

        # Parse each section
        result.trades = self._parse_trades(sections, instruments)
        result.dividends = self._parse_dividends(sections)
        result.interest = self._parse_interest(sections)
        result.withholdings = self._parse_withholdings(sections)
        result.forex = self._parse_forex(sections)
        result.positions = self._parse_positions(sections)

        return result

    # ── Metadata helpers ─────────────────────────────────────────────────

    def _extract_field(self, sections, section_name, field_name):
        """Extract a single field value from a section."""
        for row in sections.get(section_name, []):
            if _is_data_row(row) and len(row) > 3 and row[2].strip() == field_name:
                return row[3].strip().strip('"')
        return None

    def _extract_year(self, period):
        """Extract tax year from period string like 'January 1, 2024 - December 31, 2024'."""
        match = re.search(r'(\d{4})\s*$', period)
        if match:
            return int(match.group(1))
        match = re.search(r'(\d{4})', period)
        return int(match.group(1)) if match else datetime.utcnow().year

    def _parse_period_start(self, period):
        parts = period.split(' - ')
        if parts:
            return _parse_date(parts[0])
        return ''

    def _parse_period_end(self, period):
        parts = period.split(' - ')
        if len(parts) > 1:
            return _parse_date(parts[1])
        return ''

    # ── Instrument info ──────────────────────────────────────────────────

    def _parse_instruments(self, sections):
        """Build lookup from symbol → instrument details."""
        instruments = {}
        for row in sections.get('Financial Instrument Information', []):
            if not _is_data_row(row) or len(row) < 6:
                continue
            category = row[2].strip()
            symbol = row[3].strip()

            if category == 'Stocks':
                # Fields: Category, Symbol, Description, Conid, SecurityID, ...
                instruments[symbol] = {
                    'description': row[4].strip() if len(row) > 4 else '',
                    'isin': row[5].strip() if len(row) > 5 else '',
                    'category': 'Stocks',
                    'multiplier': 1,
                }
            elif category == 'Equity and Index Options':
                # Fields: Category, Symbol, Description, Conid, Underlying, Exchange, Multiplier, Expiry, DeliveryMonth, Type, Strike
                desc = row[4].strip() if len(row) > 4 else ''
                instruments[desc] = {
                    'description': desc,
                    'category': 'Options',
                    'underlying': row[6].strip() if len(row) > 6 else '',
                    'exchange': row[7].strip() if len(row) > 7 else '',
                    'multiplier': _parse_float(row[8]) if len(row) > 8 else 100,
                    'expiry': row[9].strip() if len(row) > 9 else '',
                    'option_type': row[11].strip() if len(row) > 11 else '',
                    'strike': _parse_float(row[12]) if len(row) > 12 else 0,
                }
        return instruments

    # ── Trades ───────────────────────────────────────────────────────────

    def _parse_trades(self, sections, instruments):
        """Parse Trades section — stocks and options."""
        trades = []
        current_header = None
        current_category = None

        for row in sections.get('Trades', []):
            # Detect header rows to know column positions
            if len(row) > 1 and row[1] == 'Header':
                current_header = row
                # Detect category from header
                if 'Asset Category' in row:
                    current_category = None  # Will be set per data row
                continue

            if not _is_data_row(row):
                continue

            # Parse data row based on first field after Data (DataDiscriminator)
            discriminator = row[2].strip() if len(row) > 2 else ''

            # Only parse Order rows in trade detail sections
            if discriminator != 'Order':
                continue

            asset_category = row[3].strip() if len(row) > 3 else ''

            if asset_category == 'Stocks':
                trade = self._parse_stock_trade(row, instruments)
                if trade:
                    trades.append(trade)
            elif asset_category == 'Equity and Index Options':
                trade = self._parse_option_trade(row, instruments)
                if trade:
                    trades.append(trade)

        return trades

    def _parse_stock_trade(self, row, instruments):
        """Parse a stock trade row."""
        # Trades,Data,Order,Stocks,USD,ADM,"2024-12-19, 16:20:00",100,52.5,50.49,-5250,0,5250,0,-201,A;O
        if len(row) < 15:
            return None
        currency = row[4].strip()
        symbol = row[5].strip()
        date = _parse_date(row[6])
        quantity = _parse_float(row[7])
        price = _parse_float(row[8])
        # row[9] = close price
        proceeds = _parse_float(row[10])
        commission = _parse_float(row[11])
        basis = _parse_float(row[12])
        realized_pl = _parse_float(row[13])
        code = row[15].strip() if len(row) > 15 else ''

        info = instruments.get(symbol, {})

        return {
            'asset_category': 'Stocks',
            'currency': currency,
            'symbol': symbol,
            'description': info.get('description', symbol),
            'trade_date': date,
            'quantity': quantity,
            'trade_price': price,
            'proceeds': proceeds,
            'commission': commission,
            'basis': basis,
            'realized_pl': realized_pl,
            'code': code,
            'multiplier': 1,
            'underlying': symbol,
            'expiry': None,
            'strike': None,
            'option_type': None,
        }

    def _parse_option_trade(self, row, instruments):
        """Parse an option trade row."""
        # Trades,Data,Order,Equity and Index Options,GBP,BT.A 20DEC24 1.3 P,"2024-11-07, 05:50:46",-1,0.035,0.0275,35,-1.7,-33.3,0,7.5,O
        if len(row) < 15:
            return None
        currency = row[4].strip()
        symbol = row[5].strip()
        date = _parse_date(row[6])
        quantity = _parse_float(row[7])
        price = _parse_float(row[8])
        proceeds = _parse_float(row[10])
        commission = _parse_float(row[11])
        basis = _parse_float(row[12])
        realized_pl = _parse_float(row[13])
        code = row[15].strip() if len(row) > 15 else ''

        # Extract option details from symbol or instrument info
        info = instruments.get(symbol, {})
        underlying, expiry, strike, opt_type = self._parse_option_symbol(symbol)
        multiplier = info.get('multiplier', 100)

        return {
            'asset_category': 'Options',
            'currency': currency,
            'symbol': symbol,
            'description': info.get('description', symbol),
            'trade_date': date,
            'quantity': quantity,
            'trade_price': price,
            'proceeds': proceeds,
            'commission': commission,
            'basis': basis,
            'realized_pl': realized_pl,
            'code': code,
            'multiplier': multiplier,
            'underlying': underlying or info.get('underlying', ''),
            'expiry': expiry or info.get('expiry', ''),
            'strike': strike or info.get('strike'),
            'option_type': opt_type or info.get('option_type', ''),
        }

    def _parse_option_symbol(self, symbol):
        """Parse option symbol like 'ADM 08NOV24 50 P' or 'BT.A 20DEC24 1.3 P'."""
        # Pattern: UNDERLYING DDMMMYY STRIKE C|P
        match = re.match(
            r'^(.+?)\s+(\d{2}[A-Z]{3}\d{2})\s+([\d.]+)\s+([CP])$',
            symbol.strip()
        )
        if match:
            underlying = match.group(1).strip()
            date_str = match.group(2)
            strike = float(match.group(3))
            opt_type = match.group(4)
            # Parse date like 08NOV24
            try:
                expiry = datetime.strptime(date_str, '%d%b%y').strftime('%Y-%m-%d')
            except ValueError:
                expiry = date_str
            return underlying, expiry, strike, opt_type
        return None, None, None, None

    # ── Dividends ────────────────────────────────────────────────────────

    def _parse_dividends(self, sections):
        """Parse Dividends section."""
        dividends = []
        for row in sections.get('Dividends', []):
            if not _is_data_row(row) or len(row) < 5:
                continue
            currency = row[2].strip()
            if currency in ('Total', 'Total in EUR'):
                continue
            date = _parse_date(row[3])
            description = row[4].strip() if len(row) > 4 else ''
            amount = _parse_float(row[5]) if len(row) > 5 else 0

            # Extract symbol from description: "IBKR(US45841N1072) Payment..."
            symbol = self._extract_symbol_from_div(description)
            is_in_lieu = 1 if 'Payment in Lieu' in description else 0

            dividends.append({
                'currency': currency,
                'pay_date': date,
                'symbol': symbol,
                'description': description,
                'gross_amount': amount,
                'is_in_lieu': is_in_lieu,
            })
        return dividends

    def _extract_symbol_from_div(self, description):
        """Extract ticker from dividend description like 'T(US00206R1023) Cash Dividend...'."""
        match = re.match(r'^(\w+(?:\.\w+)?)\s*\(', description)
        return match.group(1) if match else ''

    # ── Interest ─────────────────────────────────────────────────────────

    def _parse_interest(self, sections):
        """Parse Interest section."""
        interest = []
        for row in sections.get('Interest', []):
            if not _is_data_row(row) or len(row) < 5:
                continue
            currency = row[2].strip()
            if currency in ('Total', 'Total in EUR'):
                continue
            date = _parse_date(row[3])
            description = row[4].strip() if len(row) > 4 else ''
            amount = _parse_float(row[5]) if len(row) > 5 else 0

            interest.append({
                'currency': currency,
                'pay_date': date,
                'description': description,
                'amount': amount,
            })
        return interest

    # ── Withholding Tax ──────────────────────────────────────────────────

    def _parse_withholdings(self, sections):
        """Parse Withholding Tax section."""
        withholdings = []
        for row in sections.get('Withholding Tax', []):
            if not _is_data_row(row) or len(row) < 5:
                continue
            currency = row[2].strip()
            if currency in ('Total', 'Total in EUR', 'Total Withholding Tax in EUR'):
                continue
            date = _parse_date(row[3])
            description = row[4].strip() if len(row) > 4 else ''
            amount = _parse_float(row[5]) if len(row) > 5 else 0

            # Determine type and country
            symbol = self._extract_symbol_from_div(description)
            tax_type, country = self._classify_withholding(description, currency)

            withholdings.append({
                'currency': currency,
                'pay_date': date,
                'symbol': symbol,
                'description': description,
                'amount': amount,  # negative value (tax withheld)
                'tax_type': tax_type,
                'country': country,
            })
        return withholdings

    def _classify_withholding(self, description, currency):
        """Classify withholding tax by type and country."""
        desc_lower = description.lower()
        if 'us tax' in desc_lower:
            return 'dividend', 'US'
        if 'credit interest' in desc_lower or 'withholding' in desc_lower:
            if currency == 'EUR':
                return 'interest', 'ES'
            return 'interest', 'US'
        if 'dividend' in desc_lower:
            return 'dividend', 'US'
        return 'other', ''

    # ── Forex ────────────────────────────────────────────────────────────

    def _parse_forex(self, sections):
        """Parse Forex trades from the Trades section."""
        forex = []
        in_forex = False

        for row in sections.get('Trades', []):
            if len(row) > 1 and row[1] == 'Header':
                # Check if this header block is for Forex
                header_text = ','.join(row)
                in_forex = 'Comm in EUR' in header_text
                continue

            if not in_forex or not _is_data_row(row):
                continue

            discriminator = row[2].strip() if len(row) > 2 else ''
            if discriminator != 'Order':
                continue

            # Trades,Data,Order,Forex,GBP,EUR.GBP,"2024-11-07, 05:50:46",-2.05,0.83295,,1.7075475,0,,,0.002814,AFx
            if len(row) < 15:
                continue

            currency = row[4].strip()
            symbol = row[5].strip()
            date = _parse_date(row[6])
            quantity = _parse_float(row[7])
            price = _parse_float(row[8])
            proceeds = _parse_float(row[10])
            commission_eur = _parse_float(row[11])
            mtm_eur = _parse_float(row[14]) if len(row) > 14 else 0
            code = row[15].strip() if len(row) > 15 else ''

            is_auto_fx = 1 if 'AFx' in code else 0

            forex.append({
                'currency': currency,
                'symbol': symbol,
                'trade_date': date,
                'quantity': quantity,
                'trade_price': price,
                'proceeds': proceeds,
                'proceeds_eur': None,  # will compute if needed
                'commission_eur': commission_eur,
                'mtm_eur': mtm_eur,
                'code': code,
                'is_auto_fx': is_auto_fx,
            })

        return forex

    # ── Open Positions ───────────────────────────────────────────────────

    def _parse_positions(self, sections):
        """Parse Open Positions section."""
        positions = []
        for row in sections.get('Open Positions', []):
            if not _is_data_row(row) or len(row) < 14:
                continue
            discriminator = row[2].strip()
            if discriminator != 'Summary':
                continue

            category = row[3].strip()
            currency = row[4].strip()
            symbol = row[5].strip()
            quantity = _parse_float(row[7])
            # row[8] = multiplier
            cost_price = _parse_float(row[9])
            cost_basis = _parse_float(row[10])
            close_price = _parse_float(row[11])
            value = _parse_float(row[12])
            unrealized_pl = _parse_float(row[13])

            asset_cat = 'Stocks' if category == 'Stocks' else 'Options'

            positions.append({
                'asset_category': asset_cat,
                'currency': currency,
                'symbol': symbol,
                'quantity': quantity,
                'cost_price': cost_price,
                'cost_basis': cost_basis,
                'close_price': close_price,
                'market_value': value,
                'unrealized_pl': unrealized_pl,
            })
        return positions
