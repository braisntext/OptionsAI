#!/usr/bin/env python3
"""
Standalone cycle runner - launched as a subprocess by the web dashboard.

Exit codes:
  0  - cycle completed successfully
  1  - unhandled exception
  2  - agent initialisation failed
"""
import sys
import os
os.environ.setdefault("MPLBACKEND", "Agg")  # Prevent matplotlib GUI segfault
import time
import traceback
from datetime import datetime

# Ensure the project root is on sys.path regardless of cwd
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
os.chdir(BASE_DIR)


def _ts():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


print(f"[run_cycle] Starting at {_ts()}")
t0 = time.time()

try:
    from agent import OptionsMonitorAgent
except Exception as exc:
    print(f"[run_cycle] FATAL: could not import agent - {exc}")
    traceback.print_exc()
    sys.exit(2)

try:
    agent  = OptionsMonitorAgent()
    result = agent.run_cycle()
    status = result.get("status", "?")
    elapsed = time.time() - t0
    print(f"[run_cycle] Completed: {status} in {elapsed:.1f}s at {_ts()}")
    sys.exit(0)

except KeyboardInterrupt:
    print("[run_cycle] Interrupted")
    sys.exit(1)

except Exception as exc:
    print(f"[run_cycle] ERROR: {exc}")
    traceback.print_exc()
    sys.exit(1)
