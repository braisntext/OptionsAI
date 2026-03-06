import os
from functools import wraps
from flask import (
    Blueprint, render_template, request, redirect,
    url_for, session, jsonify, flash
)
from subscribers import (
    is_subscribed, get_subscriber, add_subscriber,
    cancel_subscriber, list_subscribers, list_payments
)

billing_bp = Blueprint('billing', __name__)

SUPERADMIN = {'braisnatural@gmail.com'}

def _superadmin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get('email', '').lower() not in {e.lower() for e in SUPERADMIN}:
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated

# ──────────────────────────────────────────────────────────
# PUBLIC: Subscription / Pricing page
# ──────────────────────────────────────────────────────────
@billing_bp.route('/subscribe')
def subscribe():
    return render_template('subscribe.html')

# ──────────────────────────────────────────────────────────
# PUBLIC: Payment page
# ──────────────────────────────────────────────────────────
@billing_bp.route('/payment')
def payment():
    email = request.args.get('email', '')
    return render_template('payment.html', email=email)

# ──────────────────────────────────────────────────────────
# INTERNAL: Stripe webhook (placeholder)
# ──────────────────────────────────────────────────────────
@billing_bp.route('/webhook/stripe', methods=['POST'])
def stripe_webhook():
    # Stripe will POST payment events here
    # TODO: verify Stripe-Signature header
    data = request.get_json(silent=True) or {}
    event_type = data.get('type', '')
    if event_type == 'checkout.session.completed':
        obj   = data.get('data', {}).get('object', {})
        email = obj.get('customer_email', '')
        if email:
            add_subscriber(email, months=1, method='stripe',
                           reference=obj.get('id'), amount=0.95)
    return jsonify({'ok': True})

# ──────────────────────────────────────────────────────────
# USER PANEL
# ──────────────────────────────────────────────────────────
@billing_bp.route('/account')
def account():
    if not session.get('authenticated'):
        return redirect(url_for('auth.login', next='/account'))
    email = session.get('email', '')
    sub   = get_subscriber(email)
    return render_template('account.html', email=email, sub=sub)

@billing_bp.route('/account/cancel', methods=['POST'])
def cancel():
    if not session.get('authenticated'):
        return redirect(url_for('auth.login'))
    email = session.get('email', '')
    cancel_subscriber(email)
    session.clear()
    return redirect(url_for('billing.subscribe') + '?cancelled=1')

# ──────────────────────────────────────────────────────────
# ADMIN PANEL (superadmin only)
# ──────────────────────────────────────────────────────────
@billing_bp.route('/admin/subscribers')
@_superadmin_required
def admin_subscribers():
    subs     = list_subscribers()
    payments = list_payments()
    return render_template('admin_subscribers.html', subs=subs, payments=payments)

@billing_bp.route('/admin/subscribers/add', methods=['POST'])
@_superadmin_required
def admin_add():
    email  = request.form.get('email', '').strip().lower()
    months = int(request.form.get('months', 1))
    notes  = request.form.get('notes', 'manual')
    if email:
        add_subscriber(email, months=months, method='manual', amount=0.0)
    return redirect(url_for('billing.admin_subscribers'))

@billing_bp.route('/admin/subscribers/cancel', methods=['POST'])
@_superadmin_required
def admin_cancel():
    email = request.form.get('email', '').strip().lower()
    if email:
        cancel_subscriber(email)
    return redirect(url_for('billing.admin_subscribers'))
