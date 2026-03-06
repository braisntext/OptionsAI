import os
import sys
import time
import json
import threading
from datetime import timedelta, datetime

# ── Path setup (run from any working directory) ───────────────────────────────
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(_THIS_DIR)
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from auth import auth_bp, login_required
from flask import Flask, render_template, jsonify, request, session, redirect, url_for

# ── Constants ─────────────────────────────────────────────────────────────────
CYCLE_LOG = os.path.join(BASE_DIR, "cycle.log")


def _make_error(msg, **kwargs):
    """Uniform error response helper."""
    return jsonify({"status": "error", "message": msg, **kwargs})


def create_app(database=None, agent=None):
    """
    Application factory.  Called by the WSGI entry-point with live
    db / agent objects; also works standalone (both None).
    """
    db_instance = database
    agent_ref   = [agent]          # mutable cell so closures can update it

    # ── Cycle state ───────────────────────────────────────────────────────────
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
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "options-monitor-secret")
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)
    app.config['SESSION_COOKIE_SECURE'] = False  # set True if using HTTPS
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    app.register_blueprint(auth_bp)
    from billing import billing_bp
    app.register_blueprint(billing_bp)

    # ── Helper: DB guard ──────────────────────────────────────────────────────
    def _require_db():
        """Return db_instance or raise a JSONified 503."""
        if db_instance is None:
            raise RuntimeError("DB not available")
        return db_instance

    # =========================================================================
    # ROUTES – UI
    # =========================================================================

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
            return jsonify({"status": "ok", "data": db.get_unusual_history(ticker, days)})
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

    @app.route("/api/spike-alerts")
    @login_required
    def api_spike_alerts():
        hours = request.args.get("hours", 24, type=int)
        try:
            from tools.premium_spike_tool import get_recent_spike_alerts
            return jsonify({"status": "ok", "data": get_recent_spike_alerts(hours=hours)})
        except Exception as exc:
            return _make_error(str(exc), data=[]), 500

    @app.route("/api/options-chain")
    @login_required
    def api_options_chain():
        ticker = request.args.get("ticker")
        if not ticker:
            return _make_error("ticker parameter required"), 400
        try:
            import yfinance as yf
            stock       = yf.Ticker(ticker)
            expirations = stock.options
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

    @app.route("/api/ask", methods=["POST"])
    @login_required
    def api_ask():
        agent = _get_agent()
        if agent is None:
            return _make_error("Agent not available"), 503
        question = (request.json or {}).get("question", "").strip()
        if not question:
            return _make_error("question field required"), 400
        try:
            return jsonify({"status": "ok", "response": agent._call_claude(question)})
        except Exception as exc:
            return _make_error(str(exc)), 500

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
        if cycle_status["running"]:
            return jsonify({"status": "ok", "message": "Cycle already running"})

        def _fast_cycle():
            """Quick cycle: scrape → greeks → analyze → save.  Skips Claude/email."""
            t0 = time.time()
            log_lines = []
            def _log(msg):
                log_lines.append(msg)
                print(f"[fast-cycle] {msg}")

            try:
                from config import WATCHLIST
                from tools.options_scraper import get_options_data, MEFF_TICKERS, MEFF_CACHE_DIR
                from tools.analysis_tool import analyze_options_data
                from tools.greeks_calculator import GreeksCalculator

                greeks = GreeksCalculator()

                # ── Phase 1: Scrape (use MEFF cache for .MC, yfinance for US) ──
                _log(f"Phase 1: Scraping {len(WATCHLIST)} tickers...")
                raw_data = []
                for ticker in WATCHLIST:
                    # For .MC tickers: try MEFF cache first (instant) before slow scrape
                    if ticker.endswith(".MC") and ticker in MEFF_TICKERS:
                        cache_file = os.path.join(MEFF_CACHE_DIR, f"{ticker.replace('.', '_')}.json")
                        if os.path.exists(cache_file):
                            try:
                                with open(cache_file) as f:
                                    cached = json.load(f)
                                cached['timestamp'] = datetime.now().isoformat()
                                cached['note'] = 'MEFF cache (fast refresh)'
                                raw_data.append(cached)
                                _log(f"  {ticker}: MEFF cache ({cached.get('calls_count',0)} calls)")
                                continue
                            except Exception:
                                pass
                    # yfinance scrape (fast for US, slow for .MC without cache)
                    data = get_options_data(ticker)
                    _log(f"  {ticker}: {data.get('status','?')} ({data.get('calls_count',0)} calls)")
                    raw_data.append(data)

                # ── Phase 2: Greeks ──
                _log("Phase 2: Computing Greeks...")
                for i, data in enumerate(raw_data):
                    if data.get("status") == "success":
                        raw_data[i] = greeks.enrich_options_with_greeks(data)

                # ── Phase 3: Analyze ──
                _log("Phase 3: Analyzing...")
                analysis = analyze_options_data(raw_data)

                # ── Phase 4: Save to DB ──
                _log("Phase 4: Saving to DB...")
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

    return app


# ── Dev server entry-point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    _app = create_app()
    _app.run(host="127.0.0.1", port=5001, debug=True)
