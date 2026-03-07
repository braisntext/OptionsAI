"""
Configuración central del agente de monitoreo de opciones.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ============================================================
# API KEYS
# ============================================================
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS", "")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "")
EMAIL_SMTP_SERVER = os.getenv("EMAIL_SMTP_SERVER", "smtp.gmail.com")
EMAIL_SMTP_PORT = int(os.getenv("EMAIL_SMTP_PORT", "587"))
EMAIL_RECIPIENTS = os.getenv("EMAIL_RECIPIENTS", "").split(",")

# ============================================================
# WATCHLIST
# ============================================================
WATCHLIST = [
    "ACX.MC",   # Acerinox
    "ENG.MC",   # Enagas
    "KVUE",  # Kenvue
    "NTGY.MC",  # Naturgy
    "O",     # Realty Income
    "VIS.MC",   # Viscofan
]

# ============================================================
# AGENT CONFIG
# ============================================================
AGENT_CONFIG = {
    "model": "claude-haiku-3-5-20241022",
    "max_tokens": 4096,
    "temperature": 0.3,
    "monitor_interval_minutes": 15,
    "alert_threshold_percent": 5.0,
    "expiration_range_weeks": 6,
}

# ============================================================
# GREEKS CONFIG
# ============================================================
GREEKS_CONFIG = {
    "risk_free_rate": 0.053,
    "dividend_yield": 0.013,
    "trading_days_per_year": 252,
}

# ============================================================
# NOTIFICATION CONFIG
# ============================================================
NOTIFICATION_CONFIG = {
    "enable_email": bool(EMAIL_ADDRESS and EMAIL_PASSWORD),
    "enable_telegram": bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID),
    "notify_on_high_iv": True,
    "notify_on_unusual_volume": True,
    "notify_on_pcr_extreme": True,
    "notify_on_significant_change": True,
    "unusual_volume_threshold": 3.0,
}

# ============================================================
# DATABASE CONFIG
# ============================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_raw_db_url = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR}/memory/options_monitor.db")
# Render provides postgres:// but SQLAlchemy 2.x requires postgresql://
if _raw_db_url.startswith("postgres://"):
    _raw_db_url = _raw_db_url.replace("postgres://", "postgresql://", 1)
DATABASE_URL = _raw_db_url

# ============================================================
# DASHBOARD CONFIG
# ============================================================
DASHBOARD_CONFIG = {
    "host": "0.0.0.0",
    "port": int(os.getenv("PORT", 5001)),
    "debug": False,
}

# ============================================================
# BACKTESTING CONFIG
# ============================================================
BACKTEST_CONFIG = {
    "lookback_days": 30,
    "signal_types": ["HIGH_IV", "HIGH_PUT_CALL_RATIO", "LOW_PUT_CALL_RATIO", "UNUSUAL_VOLUME"],
    "results_dir": "backtest_results",
}

# ============================================================
# BREVO (Transactional Email API)
# ============================================================
BREVO_API_KEY = os.getenv("BREVO_API_KEY", "")
BREVO_SENDER_EMAIL = os.getenv("BREVO_SENDER_EMAIL", "")
BREVO_SENDER_NAME = os.getenv("BREVO_SENDER_NAME", "Options Monitor")

# ============================================================
# SUPERADMIN EMAILS
# ============================================================
SUPERADMIN_EMAILS = [
    e.strip().lower()
    for e in os.getenv(
        "SUPERADMIN_EMAILS",
        "braisnatural@gmail.com,braisontour@gmail.com"
    ).split(",")
    if e.strip()
]

# ============================================================
# PATHS
# ============================================================
REPORTS_DIR = "reports"
MEMORY_FILE = "memory/history.json"


# ==============================================================
# PREMIUM SPIKE ALERT CONFIG
# ==============================================================
# Threshold: fire alert when premium moves > this % in one cycle
PREMIUM_SPIKE_THRESHOLD = 0.25  # 25%

# Also alert on IV spikes above this % change
IV_SPIKE_THRESHOLD = 0.30  # 30%

# Max expiry days to watch (ignore very far-dated options)
SPIKE_MAX_EXPIRY_DAYS = 60

# ==============================================================
# NOTIFICATION CONFIG (ntfy.sh + Email)
# ==============================================================
# --- ntfy.sh (free iPhone push notifications) ---
# 1. Install 'ntfy' app on your iPhone (free on App Store)
# 2. Choose a unique topic name below (keep it secret!)
# 3. In the ntfy app: tap '+' and subscribe to this topic
NTFY_TOPIC = "braisn-options-alerts-7k2m"  # Subscribe to this in ntfy app

# --- Legacy email notification vars (used by ntfy_notifier) ---
NOTIFY_EMAIL_TO = os.getenv("NOTIFY_EMAIL_TO", "")
NOTIFY_EMAIL_FROM = os.getenv("NOTIFY_EMAIL_FROM", "")
NOTIFY_EMAIL_PASSWORD = os.getenv("NOTIFY_EMAIL_PASSWORD", "")
