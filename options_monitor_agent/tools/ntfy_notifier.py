"""
Notification Tool — ntfy.sh (iPhone push) + Brevo (transactional email)

Setup:
  ntfy.sh  : Install free ntfy app on iPhone, subscribe to your topic.
             Set NTFY_TOPIC in config.py (e.g. "braisn-options-abc123")
  Email    : Set BREVO_API_KEY and BREVO_SENDER_EMAIL in .env
"""
import os
import urllib.request
import urllib.parse

# ---- Read config safely ----
try:
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from config import NTFY_TOPIC, BREVO_API_KEY, BREVO_SENDER_EMAIL, BREVO_SENDER_NAME
except ImportError:
    NTFY_TOPIC = ""
    BREVO_API_KEY = ""
    BREVO_SENDER_EMAIL = ""
    BREVO_SENDER_NAME = "Options Monitor"


def send_ntfy(title, message, priority="high", tags="chart_with_upwards_trend"):
    """Send push notification to iPhone via ntfy.sh (free, no account needed).
    priority: min, low, default, high, urgent
    tags: emoji shortcodes, e.g. 'warning' or 'chart_with_upwards_trend'
    """
    topic = NTFY_TOPIC or os.getenv("NTFY_TOPIC", "")
    if not topic:
        print("[ntfy] NTFY_TOPIC not set, skipping push")
        return False
    try:
        url = f"https://ntfy.sh/{topic}"
        data = message.encode("utf-8")
        # Encode title for HTTP header (handles emojis via URL encoding)
        from urllib.parse import quote
        encoded_title = quote(title)  # URL-encode to handle emojis
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Title": encoded_title,
                "Priority": priority,
                "Tags": tags,
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            print(f"[ntfy] Sent: {resp.status} — {title}")
            return True
    except Exception as e:
        print(f"[ntfy] Error: {e}")
        return False


def send_email(subject, body_html, body_text=None):
    """Send email alert via Brevo transactional API."""
    api_key = BREVO_API_KEY or os.getenv("BREVO_API_KEY", "")
    sender_email = BREVO_SENDER_EMAIL or os.getenv("BREVO_SENDER_EMAIL", "")
    sender_name = BREVO_SENDER_NAME or "Options Monitor"

    if not api_key or not sender_email:
        print("[email] Brevo credentials not set, skipping")
        return False
    try:
        import sib_api_v3_sdk
        configuration = sib_api_v3_sdk.Configuration()
        configuration.api_key['api-key'] = api_key
        api_instance = sib_api_v3_sdk.TransactionalEmailsApi(
            sib_api_v3_sdk.ApiClient(configuration)
        )
        send_smtp_email = sib_api_v3_sdk.SendSmtpEmail(
            to=[{'email': sender_email}],
            sender={'name': sender_name, 'email': sender_email},
            subject=subject,
            html_content=body_html,
        )
        api_instance.send_transac_email(send_smtp_email)
        print(f"[email] Sent via Brevo: {subject}")
        return True
    except Exception as e:
        print(f"[email] Brevo error: {e}")
        return False


def notify_premium_spike(spike):
    """Fire all enabled notifications for a premium spike alert."""
    ticker = spike["ticker"]
    opt_type = spike["option_type"]
    strike = spike["strike"]
    expiry = spike["expiration"]
    pct = spike["pct_change"]
    prev = spike["prev_mid"]
    curr = spike["curr_mid"]
    direction = spike["direction"]

    arrow = "⬆️" if direction == "UP" else "⬇️"
    sign = "+" if pct > 0 else ""
    title = f"⚡ Premium Spike: {ticker} {opt_type}"
    message = (
        f"{arrow} {ticker} ${strike} {opt_type} exp {expiry}\n"
        f"Premium: ${prev:.2f} → ${curr:.2f} ({sign}{pct:.1f}%)\n"
        f"Options Monitor Agent"
    )
    tags = "chart_with_upwards_trend" if direction == "UP" else "chart_with_downwards_trend"
    priority = "urgent" if abs(pct) >= 50 else "high"

    # Push notification
    send_ntfy(title, message, priority=priority, tags=tags)

    # Email
    html = f"""
    <div style='font-family:Arial;padding:20px;background:#1a1a2e;color:#fff;border-radius:8px'>
      <h2 style='color:#00d4ff'>⚡ Options Premium Spike Alert</h2>
      <table style='width:100%;border-collapse:collapse'>
        <tr><td style='padding:8px;color:#aaa'>Ticker</td><td style='padding:8px;font-weight:bold'>{ticker}</td></tr>
        <tr><td style='padding:8px;color:#aaa'>Type</td><td style='padding:8px'>{opt_type}</td></tr>
        <tr><td style='padding:8px;color:#aaa'>Strike</td><td style='padding:8px'>${strike}</td></tr>
        <tr><td style='padding:8px;color:#aaa'>Expiry</td><td style='padding:8px'>{expiry}</td></tr>
        <tr><td style='padding:8px;color:#aaa'>Prev Premium</td><td style='padding:8px'>${prev:.2f}</td></tr>
        <tr><td style='padding:8px;color:#aaa'>Curr Premium</td><td style='padding:8px;color:{'#00ff88' if direction=='UP' else '#ff4444'};font-size:1.3em'>${curr:.2f}</td></tr>
        <tr><td style='padding:8px;color:#aaa'>Change</td><td style='padding:8px;color:{'#00ff88' if direction=='UP' else '#ff4444'};font-weight:bold;font-size:1.5em'>{sign}{pct:.1f}% {arrow}</td></tr>
      </table>
      <p style='margin-top:20px;color:#666;font-size:0.8em'>Options Monitor Agent — braisn.pythonanywhere.com</p>
    </div>
    """
    send_email(f"⚡ {sign}{pct:.1f}% {ticker} {opt_type} ${strike} premium spike", html, body_text=message)


def notify_bulk_spikes(spikes):
    """Notify for multiple spikes in one email digest + individual push per spike."""
    if not spikes:
        return
    for spike in spikes:
        send_ntfy(
            f"⚡ {spike['ticker']} {spike['option_type']} +{spike['pct_change']:.0f}%",
            f"${spike['strike']} exp {spike['expiration']}\n"
            f"${spike['prev_mid']:.2f} → ${spike['curr_mid']:.2f}",
            priority="urgent" if abs(spike['pct_change']) >= 50 else "high",
            tags="chart_with_upwards_trend" if spike['direction'] == 'UP' else 'chart_with_downwards_trend'
        )
    # One combined email
    rows = "".join([
        f"<tr><td style='padding:6px;border-bottom:1px solid #333'>{s['ticker']}</td>"
        f"<td style='padding:6px;border-bottom:1px solid #333'>{s['option_type']}</td>"
        f"<td style='padding:6px;border-bottom:1px solid #333'>${s['strike']}</td>"
        f"<td style='padding:6px;border-bottom:1px solid #333'>{s['expiration']}</td>"
        f"<td style='padding:6px;border-bottom:1px solid #333'>${s['prev_mid']:.2f}</td>"
        f"<td style='padding:6px;border-bottom:1px solid #333;color:{'#00ff88' if s['direction']=='UP' else '#ff4444'}'>${s['curr_mid']:.2f}</td>"
        f"<td style='padding:6px;border-bottom:1px solid #333;font-weight:bold;color:{'#00ff88' if s['direction']=='UP' else '#ff4444'}'>{'+' if s['pct_change']>0 else ''}{s['pct_change']:.1f}%</td>"
        f"</tr>"
        for s in spikes
    ])
    html = f"""
    <div style='font-family:Arial;padding:20px;background:#1a1a2e;color:#fff'>
      <h2 style='color:#00d4ff'>⚡ {len(spikes)} Premium Spike(s) Detected</h2>
      <table style='width:100%;border-collapse:collapse;color:#fff'>
        <thead><tr style='color:#00d4ff'>
          <th style='padding:6px;text-align:left'>Ticker</th><th style='padding:6px;text-align:left'>Type</th>
          <th style='padding:6px;text-align:left'>Strike</th><th style='padding:6px;text-align:left'>Expiry</th>
          <th style='padding:6px;text-align:left'>Prev</th><th style='padding:6px;text-align:left'>Curr</th>
          <th style='padding:6px;text-align:left'>Change</th>
        </tr></thead>
        <tbody>{rows}</tbody>
      </table>
      <p style='color:#666;font-size:0.8em;margin-top:20px'>Options Monitor Agent — braisn.pythonanywhere.com</p>
    </div>
    """
    send_email(f"⚡ {len(spikes)} Options Premium Spike(s) Detected", html)
