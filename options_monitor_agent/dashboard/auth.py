import os
import secrets
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from functools import wraps
from urllib.parse import urlparse
from flask import (
    Blueprint, redirect, render_template, request,
    session, url_for, jsonify
)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
try:
    from config import BREVO_API_KEY, BREVO_SENDER_EMAIL, BREVO_SENDER_NAME
except ImportError:
    BREVO_API_KEY = os.getenv('BREVO_API_KEY', '')
    BREVO_SENDER_EMAIL = os.getenv('BREVO_SENDER_EMAIL', '')
    BREVO_SENDER_NAME = os.getenv('BREVO_SENDER_NAME', 'Small Smart Tools')

from subscribers import is_subscribed, add_free_subscriber, store_magic_token, consume_magic_token, verify_password, has_password, set_password
from security import record_failed_login

auth_bp = Blueprint('auth', __name__)

# ── Rate limiting for login requests (IP -> list of timestamps) ──────────────
_login_attempts: dict = defaultdict(list)
LOGIN_RATE_LIMIT = 5          # max requests
LOGIN_RATE_WINDOW = 300       # per 5 minutes

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
    api_key = BREVO_API_KEY
    sender_email = BREVO_SENDER_EMAIL
    sender_name = BREVO_SENDER_NAME
    if not api_key or not sender_email:
        print('[auth] ERROR: Brevo API key or sender email not configured.')
        return False
    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:480px;margin:auto;padding:32px;background:#0f1117;color:#e2e8f0;border-radius:12px">
      <h2 style="color:#3b82f6;margin-bottom:4px">&#9889; Small Smart Tools</h2>
      <p style="color:#94a3b8;margin-top:0">Your secure login link</p>
      <hr style="border:1px solid #1e293b;margin:24px 0">
      <p>Click the button below to sign in. This link expires in <strong>{TOKEN_TTL_MINUTES} minutes</strong> and can only be used once.</p>
      <a href="{link}" style="display:inline-block;padding:14px 28px;background:#3b82f6;color:#fff;text-decoration:none;border-radius:8px;font-weight:bold;font-size:16px;margin:16px 0">&#9889; Sign In Now</a>
      <p style="color:#64748b;font-size:12px">Or copy: {link}</p>
      <hr style="border:1px solid #1e293b;margin:24px 0">
      <p style="color:#475569;font-size:12px">If you didn't request this, ignore this email.</p>
    </div>
    """
    try:
        import sib_api_v3_sdk
        configuration = sib_api_v3_sdk.Configuration()
        configuration.api_key['api-key'] = api_key
        api_instance = sib_api_v3_sdk.TransactionalEmailsApi(
            sib_api_v3_sdk.ApiClient(configuration)
        )
        send_email = sib_api_v3_sdk.SendSmtpEmail(
            to=[{'email': to_email}],
            sender={'name': sender_name, 'email': sender_email},
            subject='\u26a1 Your Options Monitor Login Link',
            html_content=html,
        )
        api_instance.send_transac_email(send_email)
        print(f'[auth] Magic link sent to {to_email} via Brevo')
        return True
    except Exception as e:
        print(f'[auth] Failed to send email via Brevo: {e}')
        return False

def _is_safe_redirect(target: str) -> bool:
    """Only allow relative redirects (no scheme/netloc)."""
    if not target:
        return False
    parsed = urlparse(target)
    return parsed.scheme == '' and parsed.netloc == '' and target.startswith('/')

def _check_rate_limit(ip: str) -> bool:
    """Return True if IP is within rate limit."""
    now = datetime.utcnow()
    cutoff = now - timedelta(seconds=LOGIN_RATE_WINDOW)
    _login_attempts[ip] = [t for t in _login_attempts[ip] if t > cutoff]
    if len(_login_attempts[ip]) >= LOGIN_RATE_LIMIT:
        return False
    _login_attempts[ip].append(now)
    return True

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
        return redirect(url_for('home'))
    return render_template('login.html')

@auth_bp.route('/auth/request', methods=['POST'])
def auth_request():
    # ── Rate limiting ─────────────────────────────────────────────────────
    if not _check_rate_limit(request.remote_addr):
        return jsonify({'ok': False, 'error': 'Too many requests. Please wait a few minutes.'}), 429
    data  = request.get_json(silent=True) or {}
    email = (data.get('email') or '').strip().lower()
    if not email or '@' not in email:
        return jsonify({'ok': False, 'error': 'Invalid email address'}), 400
    if not _is_allowed(email):
        return jsonify({'ok': True})  # silent deny
    # ── Subscription gate — auto-register free tier ───────────────────────
    try:
        if not is_subscribed(email):
            add_free_subscriber(email)
    except Exception as exc:
        print(f'[auth] DB error during subscription check: {exc}')
        return jsonify({'ok': False, 'error': 'Server error. Please try again.'}), 500
    token      = secrets.token_urlsafe(32)
    expires_at = datetime.utcnow() + timedelta(minutes=TOKEN_TTL_MINUTES)
    try:
        store_magic_token(token, email, expires_at)
    except Exception as exc:
        print(f'[auth] DB error storing token: {exc}')
        return jsonify({'ok': False, 'error': 'Server error. Please try again.'}), 500
    link = url_for('auth.auth_verify', token=token, _external=True)
    sent = _send_magic_email(email, link)
    if not sent:
        return jsonify({'ok': False, 'error': 'Could not send email. Check server config.'}), 500
    return jsonify({'ok': True})

@auth_bp.route('/auth/verify/<token>')
def auth_verify(token):
    try:
        entry = consume_magic_token(token)
    except Exception as exc:
        print(f'[auth] DB error consuming token: {exc}')
        return render_template('login.html', error='Server error. Please request a new link.')
    if not entry:
        record_failed_login(request.remote_addr)
        return render_template('login.html', error='Invalid or already used link.')
    if datetime.utcnow() > entry['expires_at']:
        record_failed_login(request.remote_addr)
        return render_template('login.html', error='This link has expired. Please request a new one.')
    # Regenerate session to prevent session fixation
    session.clear()
    session.permanent = True
    session['authenticated'] = True
    session['email'] = entry['email']
    # Validate redirect URL to prevent open redirect
    next_url = request.args.get('next', '')
    if not _is_safe_redirect(next_url):
        next_url = url_for('home')
    return redirect(next_url)

@auth_bp.route('/auth/login-password', methods=['POST'])
def auth_login_password():
    """Authenticate with email + password."""
    if not _check_rate_limit(request.remote_addr):
        return jsonify({'ok': False, 'error': 'Demasiadas solicitudes. Espera unos minutos.'}), 429
    data = request.get_json(silent=True) or {}
    email = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''
    if not email or '@' not in email:
        return jsonify({'ok': False, 'error': 'Email inválido'}), 400
    if not password:
        return jsonify({'ok': False, 'error': 'Contraseña requerida'}), 400
    if not _is_allowed(email):
        record_failed_login(request.remote_addr)
        return jsonify({'ok': False, 'error': 'Credenciales incorrectas'}), 401
    if not is_subscribed(email):
        record_failed_login(request.remote_addr)
        return jsonify({'ok': False, 'error': 'Credenciales incorrectas'}), 401
    if not verify_password(email, password):
        record_failed_login(request.remote_addr)
        return jsonify({'ok': False, 'error': 'Credenciales incorrectas'}), 401
    session.clear()
    session.permanent = True
    session['authenticated'] = True
    session['email'] = email
    return jsonify({'ok': True})

@auth_bp.route('/auth/set-password', methods=['POST'])
def auth_set_password():
    """Set or update password for the logged-in user."""
    if not session.get('authenticated'):
        return jsonify({'ok': False, 'error': 'No autenticado'}), 401
    data = request.get_json(silent=True) or {}
    password = data.get('password') or ''
    if len(password) < 8:
        return jsonify({'ok': False, 'error': 'La contraseña debe tener al menos 8 caracteres'}), 400
    email = session.get('email', '')
    if not email:
        return jsonify({'ok': False, 'error': 'Sesión inválida'}), 401
    set_password(email, password)
    return jsonify({'ok': True, 'message': 'Contraseña actualizada'})

@auth_bp.route('/auth/has-password')
def auth_has_password():
    """Check if logged-in user has a password set."""
    if not session.get('authenticated'):
        return jsonify({'has_password': False})
    email = session.get('email', '')
    return jsonify({'has_password': has_password(email) if email else False})

@auth_bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('auth.login'))
