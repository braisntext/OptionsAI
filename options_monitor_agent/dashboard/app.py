import os
import sys
import re
import time
import json
import secrets
import threading
from collections import defaultdict
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
from subscribers import is_superuser, check_limit, increment_usage, LIMITS

# ── Constants ─────────────────────────────────────────────────────────────────
CYCLE_LOG = os.path.join(BASE_DIR, "cycle.log")
WATCHLIST_FILE = os.path.join(BASE_DIR, "watchlist.json")
SPIKE_CONFIGS_FILE = os.path.join(BASE_DIR, "spike_configs.json")


def _load_watchlist():
    """Load watchlist from JSON file, seeding from config.py if needed."""
    if os.path.exists(WATCHLIST_FILE):
        try:
            with open(WATCHLIST_FILE) as f:
                wl = json.load(f)
            if isinstance(wl, list) and wl:
                return wl
        except Exception:
            pass
    # Seed from config.py defaults
    try:
        from config import WATCHLIST as _DEFAULT_WL
        _save_watchlist(_DEFAULT_WL)
        return list(_DEFAULT_WL)
    except ImportError:
        return []


def _save_watchlist(wl):
    """Persist watchlist to JSON."""
    with open(WATCHLIST_FILE, "w") as f:
        json.dump(wl, f, indent=2)


def _make_error(msg, **kwargs):
    """Uniform error response helper."""
    return jsonify({"status": "error", "message": msg, **kwargs})


def _validate_ticker(ticker: str) -> bool:
    """Validate ticker: 1-12 chars, alphanumeric, may contain one dot for exchange suffix."""
    return bool(re.match(r'^[A-Z0-9]+(?:\.[A-Z]{1,4})?$', ticker)) and len(ticker) <= 12


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
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY") or secrets.token_hex(32)
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=12)
    app.config['SESSION_COOKIE_SECURE'] = os.getenv('RENDER', '') != ''  # True on Render (HTTPS)
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Strict'
    app.register_blueprint(auth_bp)
    from billing import billing_bp
    app.register_blueprint(billing_bp)

    # ── CSRF protection ──────────────────────────────────────────────────────
    def _generate_csrf_token():
        if '_csrf_token' not in session:
            session['_csrf_token'] = secrets.token_hex(32)
        return session['_csrf_token']

    @app.context_processor
    def _inject_csrf():
        return dict(csrf_token=_generate_csrf_token)

    CSRF_EXEMPT_ENDPOINTS = {'billing.stripe_webhook'}

    @app.before_request
    def _check_csrf():
        if request.method not in ('POST', 'PUT', 'PATCH', 'DELETE'):
            return
        if request.endpoint in CSRF_EXEMPT_ENDPOINTS:
            return
        token = request.headers.get('X-CSRF-Token') or (request.form.get('_csrf_token') if request.form else None)
        if not token or token != session.get('_csrf_token'):
            return jsonify({'status': 'error', 'message': 'CSRF token missing or invalid'}), 403

    # ── Security headers ─────────────────────────────────────────────────────
    @app.after_request
    def _set_security_headers(response):
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        if os.getenv('RENDER', ''):
            response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        return response

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

    @app.route("/")
    @login_required
    def index():
        return render_template("index.html")

    # =========================================================================
    # ROUTES – DATA
    # =========================================================================

    @app.route("/api/latest")
    @login_required
    def api_latest():
        try:
            db = _require_db()
            return jsonify({"status": "ok", "data": db.get_all_tickers_latest()})
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
            return jsonify({"status": "ok", "data": db.get_recent_alerts(hours)})
        except RuntimeError as exc:
            return _make_error(str(exc)), 503

    @app.route("/api/unusual")
    @login_required
    def api_unusual():
        ticker = request.args.get("ticker") or None
        days   = request.args.get("days", 7, type=int)
        try:
            db = _require_db()
            raw = db.get_unusual_history(ticker, days)
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
            return jsonify({"status": "ok", "data": db.get_database_stats()})
        except RuntimeError as exc:
            return _make_error(str(exc)), 503

    @app.route("/api/usage")
    @login_required
    def api_usage():
        email = session.get('email', '')
        su = is_superuser(email)
        wl_count = len(_load_watchlist())
        alert_count = len(_load_spike_configs()) if os.path.exists(SPIKE_CONFIGS_FILE) else 0
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

    # ── Spike alert config persistence ────────────────────────────────────────
    def _load_spike_configs():
        if os.path.exists(SPIKE_CONFIGS_FILE):
            try:
                with open(SPIKE_CONFIGS_FILE) as f:
                    return json.load(f)
            except Exception:
                pass
        return []

    def _save_spike_configs(configs):
        with open(SPIKE_CONFIGS_FILE, "w") as f:
            json.dump(configs, f, indent=2)

    @app.route("/api/spike-configs")
    @login_required
    def api_spike_configs_get():
        return jsonify({"status": "ok", "configs": _load_spike_configs()})

    @app.route("/api/spike-configs", methods=["POST"])
    @login_required
    def api_spike_configs_post():
        # ── Usage limit: alert configs ────────────────────────────────────
        email = session.get('email', '')
        if not is_superuser(email):
            configs_count = len(_load_spike_configs())
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
        configs = _load_spike_configs()
        cfg = {
            "id": int(time.time() * 1000),
            "ticker": ticker,
            "threshold": threshold,
            "option_type": option_type,
            "notify_push": notify_push,
            "notify_email": notify_email,
            "enabled": True,
            "created": datetime.now().isoformat(),
        }
        configs.append(cfg)
        _save_spike_configs(configs)
        return jsonify({"status": "ok", "config": cfg})

    @app.route("/api/spike-configs/<int:cfg_id>", methods=["DELETE"])
    @login_required
    def api_spike_configs_delete(cfg_id):
        configs = _load_spike_configs()
        configs = [c for c in configs if c.get("id") != cfg_id]
        _save_spike_configs(configs)
        return jsonify({"status": "ok"})

    @app.route("/api/spike-configs/<int:cfg_id>/toggle", methods=["POST"])
    @login_required
    def api_spike_configs_toggle(cfg_id):
        configs = _load_spike_configs()
        for c in configs:
            if c.get("id") == cfg_id:
                c["enabled"] = not c.get("enabled", True)
                break
        _save_spike_configs(configs)
        return jsonify({"status": "ok"})

    @app.route("/api/options-chain")
    @login_required
    def api_options_chain():
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
            for exp_date in expirations[:6]:
                chain = stock.option_chain(exp_date)
                calls_list.extend(_row(r, "CALL", exp_date) for _, r in chain.calls.iterrows())
                puts_list.extend( _row(r, "PUT",  exp_date) for _, r in chain.puts.iterrows())

            return jsonify({"status": "ok", "ticker": ticker,
                            "calls": calls_list, "puts": puts_list,
                            "expirations": list(expirations)})
        except Exception as exc:
            return _make_error(str(exc)), 500

    # =========================================================================
    # ROUTES – AI CHAT
    # =========================================================================

    # Per-user rate limiting for /api/ask (max 3 requests per 60 seconds)
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
        # Try Claude agent first
        agent = _get_agent()
        if agent is not None:
            try:
                result = agent._call_claude(question)
                if not result.startswith("Error with Claude"):
                    return jsonify({"status": "ok", "response": result})
                print(f"[ask] Claude failed: {result}")
            except Exception as exc:
                print(f"[ask] Claude error: {exc}")
        # Fallback: answer from local data
        try:
            db = _require_db()
            answer = _local_answer(db, question)
            return jsonify({"status": "ok", "response": answer})
        except Exception as exc:
            return _make_error(str(exc)), 500

    def _local_answer(db, question):
        """Generate a data-driven answer without Claude."""
        q = question.lower()
        latest = db.get_all_tickers_latest()
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
        """Return live price for every watchlist ticker via yfinance fast_info."""
        wl = _load_watchlist()
        quotes = {}
        try:
            for ticker in wl:
                try:
                    fi = yf.Ticker(ticker).fast_info
                    p = getattr(fi, 'last_price', None) or getattr(fi, 'previous_close', None)
                    if p and p > 0:
                        quotes[ticker] = round(p, 2)
                except Exception:
                    pass
        except Exception:
            pass
        return jsonify({"status": "ok", "quotes": quotes})

    @app.route("/api/search-ticker")
    @login_required
    def api_search_ticker():
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
        return jsonify({"status": "ok", "watchlist": _load_watchlist()})

    @app.route("/api/watchlist", methods=["POST"])
    @login_required
    def api_watchlist_add():
        ticker = (request.json or {}).get("ticker", "").strip().upper()
        if not ticker or not _validate_ticker(ticker):
            return _make_error("Invalid ticker format"), 400
        wl = _load_watchlist()
        if ticker in wl:
            return jsonify({"status": "ok", "message": "Already in watchlist", "watchlist": wl})
        # ── Usage limit: watchlist size ───────────────────────────────────
        email = session.get('email', '')
        if not is_superuser(email) and len(wl) >= LIMITS['watchlist_max']:
            return jsonify({"status": "error", "message": f"Watchlist limit reached ({LIMITS['watchlist_max']} tickers). Upgrade to superuser for unlimited."}), 403
        wl.append(ticker)
        _save_watchlist(wl)
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
        wl = _load_watchlist()
        if ticker not in wl:
            return _make_error("Ticker not in watchlist"), 404
        wl.remove(ticker)
        _save_watchlist(wl)
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
    #   Spain (.MC): 09:10, 14:00, 17:25  (market 09:00–17:30)
    #   US:          15:40, 20:30, 21:55  (market 15:30–22:00 CET = 09:30–16:00 ET)

    _CET = timezone(timedelta(hours=1))   # CET (winter); adjust +1 for CEST
    try:
        from zoneinfo import ZoneInfo
        _MADRID = ZoneInfo("Europe/Madrid")  # handles CET/CEST automatically
    except ImportError:
        _MADRID = _CET  # fallback
    _SCHEDULE = {
        "ES": [(9, 10), (14, 0), (17, 25)],   # Spanish market schedule
        "US": [(15, 40), (20, 30), (21, 55)],  # US market schedule in CET
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

    return app


# ── Dev server entry-point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    _app = create_app()
    _app.run(host="127.0.0.1", port=5001, debug=True)
