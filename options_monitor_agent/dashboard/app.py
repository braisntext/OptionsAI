import os
import sys
import time
import threading
import subprocess
from datetime import timedelta

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
PYTHON_BIN   = sys.executable  # Use the same Python that runs the dashboard
RUN_CYCLE_PY = os.path.join(BASE_DIR, "run_cycle.py")
CYCLE_LOG    = os.path.join(BASE_DIR, "cycle.log")


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
        "process":      None,      # subprocess.Popen – never serialised
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
        """Poll subprocess state on every call – survives WSGI restarts."""
        proc = cycle_status["process"]
        if proc is not None and cycle_status["running"]:
            rc = proc.poll()            # None = still running
            if rc is not None:
                cycle_status["running"]      = False
                cycle_status["completed_at"] = time.time()
                cycle_status["result"]       = {"status": "ok"} if rc == 0 else None
                cycle_status["error"]        = None if rc == 0 else f"Exit code {rc}"
        safe = {k: v for k, v in cycle_status.items() if k != "process"}
        return jsonify({"status": "ok", "cycle": safe})

    @app.route("/api/run-cycle", methods=["POST"])
    @login_required
    def api_run_cycle():
        """Launch run_cycle.py as a detached subprocess."""
        # Check if already running (poll the real process)
        proc = cycle_status["process"]
        if cycle_status["running"] and proc and proc.poll() is None:
            return jsonify({"status": "ok", "message": "Cycle already running"})

        # Reset stale state
        cycle_status["running"] = False

        try:
            new_proc = subprocess.Popen(
                [PYTHON_BIN, RUN_CYCLE_PY],
                stdout=open(CYCLE_LOG, "w"),
                stderr=subprocess.STDOUT,
                close_fds=True,
                cwd=BASE_DIR,
            )
            cycle_status.update({
                "running":      True,
                "process":      new_proc,
                "result":       None,
                "error":        None,
                "completed_at": None,
            })

            # Background watcher – updates status when process exits.
            # daemon=True means it won't block app shutdown.
            def _watch():
                new_proc.wait()
                cycle_status["running"]      = False
                cycle_status["completed_at"] = time.time()
                rc = new_proc.returncode
                if rc == 0:
                    cycle_status["result"] = {"status": "ok"}
                else:
                    cycle_status["error"]  = f"Exit code {rc}"

            threading.Thread(target=_watch, daemon=True, name="cycle-watcher").start()
            return jsonify({"status": "ok", "message": "Cycle started"})

        except Exception as exc:
            return _make_error(str(exc)), 500

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
