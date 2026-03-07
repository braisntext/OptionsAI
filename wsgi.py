"""
WSGI entry point for Render / gunicorn.

Usage (Render start command):
    gunicorn wsgi:app --bind 0.0.0.0:$PORT
"""

import os
import sys

os.environ.setdefault("MPLBACKEND", "Agg")

# ── Put the agent package on sys.path ─────────────────────────────────────────
AGENT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "options_monitor_agent")
if AGENT_DIR not in sys.path:
    sys.path.insert(0, AGENT_DIR)

from dashboard.app import create_app

app = create_app()
