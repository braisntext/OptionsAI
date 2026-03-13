"""
Background security agent — monitors suspicious activity.

Tracks:
  - Failed login attempts per IP (brute-force detection)
  - Request rate anomalies per IP
  - Expired token cleanup

Runs as a daemon thread alongside the Flask app.
"""

import threading
import time
from collections import defaultdict
from datetime import datetime, timezone

# ── Tracked events ────────────────────────────────────────────────────────────
_failed_logins: dict = defaultdict(list)   # ip -> [timestamps]
_request_counts: dict = defaultdict(list)  # ip -> [timestamps]
_blocked_ips: dict = {}                    # ip -> unblock_timestamp

# Thresholds
FAILED_LOGIN_THRESHOLD = 10    # failed attempts before temp-block
FAILED_LOGIN_WINDOW = 300      # 5 min window
BLOCK_DURATION = 900           # 15 min block
REQUEST_SPIKE_THRESHOLD = 200  # requests per minute before warning
REQUEST_SPIKE_WINDOW = 60      # 1 min window
CLEANUP_INTERVAL = 600         # purge expired data every 10 min


def record_failed_login(ip: str):
    """Record a failed login attempt from an IP."""
    now = time.time()
    cutoff = now - FAILED_LOGIN_WINDOW
    entries = _failed_logins[ip]
    entries.append(now)
    _failed_logins[ip] = entries = [t for t in entries if t > cutoff]
    if len(entries) >= FAILED_LOGIN_THRESHOLD:
        _blocked_ips[ip] = now + BLOCK_DURATION
        print(f"[security] BLOCKED IP {ip} — {len(entries)} failed logins in {FAILED_LOGIN_WINDOW}s")


def record_request(ip: str):
    """Record a request from an IP (bounded to last 5 min)."""
    now = time.time()
    entries = _request_counts[ip]
    entries.append(now)
    # Prune every 50 appends to stay bounded
    if len(entries) > 500:
        _request_counts[ip] = [t for t in entries if t > now - 300]


def is_ip_blocked(ip: str) -> bool:
    """Return True if IP is currently temp-blocked."""
    unblock = _blocked_ips.get(ip)
    if unblock is None:
        return False
    if time.time() > unblock:
        del _blocked_ips[ip]
        return False
    return True


def get_security_stats() -> dict:
    """Return current security state (for admin panel)."""
    now = time.time()
    login_cutoff = now - FAILED_LOGIN_WINDOW
    spike_cutoff = now - REQUEST_SPIKE_WINDOW
    half_thresh = REQUEST_SPIKE_THRESHOLD // 2

    high_rate = {}
    for ip, ts in _request_counts.items():
        recent = sum(1 for t in ts if t > spike_cutoff)
        if recent > half_thresh:
            high_rate[ip] = recent

    return {
        "blocked_ips": {ip: round(ts - now) for ip, ts in _blocked_ips.items() if ts > now},
        "recent_failed_logins": {
            ip: len(ts) for ip, ts in _failed_logins.items()
            if ts and ts[-1] > login_cutoff
        },
        "high_rate_ips": high_rate,
    }


def _cleanup_loop():
    """Periodically purge stale data and log anomalies."""
    while True:
        time.sleep(CLEANUP_INTERVAL)
        try:
            now = time.time()

            # Purge old failed login records
            for ip in list(_failed_logins.keys()):
                _failed_logins[ip] = [t for t in _failed_logins[ip] if t > now - FAILED_LOGIN_WINDOW]
                if not _failed_logins[ip]:
                    del _failed_logins[ip]

            # Purge old request counts + warn on spikes
            for ip in list(_request_counts.keys()):
                recent = [t for t in _request_counts[ip] if t > now - REQUEST_SPIKE_WINDOW]
                if len(recent) > REQUEST_SPIKE_THRESHOLD:
                    print(f"[security] WARNING: IP {ip} made {len(recent)} requests in last {REQUEST_SPIKE_WINDOW}s")
                _request_counts[ip] = [t for t in _request_counts[ip] if t > now - 300]
                if not _request_counts[ip]:
                    del _request_counts[ip]

            # Purge expired blocks
            for ip in list(_blocked_ips.keys()):
                if _blocked_ips[ip] < now:
                    print(f"[security] Unblocked IP {ip}")
                    del _blocked_ips[ip]

            # Purge expired magic tokens
            try:
                from subscribers import _conn
                with _conn() as c:
                    c.execute("DELETE FROM magic_tokens WHERE expires_at < ?",
                              (datetime.now(timezone.utc).isoformat(),))
                    purged = c.total_changes
                    c.commit()
                if purged:
                    print(f"[security] Purged {purged} expired magic token(s)")
            except Exception:
                pass

        except Exception as exc:
            print(f"[security] Cleanup error: {exc}")


def start_security_agent():
    """Launch the background security monitoring thread."""
    t = threading.Thread(target=_cleanup_loop, daemon=True, name="security-agent")
    t.start()
    print("[security] Background security agent started")
