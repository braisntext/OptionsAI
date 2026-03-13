import os
import sys
import re
import time
import json
import secrets
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import timedelta, datetime, timezone

import yfinance as yf
import numpy as np

# ── Path setup (run from any working directory) ───────────────────────────────
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(_THIS_DIR)
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from auth import auth_bp, login_required
from flask import Flask, render_template, jsonify, request, session, redirect, url_for
from security import (
    record_request, record_failed_login, is_ip_blocked,
    get_security_stats, start_security_agent,
)
from subscribers import (
    is_superuser, check_limit, increment_usage, LIMITS,
    get_user_watchlist, add_user_ticker, remove_user_ticker,
    get_all_watched_tickers, seed_user_watchlist, user_has_watchlist,
    get_user_spike_configs, add_user_spike_config,
    delete_user_spike_config, toggle_user_spike_config,
    has_app_access,
)

# ── Constants ─────────────────────────────────────────────────────────────────
CYCLE_LOG = os.path.join(BASE_DIR, "cycle.log")


def _load_watchlist():
    """Load union of all users' watchlists for the scheduler.
    Falls back to config defaults if no user has a watchlist yet."""
    tickers = get_all_watched_tickers()
    if tickers:
        return tickers
    # Fallback to config.py defaults (bootstrap)
    try:
        from config import WATCHLIST as _DEFAULT_WL
        return list(_DEFAULT_WL)
    except ImportError:
        return []


def _load_user_watchlist_or_seed(email: str) -> list:
    """Return user's watchlist; seed from defaults on first login."""
    if not user_has_watchlist(email):
        try:
            from config import WATCHLIST as _DEFAULT_WL
            seed_user_watchlist(email, _DEFAULT_WL)
        except ImportError:
            pass
    return get_user_watchlist(email)


def _make_error(msg, **kwargs):
    """Uniform error response helper."""
    return jsonify({"status": "error", "message": msg, **kwargs})


def _validate_ticker(ticker: str) -> bool:
    """Validate ticker: 1-12 chars, alphanumeric, may contain one dot for exchange suffix."""
    return bool(re.match(r'^[A-Z0-9]+(?:\.[A-Z]{1,4})?$', ticker)) and len(ticker) <= 12


# ── In-memory TTL cache for expensive operations ─────────────────────────────
_cache: dict = {}   # key -> (timestamp, data)
_CACHE_TTL = 30     # seconds

def _cached(key: str, ttl: int = _CACHE_TTL):
    """Return cached value if fresh, else None."""
    entry = _cache.get(key)
    if entry and (time.time() - entry[0]) < ttl:
        return entry[1]
    return None

def _set_cache(key: str, data):
    _cache[key] = (time.time(), data)


def create_app(database=None, agent=None):
    """
    Application factory.  Called by the WSGI entry-point with live
    db / agent objects; also works standalone (both None).
    """
    db_instance = database
    agent_ref   = [agent]          # mutable cell so closures can update it

    # ── Cycle state ───────────────────────────────────────────────────────────
    cycle_lock = threading.Lock()
    cycle_status = {
        "running":      False,
        "result":       None,
        "error":        None,
        "completed_at": None,
    }

    # ── Lazy agent initialisation ─────────────────────────────────────────────
    def _get_agent():
        if agent_ref[0] is None:
            try:
                from agent import OptionsMonitorAgent
                agent_ref[0] = OptionsMonitorAgent()
            except Exception as exc:
                print(f"[app] Agent init error: {exc}")
        return agent_ref[0]

    # ── Flask app ─────────────────────────────────────────────────────────────
    app = Flask(__name__, template_folder="templates", static_folder="static")

    # Trust Render's reverse-proxy headers so url_for(_external=True)
    # generates https:// links and Flask sees the real client IP.
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY") or secrets.token_hex(32)
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)
    app.config['SESSION_COOKIE_SECURE'] = os.getenv('RENDER', '') != ''  # True on Render (HTTPS)
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    app.register_blueprint(auth_bp)
    from billing import billing_bp
    app.register_blueprint(billing_bp)
    from options_monitor_agent.fiscal.routes import fiscal_bp
    app.register_blueprint(fiscal_bp)
    from options_monitor_agent.investments.routes import investments_bp
    app.register_blueprint(investments_bp)

    # ── CSRF protection ──────────────────────────────────────────────────────
    def _generate_csrf_token():
        if '_csrf_token' not in session:
            session['_csrf_token'] = secrets.token_hex(32)
        return session['_csrf_token']

    @app.context_processor
    def _inject_csrf():
        return dict(csrf_token=_generate_csrf_token)

    CSRF_EXEMPT_ENDPOINTS = {'billing.stripe_webhook', 'auth.auth_request', 'auth.auth_login_password'}

    @app.before_request
    def _check_csrf():
        if request.method not in ('POST', 'PUT', 'PATCH', 'DELETE'):
            return
        if request.endpoint in CSRF_EXEMPT_ENDPOINTS:
            return
        token = request.headers.get('X-CSRF-Token') or (request.form.get('_csrf_token') if request.form else None)
        if not token or token != session.get('_csrf_token'):
            return jsonify({'status': 'error', 'message': 'CSRF token missing or invalid'}), 403

    # ── Security agent: track requests + block abusive IPs ───────────────
    _SECURITY_SKIP = ('/health', '/static/')

    @app.before_request
    def _security_gate():
        if request.path.startswith(_SECURITY_SKIP):
            return
        ip = request.remote_addr
        if is_ip_blocked(ip):
            return jsonify({'status': 'error', 'message': 'Too many requests. Try again later.'}), 429
        record_request(ip)

    # ── Security headers ─────────────────────────────────────────────────────
    @app.after_request
    def _set_security_headers(response):
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        if os.getenv('RENDER', ''):
            response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        return response

    # ── Error handlers ─────────────────────────────────────────────────────────
    @app.errorhandler(404)
    def _handle_404(e):
        if request.path.startswith('/api/'):
            return jsonify({'status': 'error', 'message': 'Not found'}), 404
        return render_template('login.html', error='Página no encontrada (404)'), 404

    @app.errorhandler(500)
    def _handle_500(e):
        if request.path.startswith('/api/'):
            return jsonify({'status': 'error', 'message': 'Internal server error'}), 500
        return render_template('login.html', error='Error del servidor (500). Inténtalo de nuevo.'), 500

    # ── Health endpoint (for Render + UptimeRobot + self-ping) ────────────────
    @app.route("/health")
    def health():
        return jsonify({"status": "ok", "ts": datetime.now(timezone.utc).isoformat()})

    # ── Helper: DB guard ──────────────────────────────────────────────────────
    def _require_db():
        """Return db_instance or raise a JSONified 503."""
        if db_instance is None:
            raise RuntimeError("DB not available")
        return db_instance

    # =========================================================================
    # ROUTES – UI
    # =========================================================================

    @app.route("/api/csrf-token")
    def api_csrf_token():
        return jsonify({"csrf_token": _generate_csrf_token()})

    # ── Market status helpers ─────────────────────────────────────────────
    def _is_market_open():
        """Check if any tracked market (ES/US) is currently open.
        Returns dict with per-market status and overall open flag."""
        try:
            from zoneinfo import ZoneInfo
            madrid = ZoneInfo("Europe/Madrid")
        except ImportError:
            madrid = timezone(timedelta(hours=1))
        now = datetime.now(madrid)
        # Weekends
        if now.weekday() >= 5:
            return {"open": False, "es_open": False, "us_open": False,
                    "now_cet": now.strftime("%H:%M"), "weekday": now.strftime("%A")}
        hhmm = now.hour * 60 + now.minute
        # Spain: 09:00 – 17:30 CET
        es_open = 9 * 60 <= hhmm < 17 * 60 + 30
        # US: 15:30 – 22:00 CET
        us_open = 15 * 60 + 30 <= hhmm < 22 * 60
        return {
            "open": es_open or us_open,
            "es_open": es_open,
            "us_open": us_open,
            "now_cet": now.strftime("%H:%M"),
            "weekday": now.strftime("%A"),
        }

    @app.route("/api/market-status")
    @login_required
    def api_market_status():
        """Return market open/closed status and data freshness info."""
        status = _is_market_open()
        last_update = None
        try:
            db = _require_db()
            email = session.get('email', '')
            user_tickers = set(_load_user_watchlist_or_seed(email))
            if user_tickers:
                cache_key = 'all_tickers_latest'
                latest = _cached(cache_key)
                if latest is None:
                    latest = db.get_all_tickers_latest()
                    _set_cache(cache_key, latest)
                user_latest = [d for d in latest if d['ticker'] in user_tickers]
                if user_latest:
                    timestamps = [d.get('timestamp', '') for d in user_latest if d.get('timestamp')]
                    if timestamps:
                        last_update = max(timestamps)
        except Exception:
            pass
        status["last_update"] = last_update
        # Auto-refresh recommendation: market open and data > 15 min old
        should_refresh = False
        if status["open"] and last_update:
            try:
                from zoneinfo import ZoneInfo
                madrid = ZoneInfo("Europe/Madrid")
            except ImportError:
                madrid = timezone(timedelta(hours=1))
            last_dt = datetime.fromisoformat(last_update)
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=timezone.utc)
            age_minutes = (datetime.now(timezone.utc) - last_dt).total_seconds() / 60
            should_refresh = age_minutes > 15
        elif status["open"] and not last_update:
            should_refresh = True
        status["should_refresh"] = should_refresh
        return jsonify({"status": "ok", "market": status})

    @app.route("/")
    def landing():
        """Public landing page — entry point for all visitors."""
        if session.get('authenticated'):
            return redirect(url_for('home'))
        return render_template("landing.html")

    @app.route("/home")
    @login_required
    def home():
        """Authenticated user hub — see and launch all apps."""
        email = session.get('email', '')
        can_options = has_app_access(email, 'options')
        can_fiscal = has_app_access(email, 'fiscal')
        can_investments = has_app_access(email, 'investments')
        has_all = can_options and can_fiscal and can_investments
        return render_template('home.html', email=email,
                               can_options=can_options, can_fiscal=can_fiscal,
                               can_investments=can_investments, has_all_apps=has_all)

    @app.route("/alt-investments")
    def alt_investments():
        """Public informational page for Alt Investments Tracker."""
        return render_template("alt_investments.html")

    @app.route("/fiscal")
    @login_required
    def fiscal():
        """Fiscal Import dashboard — requires paid plan."""
        from subscribers import has_app_access
        if not has_app_access(session.get('email', ''), 'fiscal'):
            return redirect(url_for('billing.account'))
        return render_template("fiscal.html")

    @app.route("/investments")
    @login_required
    def investments():
        """Investment management dashboard."""
        return render_template("investments.html")

    @app.route("/dashboard")
    @login_required
    def dashboard():
        return render_template("index.html")

    # =========================================================================
    # ROUTES – CONTACT FORM (public, rate-limited)
    # =========================================================================
    _contact_attempts: dict = defaultdict(list)
    CONTACT_RATE_LIMIT = 3
    CONTACT_RATE_WINDOW = 600  # 10 minutes

    @app.route("/api/contact", methods=["POST"])
    def api_contact():
        # Rate limit by IP
        ip = request.remote_addr
        now = time.time()
        cutoff = now - CONTACT_RATE_WINDOW
        _contact_attempts[ip] = [t for t in _contact_attempts[ip] if t > cutoff]
        if len(_contact_attempts[ip]) >= CONTACT_RATE_LIMIT:
            return jsonify({"ok": False, "error": "Demasiados mensajes. Espera unos minutos."}), 429
        _contact_attempts[ip].append(now)

        data = request.get_json(silent=True) or {}
        name = (data.get("name") or "").strip()[:100]
        email = (data.get("email") or "").strip()[:200]
        message = (data.get("message") or "").strip()[:2000]

        if not name or not email or not message:
            return jsonify({"ok": False, "error": "Todos los campos son obligatorios."}), 400
        if "@" not in email or "." not in email:
            return jsonify({"ok": False, "error": "Email no válido."}), 400

        try:
            from config import BREVO_API_KEY, BREVO_SENDER_EMAIL, BREVO_SENDER_NAME, SUPERADMIN_EMAILS
        except ImportError:
            BREVO_API_KEY = os.getenv("BREVO_API_KEY", "")
            BREVO_SENDER_EMAIL = os.getenv("BREVO_SENDER_EMAIL", "")
            BREVO_SENDER_NAME = os.getenv("BREVO_SENDER_NAME", "Small Smart Tools")
            SUPERADMIN_EMAILS = [os.getenv("SUPERADMIN_EMAIL", "braisnatural@gmail.com")]

        if not BREVO_API_KEY or not BREVO_SENDER_EMAIL:
            print("[contact] Brevo not configured")
            return jsonify({"ok": False, "error": "Servicio no disponible. Inténtalo más tarde."}), 503

        admin_email = SUPERADMIN_EMAILS[0] if SUPERADMIN_EMAILS else "braisnatural@gmail.com"

        import html as html_mod
        safe_name = html_mod.escape(name)
        safe_email = html_mod.escape(email)
        safe_message = html_mod.escape(message).replace("\n", "<br>")

        html_body = f"""
        <div style="font-family:Inter,Arial,sans-serif;max-width:560px;margin:auto;padding:32px;background:#F8FAFC;color:#1E293B;border-radius:16px;border:1px solid #EDF2F7">
          <h2 style="color:#7C3AED;margin-bottom:4px">📬 Nuevo mensaje de contacto</h2>
          <hr style="border:1px solid #EDF2F7;margin:20px 0">
          <p><strong>Nombre:</strong> {safe_name}</p>
          <p><strong>Email:</strong> <a href="mailto:{safe_email}">{safe_email}</a></p>
          <hr style="border:1px solid #EDF2F7;margin:20px 0">
          <p><strong>Mensaje:</strong></p>
          <div style="background:#FFFFFF;padding:16px;border-radius:8px;border:1px solid #EDF2F7;margin-top:8px">{safe_message}</div>
          <hr style="border:1px solid #EDF2F7;margin:20px 0">
          <p style="color:#64748B;font-size:12px">Enviado desde el formulario de contacto de Small Smart Tools</p>
        </div>
        """

        try:
            import sib_api_v3_sdk
            configuration = sib_api_v3_sdk.Configuration()
            configuration.api_key["api-key"] = BREVO_API_KEY
            api_instance = sib_api_v3_sdk.TransactionalEmailsApi(
                sib_api_v3_sdk.ApiClient(configuration)
            )

            # 1) Email to admin
            send_email = sib_api_v3_sdk.SendSmtpEmail(
                to=[{"email": admin_email}],
                sender={"name": BREVO_SENDER_NAME, "email": BREVO_SENDER_EMAIL},
                reply_to={"email": email, "name": name},
                subject=f"📬 Contacto SST: {name}",
                html_content=html_body,
            )
            api_instance.send_transac_email(send_email)
            print(f"[contact] Message from {email} sent to {admin_email}")

            # 2) Confirmation email to the visitor
            confirm_html = f"""
            <div style="font-family:Inter,Arial,sans-serif;max-width:560px;margin:auto;padding:32px;background:#F8FAFC;color:#1E293B;border-radius:16px;border:1px solid #EDF2F7">
              <h2 style="color:#7C3AED;margin-bottom:4px">✓ Hemos recibido tu mensaje</h2>
              <hr style="border:1px solid #EDF2F7;margin:20px 0">
              <p>Hola <strong>{safe_name}</strong>,</p>
              <p>Gracias por escribirnos. Hemos recibido tu mensaje y te responderemos en menos de 24 horas.</p>
              <hr style="border:1px solid #EDF2F7;margin:20px 0">
              <p style="color:#64748B;font-size:13px"><strong>Tu mensaje:</strong></p>
              <div style="background:#FFFFFF;padding:16px;border-radius:8px;border:1px solid #EDF2F7;margin-top:8px;font-size:14px">{safe_message}</div>
              <hr style="border:1px solid #EDF2F7;margin:20px 0">
              <p style="color:#64748B;font-size:12px">— El equipo de Small Smart Tools<br><a href="https://smallsmarttools.com" style="color:#7C3AED">smallsmarttools.com</a></p>
            </div>
            """
            confirm_email = sib_api_v3_sdk.SendSmtpEmail(
                to=[{"email": email, "name": name}],
                sender={"name": BREVO_SENDER_NAME, "email": BREVO_SENDER_EMAIL},
                subject="✓ Hemos recibido tu mensaje — Small Smart Tools",
                html_content=confirm_html,
            )
            api_instance.send_transac_email(confirm_email)
            print(f"[contact] Confirmation sent to {email}")

            return jsonify({"ok": True})
        except Exception as e:
            print(f"[contact] Brevo error: {e}")
            return jsonify({"ok": False, "error": "Error al enviar. Inténtalo más tarde."}), 500

    # =========================================================================
    # ROUTES – DATA
    # =========================================================================

    @app.route("/api/latest")
    @login_required
    def api_latest():
        try:
            db = _require_db()
            email = session.get('email', '')
            user_tickers = set(_load_user_watchlist_or_seed(email))
            cache_key = 'all_tickers_latest'
            all_data = _cached(cache_key)
            if all_data is None:
                all_data = db.get_all_tickers_latest()
                _set_cache(cache_key, all_data)
            data = [d for d in all_data if d['ticker'] in user_tickers]
            return jsonify({"status": "ok", "data": data})
        except RuntimeError as exc:
            return _make_error(str(exc)), 503

    @app.route("/api/history/<ticker>")
    @login_required
    def api_history(ticker):
        days = request.args.get("days", 30, type=int)
        try:
            db = _require_db()
            return jsonify({"status": "ok", "ticker": ticker,
                            "data": db.get_ticker_history(ticker, days)})
        except RuntimeError as exc:
            return _make_error(str(exc)), 503

    @app.route("/api/alerts")
    @login_required
    def api_alerts():
        hours = request.args.get("hours", 24, type=int)
        try:
            db = _require_db()
            email = session.get('email', '')
            user_tickers = set(_load_user_watchlist_or_seed(email))
            all_alerts = db.get_recent_alerts(hours)
            data = [a for a in all_alerts if a.get('ticker') in user_tickers]
            return jsonify({"status": "ok", "data": data})
        except RuntimeError as exc:
            return _make_error(str(exc)), 503

    @app.route("/api/unusual")
    @login_required
    def api_unusual():
        ticker = request.args.get("ticker") or None
        days   = request.args.get("days", 7, type=int)
        try:
            db = _require_db()
            email = session.get('email', '')
            user_tickers = set(_load_user_watchlist_or_seed(email))
            raw = db.get_unusual_history(ticker, days)
            # Filter by user's watchlist
            raw = [r for r in raw if r.get('ticker') in user_tickers]
            # Deduplicate by (ticker, type, strike, expiration) keeping newest
            seen = set()
            deduped = []
            for r in raw:
                key = (r.get("ticker"), r.get("type"), r.get("strike"), r.get("expiration"))
                if key not in seen:
                    seen.add(key)
                    deduped.append(r)
            return jsonify({"status": "ok", "data": deduped})
        except RuntimeError as exc:
            return _make_error(str(exc)), 503

    @app.route("/api/backtest")
    @login_required
    def api_backtest():
        try:
            db = _require_db()
            return jsonify({"status": "ok", "data": db.get_backtest_signals(days=30)})
        except RuntimeError as exc:
            return _make_error(str(exc)), 503

    @app.route("/api/stats")
    @login_required
    def api_stats():
        try:
            db = _require_db()
            cache_key = 'db_stats'
            stats = _cached(cache_key, ttl=60)
            if stats is None:
                stats = db.get_database_stats()
                _set_cache(cache_key, stats)
            return jsonify({"status": "ok", "data": stats})
        except RuntimeError as exc:
            return _make_error(str(exc)), 503

    @app.route("/api/usage")
    @login_required
    def api_usage():
        email = session.get('email', '')
        su = is_superuser(email)
        wl_count = len(get_user_watchlist(email))
        alert_count = len(get_user_spike_configs(email))
        _, ask_remaining, ask_limit = check_limit(email, 'ask_agent_max')
        return jsonify({
            "status": "ok",
            "superuser": su,
            "limits": {
                "watchlist": {"used": wl_count, "max": 999 if su else LIMITS['watchlist_max']},
                "alerts":    {"used": alert_count, "max": 999 if su else LIMITS['alerts_max']},
                "ask_agent": {"remaining": 999 if su else ask_remaining, "max": 999 if su else ask_limit},
            }
        })

    @app.route("/api/spike-alerts")
    @login_required
    def api_spike_alerts():
        hours = request.args.get("hours", 24, type=int)
        try:
            from tools.premium_spike_tool import get_recent_spike_alerts
            return jsonify({"status": "ok", "data": get_recent_spike_alerts(hours=hours)})
        except Exception as exc:
            return _make_error(str(exc), data=[]), 500

    # ── Spike alert config persistence (per-user) ──────────────────────────────

    @app.route("/api/spike-configs")
    @login_required
    def api_spike_configs_get():
        email = session.get('email', '')
        configs = get_user_spike_configs(email)
        return jsonify({"status": "ok", "configs": configs})

    @app.route("/api/spike-configs", methods=["POST"])
    @login_required
    def api_spike_configs_post():
        email = session.get('email', '')
        if not is_superuser(email):
            configs_count = len(get_user_spike_configs(email))
            if configs_count >= LIMITS['alerts_max']:
                return jsonify({"status": "error", "message": f"Alert limit reached ({LIMITS['alerts_max']}). Upgrade to superuser for unlimited."}), 403
        data = request.get_json(silent=True) or {}
        ticker = (data.get("ticker") or "").strip().upper()
        if not ticker:
            return jsonify({"status": "error", "message": "Ticker is required"}), 400
        threshold = float(data.get("threshold", 25))
        option_type = (data.get("option_type") or "ALL").upper()
        if option_type not in ("CALL", "PUT", "ALL"):
            option_type = "ALL"
        notify_push = bool(data.get("notify_push", True))
        notify_email = bool(data.get("notify_email", False))
        cfg = add_user_spike_config(email, ticker, threshold, option_type,
                                    notify_push, notify_email)
        return jsonify({"status": "ok", "config": cfg})

    @app.route("/api/spike-configs/<int:cfg_id>", methods=["DELETE"])
    @login_required
    def api_spike_configs_delete(cfg_id):
        email = session.get('email', '')
        delete_user_spike_config(email, cfg_id)
        return jsonify({"status": "ok"})

    @app.route("/api/spike-configs/<int:cfg_id>/toggle", methods=["POST"])
    @login_required
    def api_spike_configs_toggle(cfg_id):
        email = session.get('email', '')
        toggle_user_spike_config(email, cfg_id)
        return jsonify({"status": "ok"})

    @app.route("/api/options-chain")
    @login_required
    def api_options_chain():
        email = session.get('email', '')
        if not is_superuser(email) and not _check_ext_api_rate(email):
            return _make_error("Too many requests. Please wait a minute."), 429
        ticker = request.args.get("ticker", "").strip().upper()
        if not ticker or not _validate_ticker(ticker):
            return _make_error("Invalid ticker format"), 400
        try:
            stock       = yf.Ticker(ticker)
            expirations = stock.options

            # ---- MEFF cache fallback for Spanish tickers ----
            if not expirations and ticker.endswith(".MC"):
                _cache_file = os.path.join(
                    BASE_DIR, "data", "meff_cache",
                    f"{ticker.replace('.', '_')}.json"
                )
                if os.path.exists(_cache_file):
                    with open(_cache_file) as _f:
                        _cached = json.load(_f)
                    def _meff_row(opt, opt_type):
                        return {
                            "type":             opt_type,
                            "expiration":       opt.get("expiration", ""),
                            "strike":           float(opt.get("strike", 0)),
                            "lastPrice":        float(opt.get("lastPrice", 0) or 0),
                            "bid":              float(opt.get("bid", 0) or 0),
                            "ask":              float(opt.get("ask", 0) or 0),
                            "volume":           0,
                            "openInterest":     0,
                            "impliedVolatility": round(float(opt.get("impliedVolatility", 0)) * 100, 2),
                        }
                    calls_list = [_meff_row(c, "CALL") for c in _cached.get("calls", [])]
                    puts_list  = [_meff_row(p, "PUT")  for p in _cached.get("puts", [])]
                    exps = _cached.get("expirations_analyzed", [])
                    # deduplicate expirations
                    seen = set(); exps = [e for e in exps if e and e not in seen and not seen.add(e)]
                    return jsonify({"status": "ok", "ticker": ticker,
                                    "calls": calls_list, "puts": puts_list,
                                    "expirations": exps,
                                    "source": "MEFF cache"})
                return _make_error(f"No options available for {ticker}"), 404

            if not expirations:
                return _make_error(f"No options available for {ticker}"), 404

            def _row(row, opt_type, exp_date):
                """Convert a DataFrame row to a clean dict."""
                def _int(v):  return int(v)  if v == v else 0   # NaN guard
                def _float(v): return float(v) if v == v else 0.0
                return {
                    "type":             opt_type,
                    "expiration":       exp_date,
                    "strike":           _float(row.get("strike", 0)),
                    "lastPrice":        _float(row.get("lastPrice", 0)),
                    "bid":              _float(row.get("bid", 0)),
                    "ask":              _float(row.get("ask", 0)),
                    "volume":           _int(row.get("volume", 0)),
                    "openInterest":     _int(row.get("openInterest", 0)),
                    "impliedVolatility": round(_float(row.get("impliedVolatility", 0)) * 100, 2),
                }

            calls_list, puts_list = [], []
            def _fetch_chain(exp_date):
                c = stock.option_chain(exp_date)
                cl = [_row(r, "CALL", exp_date) for _, r in c.calls.iterrows()]
                pl = [_row(r, "PUT",  exp_date) for _, r in c.puts.iterrows()]
                return cl, pl
            exps = list(expirations[:6])
            with ThreadPoolExecutor(max_workers=min(len(exps), 4)) as pool:
                results = pool.map(_fetch_chain, exps)
            for cl, pl in results:
                calls_list.extend(cl)
                puts_list.extend(pl)

            return jsonify({"status": "ok", "ticker": ticker,
                            "calls": calls_list, "puts": puts_list,
                            "expirations": list(expirations)})
        except Exception as exc:
            return _make_error(str(exc)), 500

    # =========================================================================
    # ROUTES – AI CHAT
    # =========================================================================

    # ── Per-user rate limiting for /api/ask (max 3 requests per 60 seconds)
    _ask_rate: dict = defaultdict(list)
    ASK_RATE_LIMIT = 3
    ASK_RATE_WINDOW = 60  # seconds

    def _check_ask_rate(email: str) -> bool:
        now = time.time()
        cutoff = now - ASK_RATE_WINDOW
        _ask_rate[email] = [t for t in _ask_rate[email] if t > cutoff]
        if len(_ask_rate[email]) >= ASK_RATE_LIMIT:
            return False
        _ask_rate[email].append(now)
        return True

    # ── Rate limiting for external API calls (yfinance, etc.) ────────────────
    _ext_api_rate: dict = defaultdict(list)
    EXT_API_RATE_LIMIT = 10   # max calls per user
    EXT_API_RATE_WINDOW = 60  # per 60 seconds

    def _check_ext_api_rate(email: str) -> bool:
        """Rate-limit user access to yfinance-heavy endpoints."""
        now = time.time()
        cutoff = now - EXT_API_RATE_WINDOW
        _ext_api_rate[email] = [t for t in _ext_api_rate[email] if t > cutoff]
        if len(_ext_api_rate[email]) >= EXT_API_RATE_LIMIT:
            return False
        _ext_api_rate[email].append(now)
        return True

    def _build_user_context(email):
        """Build a data context string with the user's watchlist and latest data."""
        parts = []
        try:
            user_tickers = _load_user_watchlist_or_seed(email)
            parts.append(f"User watchlist: {', '.join(user_tickers)}")
            db = _require_db()
            all_latest = db.get_all_tickers_latest()
            user_data = [d for d in all_latest if d['ticker'] in set(user_tickers)]
            if user_data:
                parts.append("\nLatest data for user's tickers:")
                for d in user_data:
                    parts.append(
                        f"  {d['ticker']}: price=${d.get('price',0):.2f}, "
                        f"Call IV={d.get('call_iv',0):.1f}%, Put IV={d.get('put_iv',0):.1f}%, "
                        f"P/C ratio={d.get('pcr_volume',0):.2f}, IV skew={d.get('iv_skew',0):.1f}%, "
                        f"sentiment={d.get('sentiment','N/A')}, updated={d.get('timestamp','N/A')}"
                    )
            alerts = db.get_recent_alerts(hours=48)
            user_alerts = [a for a in alerts if a.get('ticker') in set(user_tickers)]
            if user_alerts:
                parts.append(f"\nRecent alerts ({len(user_alerts)}):")
                for a in user_alerts[:10]:
                    parts.append(f"  [{a.get('ticker')}] {a.get('severity','')}: {a.get('message','')}")
        except Exception:
            pass
        return "\n".join(parts)

    @app.route("/api/ask", methods=["POST"])
    @login_required
    def api_ask():
        question = (request.json or {}).get("question", "").strip()
        if not question:
            return _make_error("question field required"), 400
        # ── Per-minute rate limit ─────────────────────────────────────────
        email = session.get('email', '')
        if not is_superuser(email) and not _check_ask_rate(email):
            return jsonify({"status": "error", "message": f"Too many requests. Please wait {ASK_RATE_WINDOW}s between bursts (max {ASK_RATE_LIMIT}/min)."}), 429
        # ── Usage limit: agent queries per day ────────────────────────────
        allowed, remaining, limit = check_limit(email, 'ask_agent_max')
        if not allowed:
            return jsonify({"status": "error", "message": f"Daily query limit reached ({limit}). Resets tomorrow. Superusers have unlimited queries."}), 403
        increment_usage(email, 'ask_agent_max')
        # Build context from user's data
        context = _build_user_context(email)
        enriched_question = f"[User data context]\n{context}\n\n[User question]\n{question}" if context else question
        # Try Claude agent first
        agent = _get_agent()
        claude_error = None
        if agent is not None:
            try:
                result = agent._call_claude(enriched_question)
                if not result.startswith("Error with Claude"):
                    return jsonify({"status": "ok", "response": result})
                claude_error = result
                print(f"[ask] Claude failed: {result}")
            except Exception as exc:
                claude_error = str(exc)
                print(f"[ask] Claude error: {exc}")
        else:
            claude_error = "Agent could not be initialized (check ANTHROPIC_API_KEY)"
        # Fallback: answer from local data + explain why AI is unavailable
        try:
            db = _require_db()
            answer = _local_answer(db, question)
            if claude_error:
                answer += f"\n\n⚠️ *AI agent unavailable: {claude_error}*"
            return jsonify({"status": "ok", "response": answer})
        except Exception as exc:
            return _make_error(str(exc)), 500

    def _local_answer(db, question):
        """Generate a data-driven answer without Claude."""
        q = question.lower()
        email = session.get('email', '')
        user_tickers = set(_load_user_watchlist_or_seed(email))
        all_latest = db.get_all_tickers_latest()
        latest = [d for d in all_latest if d['ticker'] in user_tickers]
        if not latest:
            return "No data available yet. Run a cycle first to collect options data."
        # Build summary
        lines = ["📊 **Current Watchlist Status:**\n"]
        for d in latest:
            pcr = d.get('pcr_volume', 0)
            sentiment = '🐻' if pcr > 1.2 else ('🐂' if pcr < 0.8 else '😐')
            lines.append(f"**{d['ticker']}** — ${d['price']:.2f} | Call IV: {d.get('call_iv',0):.1f}% | Put IV: {d.get('put_iv',0):.1f}% | P/C: {pcr:.2f} {sentiment}")
        # Sentiment summary
        pcrs = [d.get('pcr_volume', 0) for d in latest if d.get('pcr_volume', 0) > 0]
        avg_pcr = sum(pcrs) / len(pcrs) if pcrs else 0
        if avg_pcr > 1.2:
            lines.append(f"\n🐻 **Overall sentiment: BEARISH** (avg P/C ratio: {avg_pcr:.2f})")
        elif avg_pcr < 0.8:
            lines.append(f"\n🐂 **Overall sentiment: BULLISH** (avg P/C ratio: {avg_pcr:.2f})")
        else:
            lines.append(f"\n😐 **Overall sentiment: NEUTRAL** (avg P/C ratio: {avg_pcr:.2f})")
        # Ticker-specific question
        for d in latest:
            if d['ticker'].lower().replace('.mc','') in q:
                alerts = db.get_recent_alerts(hours=48)
                ticker_alerts = [a for a in alerts if a.get('ticker') == d['ticker']]
                if ticker_alerts:
                    lines.append(f"\n⚠️ **Alerts for {d['ticker']}:**")
                    for a in ticker_alerts[:5]:
                        lines.append(f"  • {a.get('message', '')}")
                break
        lines.append("\n💡 *Note: AI analysis requires Anthropic API key. Set ANTHROPIC_API_KEY in .env for full AI responses.*")
        return "\n".join(lines)

    # =========================================================================
    # ROUTES – CYCLE MANAGEMENT
    # =========================================================================

    @app.route("/api/cycle-status")
    @login_required
    def api_cycle_status():
        safe = {k: v for k, v in cycle_status.items() if k != "_thread"}
        return jsonify({"status": "ok", "cycle": safe})

    @app.route("/api/run-cycle", methods=["POST"])
    @login_required
    def api_run_cycle():
        """Run a fast in-process refresh cycle in a background thread."""
        with cycle_lock:
            if cycle_status["running"]:
                return jsonify({"status": "ok", "message": "Cycle already running"})

        def _fast_cycle():
            """Ultra-fast cycle: batch prices + cached/synthetic options → analyze → save."""
            t0 = time.time()
            log_lines = []
            def _log(msg):
                log_lines.append(msg)
                print(f"[fast-cycle] {msg}")

            try:
                WATCHLIST = _load_watchlist()
                from tools.options_scraper import MEFF_TICKERS, MEFF_CACHE_DIR
                from tools.analysis_tool import analyze_options_data
                from tools.greeks_calculator import GreeksCalculator
                from tools.synthetic_options import generate_synthetic_options

                greeks = GreeksCalculator()

                # ── Phase 1: Batch price download (single HTTP call) ──
                _log(f"Phase 1: Batch price download for {len(WATCHLIST)} tickers...")
                prices = {}
                hvs = {}
                try:
                    df = yf.download(WATCHLIST, period="30d", progress=False, threads=True)
                    for ticker in WATCHLIST:
                        try:
                            col = df['Close'][ticker] if len(WATCHLIST) > 1 else df['Close']
                            series = col.dropna()
                            if len(series) > 0:
                                prices[ticker] = round(float(series.iloc[-1]), 2)
                            if len(series) > 1:
                                log_ret = np.log(series / series.shift(1)).dropna()
                                hvs[ticker] = round(float(log_ret.std() * np.sqrt(252) * 100), 2)
                        except Exception:
                            pass
                except Exception as exc:
                    _log(f"  yf.download error: {exc}")

                _log(f"  Prices: {len(prices)}/{len(WATCHLIST)} tickers")

                # ── Phase 2: Build raw_data from cache + synthetic ──
                _log("Phase 2: Building options data (cache + synthetic)...")
                raw_data = []
                for ticker in WATCHLIST:
                    price = prices.get(ticker, 0)
                    hv = hvs.get(ticker, 25.0)
                    entry = None

                    # Try MEFF cache for .MC tickers
                    if ticker.endswith(".MC") and ticker in MEFF_TICKERS:
                        cache_file = os.path.join(MEFF_CACHE_DIR, f"{ticker.replace('.', '_')}.json")
                        if os.path.exists(cache_file):
                            try:
                                with open(cache_file) as f:
                                    entry = json.load(f)
                                entry['timestamp'] = datetime.now().isoformat()
                                if price > 0:
                                    entry['current_price'] = price
                                _log(f"  {ticker}: MEFF cache, price={price}")
                            except Exception:
                                entry = None

                    # Generate synthetic options if no cache
                    if not entry and price > 0:
                        entry = generate_synthetic_options(
                            ticker, price, hv, {}
                        )
                        _log(f"  {ticker}: synthetic (HV={hv}%), price={price}")
                    elif not entry:
                        entry = {
                            'ticker': ticker, 'current_price': 0,
                            'timestamp': datetime.now().isoformat(),
                            'status': 'error', 'error': 'No price data',
                            'calls': [], 'puts': [],
                            'calls_count': 0, 'puts_count': 0,
                            'put_call_ratio': 0,
                        }
                        _log(f"  {ticker}: no data")

                    raw_data.append(entry)

                # ── Phase 3: Greeks ──
                _log("Phase 3: Computing Greeks...")
                for i, data in enumerate(raw_data):
                    if data.get("status") == "success":
                        raw_data[i] = greeks.enrich_options_with_greeks(data)

                # ── Phase 4: Analyze ──
                _log("Phase 4: Analyzing...")
                analysis = analyze_options_data(raw_data)

                # ── Phase 5: Save to DB ──
                _log("Phase 5: Saving to DB...")
                db = _require_db()
                db.save_snapshot(analysis)
                db.save_alerts(analysis.get("alerts", []))
                db.save_unusual_activity(analysis.get("unusual_activity", []))

                elapsed = time.time() - t0
                _log(f"Done in {elapsed:.1f}s")

                cycle_status["running"]      = False
                cycle_status["completed_at"] = time.time()
                cycle_status["result"]       = {"status": "ok", "time": round(elapsed, 1)}
                cycle_status["error"]        = None

            except Exception as exc:
                elapsed = time.time() - t0
                _log(f"ERROR: {exc}")
                cycle_status["running"]      = False
                cycle_status["completed_at"] = time.time()
                cycle_status["error"]        = str(exc)

            # Write log
            try:
                with open(CYCLE_LOG, "w") as f:
                    f.write("\n".join(log_lines) + "\n")
            except Exception:
                pass

        with cycle_lock:
            cycle_status.update({
                "running":      True,
                "result":       None,
                "error":        None,
                "completed_at": None,
            })
        t = threading.Thread(target=_fast_cycle, daemon=True, name="fast-cycle")
        t.start()
        return jsonify({"status": "ok", "message": "Cycle started"})

    @app.route("/api/cycle-log")
    @login_required
    def api_cycle_log():
        """Return the last 50 lines of the cycle log file."""
        try:
            if not os.path.exists(CYCLE_LOG):
                return jsonify({"status": "ok", "log": []})
            with open(CYCLE_LOG, "r", errors="replace") as fh:
                lines = fh.readlines()[-50:]
            return jsonify({"status": "ok", "log": lines})
        except Exception as exc:
            return _make_error(str(exc)), 500

    # =========================================================================
    # ROUTES – WATCHLIST MANAGEMENT
    # =========================================================================

    @app.route("/api/watchlist-quotes")
    @login_required
    def api_watchlist_quotes():
        """Return live price for every watchlist ticker via yfinance (parallel)."""
        email = session.get('email', '')
        if not is_superuser(email) and not _check_ext_api_rate(email):
            return _make_error("Too many requests. Please wait a minute."), 429
        wl = _load_user_watchlist_or_seed(email)
        # Return cached quotes if fresh (30s TTL)
        cache_key = f'quotes:{email}'
        cached = _cached(cache_key)
        if cached is not None:
            return jsonify({"status": "ok", "quotes": cached})
        quotes = {}
        def _fetch_one(ticker):
            try:
                fi = yf.Ticker(ticker).fast_info
                p = getattr(fi, 'last_price', None) or getattr(fi, 'previous_close', None)
                if p and p > 0:
                    return ticker, round(p, 2)
            except Exception:
                pass
            return ticker, None
        try:
            with ThreadPoolExecutor(max_workers=min(len(wl), 8)) as pool:
                futures = {pool.submit(_fetch_one, t): t for t in wl}
                for future in as_completed(futures, timeout=10):
                    try:
                        ticker, price = future.result()
                        if price is not None:
                            quotes[ticker] = price
                    except Exception:
                        pass
        except Exception:
            pass
        _set_cache(cache_key, quotes)
        return jsonify({"status": "ok", "quotes": quotes})

    @app.route("/api/search-ticker")
    @login_required
    def api_search_ticker():
        email = session.get('email', '')
        if not is_superuser(email) and not _check_ext_api_rate(email):
            return _make_error("Too many requests. Please wait a minute."), 429
        q = request.args.get("q", "").strip()
        if len(q) < 1:
            return jsonify({"status": "ok", "results": []})
        try:
            results = []
            # yfinance doesn't have a search API, so we validate the ticker directly
            # and also try common suffixes
            candidates = [q.upper()]
            if not q.endswith(".MC"):
                candidates.append(q.upper() + ".MC")
            for candidate in candidates:
                try:
                    t = yf.Ticker(candidate)
                    info = t.fast_info
                    price = getattr(info, 'last_price', None) or getattr(info, 'previous_close', None)
                    if price and price > 0:
                        # Get the long name if available
                        try:
                            name = t.info.get('shortName', '') or t.info.get('longName', candidate)
                        except Exception:
                            name = candidate
                        results.append({"symbol": candidate, "name": name, "price": round(price, 2)})
                except Exception:
                    pass
            return jsonify({"status": "ok", "results": results})
        except Exception as exc:
            return jsonify({"status": "ok", "results": []})

    @app.route("/api/watchlist")
    @login_required
    def api_watchlist_get():
        email = session.get('email', '')
        wl = _load_user_watchlist_or_seed(email)
        return jsonify({"status": "ok", "watchlist": wl})

    @app.route("/api/watchlist", methods=["POST"])
    @login_required
    def api_watchlist_add():
        ticker = (request.json or {}).get("ticker", "").strip().upper()
        if not ticker or not _validate_ticker(ticker):
            return _make_error("Invalid ticker format"), 400
        email = session.get('email', '')
        wl = get_user_watchlist(email)
        if ticker in wl:
            return jsonify({"status": "ok", "message": "Already in watchlist", "watchlist": wl})
        # ── Usage limit: watchlist size ───────────────────────────────────
        if not is_superuser(email) and len(wl) >= LIMITS['watchlist_max']:
            return jsonify({"status": "error", "message": f"Watchlist limit reached ({LIMITS['watchlist_max']} tickers). Upgrade to superuser for unlimited."}), 403
        add_user_ticker(email, ticker)
        wl = get_user_watchlist(email)
        # Invalidate scheduler ticker classification
        _TICKER_MARKET.clear()
        _classify_tickers()
        # Try to get a quick price snapshot for the new ticker
        price_info = {}
        try:
            t = yf.Ticker(ticker)
            fi = t.fast_info
            p = getattr(fi, 'last_price', None) or getattr(fi, 'previous_close', None)
            if p:
                price_info = {"price": round(p, 2), "valid": True}
        except Exception:
            pass
        return jsonify({"status": "ok", "watchlist": wl, "ticker_info": price_info})

    @app.route("/api/watchlist/<ticker>", methods=["DELETE"])
    @login_required
    def api_watchlist_remove(ticker):
        ticker = ticker.strip().upper()
        email = session.get('email', '')
        if not remove_user_ticker(email, ticker):
            return _make_error("Ticker not in watchlist"), 404
        wl = get_user_watchlist(email)
        _TICKER_MARKET.clear()
        _classify_tickers()
        return jsonify({"status": "ok", "watchlist": wl})

    @app.route("/api/scheduler-status")
    @login_required
    def api_scheduler_status():
        now = datetime.now(_MADRID)
        today = now.strftime("%Y-%m-%d")
        slots_today = []
        for market, times in _SCHEDULE.items():
            for (hh, mm) in times:
                key = f"{today}_{market}_{hh:02d}:{mm:02d}"
                slots_today.append({
                    "market": market, "time": f"{hh:02d}:{mm:02d}",
                    "fired": key in _fired_slots
                })
        return jsonify({"status": "ok", "now_cet": now.strftime("%H:%M"),
                        "weekday": now.strftime("%A"),
                        "slots": slots_today,
                        "tickers": {k: v for k, v in _TICKER_MARKET.items()}})

    # =========================================================================
    # MARKET-HOURS SCHEDULER
    # =========================================================================
    # Collection times (CET / Europe-Madrid):
    #   Spain (.MC): 09:10, 13:10, 17:10  (market 09:00 → +10min, +4h, +4h)
    #   US:          15:40, 19:40          (market 15:30 → +10min, +4h)

    _CET = timezone(timedelta(hours=1))   # CET (winter); adjust +1 for CEST
    try:
        from zoneinfo import ZoneInfo
        _MADRID = ZoneInfo("Europe/Madrid")  # handles CET/CEST automatically
    except ImportError:
        _MADRID = _CET  # fallback
    _SCHEDULE = {
        "ES": [(9, 10), (13, 10), (17, 10)],   # market 09:00: +10min, +4h, +4h
        "US": [(15, 40), (19, 40)],              # market 15:30: +10min, +4h
    }
    _TICKER_MARKET = {}  # filled lazily

    _fired_slots: dict = {}  # "2026-03-06_ES_09:10" → True

    def _classify_tickers():
        """Classify watchlist tickers into ES / US groups."""
        if _TICKER_MARKET:
            return _TICKER_MARKET
        for t in _load_watchlist():
            mkt = "ES" if t.endswith(".MC") else "US"
            _TICKER_MARKET.setdefault(mkt, []).append(t)
        return _TICKER_MARKET

    def _run_market_cycle(tickers, label):
        """Run a fast cycle for a subset of tickers."""
        if cycle_status["running"]:
            print(f"[scheduler] Skipping {label} — cycle already running")
            return
        t0 = time.time()
        log_lines = []
        def _log(msg):
            log_lines.append(msg)
            print(f"[scheduler:{label}] {msg}")

        cycle_status.update({"running": True, "result": None, "error": None, "completed_at": None})
        try:
            from tools.options_scraper import get_options_data, MEFF_TICKERS, MEFF_CACHE_DIR
            from tools.analysis_tool import analyze_options_data
            from tools.greeks_calculator import GreeksCalculator
            greeks = GreeksCalculator()

            _log(f"Scraping {len(tickers)} tickers: {tickers}")
            raw_data = []
            for ticker in tickers:
                if ticker.endswith(".MC") and ticker in MEFF_TICKERS:
                    cache_file = os.path.join(MEFF_CACHE_DIR, f"{ticker.replace('.', '_')}.json")
                    if os.path.exists(cache_file):
                        try:
                            with open(cache_file) as f:
                                cached = json.load(f)
                            cached['timestamp'] = datetime.now().isoformat()
                            cached['note'] = 'MEFF cache (scheduled)'
                            raw_data.append(cached)
                            _log(f"  {ticker}: MEFF cache")
                            continue
                        except Exception:
                            pass
                data = get_options_data(ticker)
                _log(f"  {ticker}: {data.get('status','?')}")
                raw_data.append(data)

            _log("Computing Greeks...")
            for i, data in enumerate(raw_data):
                if data.get("status") == "success":
                    raw_data[i] = greeks.enrich_options_with_greeks(data)

            _log("Analyzing...")
            analysis = analyze_options_data(raw_data)

            _log("Saving to DB...")
            db = _require_db()
            db.save_snapshot(analysis)
            db.save_alerts(analysis.get("alerts", []))
            db.save_unusual_activity(analysis.get("unusual_activity", []))

            # ── Premium spike detection ──────────────────────────────────
            try:
                from tools.premium_spike_tool import detect_spikes as _detect_spikes, save_snapshot as _save_snap
                from tools.ntfy_notifier import notify_bulk_spikes
                all_spikes = []
                for data in raw_data:
                    if data.get("status") != "success":
                        continue
                    t = data.get("ticker", "")
                    opts = data.get("calls", []) + data.get("puts", [])
                    if not opts:
                        continue
                    spikes = _detect_spikes(t, opts)
                    if spikes:
                        all_spikes.extend(spikes)
                    _save_snap(t, opts)
                if all_spikes:
                    _log(f"⚡ {len(all_spikes)} premium spike(s) detected")
                    notify_bulk_spikes(all_spikes)
            except Exception as spike_exc:
                _log(f"Spike detection error: {spike_exc}")

            elapsed = time.time() - t0
            _log(f"Done in {elapsed:.1f}s")
            cycle_status.update({"running": False, "completed_at": time.time(),
                                 "result": {"status": "ok", "time": round(elapsed, 1)}, "error": None})
        except Exception as exc:
            _log(f"ERROR: {exc}")
            cycle_status.update({"running": False, "completed_at": time.time(), "error": str(exc)})

        try:
            with open(CYCLE_LOG, "w") as f:
                f.write("\n".join(log_lines) + "\n")
        except Exception:
            pass

    def _scheduler_loop():
        """Background loop: check every 30s if it's time to collect data."""
        time.sleep(5)  # let server finish starting
        _classify_tickers()
        print("[scheduler] Market-hours scheduler started")
        while True:
            try:
                now = datetime.now(_MADRID)
                today = now.strftime("%Y-%m-%d")
                # Skip weekends (Mon=0, Sun=6)
                if now.weekday() >= 5:
                    time.sleep(60)
                    continue
                for market, slots in _SCHEDULE.items():
                    tickers = _TICKER_MARKET.get(market, [])
                    if not tickers:
                        continue
                    for (hh, mm) in slots:
                        slot_key = f"{today}_{market}_{hh:02d}:{mm:02d}"
                        if slot_key in _fired_slots:
                            continue
                        # Fire if within a 2-minute window of the target time
                        target_min = hh * 60 + mm
                        current_min = now.hour * 60 + now.minute
                        if 0 <= (current_min - target_min) < 2:
                            print(f"[scheduler] Firing {slot_key}")
                            _fired_slots[slot_key] = True
                            threading.Thread(
                                target=_run_market_cycle,
                                args=(tickers, f"{market}_{hh:02d}:{mm:02d}"),
                                daemon=True
                            ).start()
            except Exception as exc:
                print(f"[scheduler] Error: {exc}")
            time.sleep(30)

    # Start the scheduler thread
    threading.Thread(target=_scheduler_loop, daemon=True, name="market-scheduler").start()

    # Start background security agent
    start_security_agent()

    # ── Self-ping keepalive (Render free tier) ────────────────────────────────
    def _self_ping_loop():
        """Ping /health every 10 min to prevent Render free tier spin-down."""
        import urllib.request
        base_url = os.getenv('RENDER_EXTERNAL_URL', '')
        if not base_url:
            print("[keepalive] RENDER_EXTERNAL_URL not set — self-ping disabled")
            return
        health_url = f"{base_url.rstrip('/')}/health"
        print(f"[keepalive] Self-ping started → {health_url}")
        while True:
            time.sleep(600)  # 10 minutes
            try:
                urllib.request.urlopen(health_url, timeout=10)
            except Exception as exc:
                print(f"[keepalive] Ping failed: {exc}")

    if os.getenv('RENDER', ''):
        threading.Thread(target=_self_ping_loop, daemon=True, name="self-ping").start()

    return app


# ── Dev server entry-point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    _app = create_app()
    _app.run(host="127.0.0.1", port=5001, debug=True)
