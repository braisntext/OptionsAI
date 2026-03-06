import os
import smtplib
import secrets
import sys
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from functools import wraps
from flask import (
    Blueprint, redirect, render_template, request,
    session, url_for, flash, jsonify
)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
try:
    from config import NOTIFY_EMAIL_FROM, NOTIFY_EMAIL_PASSWORD
except ImportError:
    NOTIFY_EMAIL_FROM = os.getenv('NOTIFY_EMAIL_FROM', '')
    NOTIFY_EMAIL_PASSWORD = os.getenv('NOTIFY_EMAIL_PASSWORD', '')

from subscribers import is_subscribed

auth_bp = Blueprint('auth', __name__)

# ── In-memory token store ────────────────────────────────────────────────────
_tokens: dict = {}

# ── Allowed emails whitelist (empty = anyone subscribed can log in) ──────────
ALLOWED_EMAILS_ENV = os.getenv('ALLOWED_EMAILS', '')
ALLOWED_EMAILS: set = {
    e.strip().lower()
    for e in ALLOWED_EMAILS_ENV.split(',')
    if e.strip()
}

TOKEN_TTL_MINUTES = 15
SESSION_DAYS = 7

# ── Helpers ──────────────────────────────────────────────────────────────────
def _is_allowed(email: str) -> bool:
    email = email.strip().lower()
    if not ALLOWED_EMAILS:
        return True
    return email in ALLOWED_EMAILS

def _send_magic_email(to_email: str, link: str) -> bool:
    smtp_server = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
    smtp_port   = int(os.getenv('SMTP_PORT', '587'))
    sender      = os.getenv('NOTIFY_EMAIL_FROM', NOTIFY_EMAIL_FROM)
    password    = os.getenv('NOTIFY_EMAIL_PASSWORD', NOTIFY_EMAIL_PASSWORD)
    if not sender or not password:
        print('[auth] ERROR: email credentials not configured.')
        return False
    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:480px;margin:auto;padding:32px;background:#0f1117;color:#e2e8f0;border-radius:12px">
      <h2 style="color:#3b82f6;margin-bottom:4px">&#9889; Options Monitor</h2>
      <p style="color:#94a3b8;margin-top:0">Your secure login link</p>
      <hr style="border:1px solid #1e293b;margin:24px 0">
      <p>Click the button below to sign in. This link expires in <strong>{TOKEN_TTL_MINUTES} minutes</strong> and can only be used once.</p>
      <a href="{link}" style="display:inline-block;padding:14px 28px;background:#3b82f6;color:#fff;text-decoration:none;border-radius:8px;font-weight:bold;font-size:16px;margin:16px 0">&#9889; Sign In Now</a>
      <p style="color:#64748b;font-size:12px">Or copy: {link}</p>
      <hr style="border:1px solid #1e293b;margin:24px 0">
      <p style="color:#475569;font-size:12px">If you didn't request this, ignore this email.</p>
    </div>
    """
    msg = msg = MIMEMultipart('alternative')
    msg['Subject'] = '\u26a1 Your Options Monitor Login Link'
    msg['From']    = sender
    msg['To']      = to_email
    msg.attach(MIMEText(html, 'html'))
    try:
        with smtplib.SMTP(smtp_server, smtp_port) as srv:
            srv.ehlo()
            srv.starttls()
            srv.login(sender, password)
            srv.sendmail(sender, [to_email], msg.as_string())
        print(f'[auth] Magic link sent to {to_email}')
        return True
    except Exception as e:
        print(f'[auth] Failed to send email: {e}')
        return False

def login_required(f):
    """Decorator: redirect to /login if not authenticated."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('authenticated'):
            return redirect(url_for('auth.login', next=request.path))
        return f(*args, **kwargs)
    return decorated

# ── Routes ───────────────────────────────────────────────────────────────────
@auth_bp.route('/login', methods=['GET'])
def login():
    if session.get('authenticated'):
        return redirect(url_for('index'))
    return render_template('login.html')

@auth_bp.route('/auth/request', methods=['POST'])
def auth_request():
    data  = request.get_json(silent=True) or {}
    email = (data.get('email') or '').strip().lower()
    if not email or '@' not in email:
        return jsonify({'ok': False, 'error': 'Invalid email address'}), 400
    if not _is_allowed(email):
        return jsonify({'ok': True})  # silent deny
    # ── Subscription gate ────────────────────────────────────────────────────
    if not is_subscribed(email):
        return jsonify({
            'ok': False,
            'not_subscribed': True,
            'error': 'No active subscription found for this email.',
            'subscribe_url': url_for('billing.subscribe', _external=True)
        }), 403
    token      = secrets.token_urlsafe(32)
    expires_at = datetime.utcnow() + timedelta(minutes=TOKEN_TTL_MINUTES)
    _tokens[token] = {'email': email, 'expires_at': expires_at}
    link = url_for('auth.auth_verify', token=token, _external=True)
    sent = _send_magic_email(email, link)
    if not sent:
        return jsonify({'ok': False, 'error': 'Could not send email. Check server config.'}), 500
    return jsonify({'ok': True})

@auth_bp.route('/auth/verify/<token>')
def auth_verify(token):
    entry = _tokens.get(token)
    if not entry:
        return render_template('login.html', error='Invalid or already used link.')
    if datetime.utcnow() > entry['expires_at']:
        _tokens.pop(token, None)
        return render_template('login.html', error='This link has expired. Please request a new one.')
    _tokens.pop(token, None)
    session.permanent = True
    session['authenticated'] = True
    session['email'] = entry['email']
    next_url = request.args.get('next') or url_for('index')
    return redirect(next_url)

@auth_bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('auth.login'))
