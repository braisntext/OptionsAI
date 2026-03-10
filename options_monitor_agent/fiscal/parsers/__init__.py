"""
Abstract base class for broker statement parsers.
All broker-specific parsers must implement this interface.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ParsedStatement:
    """Normalized output from any broker parser."""
    broker: str
    account_id: str
    tax_year: int
    base_currency: str
    holder_name: str = ''
    period_start: str = ''
    period_end: str = ''

    trades: list = field(default_factory=list)         # stocks + options
    dividends: list = field(default_factory=list)
    interest: list = field(default_factory=list)
    withholdings: list = field(default_factory=list)
    forex: list = field(default_factory=list)
    positions: list = field(default_factory=list)       # open positions


class BrokerParser(ABC):
    """
    Abstract parser interface. Each broker implements:
    - parse(file_content) -> ParsedStatement
    - detect(file_content) -> bool  (can this parser handle this file?)
    """

    @property
    @abstractmethod
    def broker_name(self) -> str:
        """Return broker identifier (e.g., 'IBKR', 'DEGIRO', 'TRADE_REPUBLIC')."""
        ...

    @abstractmethod
    def detect(self, content: str) -> bool:
        """Return True if this parser can handle the given file content."""
        ...

    @abstractmethod
    def parse(self, content: str, **kwargs) -> ParsedStatement:
        """Parse file content into a normalized ParsedStatement."""
        ...


# Registry of available parsers
_PARSERS: list[BrokerParser] = []


def register_parser(parser_class):
    """Decorator to register a parser class."""
    _PARSERS.append(parser_class())
    return parser_class


def detect_broker(content: str) -> Optional[BrokerParser]:
    """Auto-detect which parser can handle a file."""
    for parser in _PARSERS:
        if parser.detect(content):
            return parser
    return None


def get_parser(broker_name: str) -> Optional[BrokerParser]:
    """Get parser by broker name."""
    for parser in _PARSERS:
        if parser.broker_name == broker_name:
            return parser
    return None


def available_brokers() -> list[str]:
    """Return list of supported broker names."""
    return [p.broker_name for p in _PARSERS]


# Auto-import parser modules so @register_parser decorators fire
from . import ibkr_parser   # noqa: F401, E402
from . import tr_parser     # noqa: F401, E402
