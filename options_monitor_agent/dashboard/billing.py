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

try:
    from config import SUPERADMIN_EMAILS
    SUPERADMIN = set(SUPERADMIN_EMAILS)
except ImportError:
    SUPERADMIN = {'braisnatural@gmail.com', 'braisontour@gmail.com'}

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
    stripe_secret = os.getenv('STRIPE_WEBHOOK_SECRET', '')
    if not stripe_secret:
        return jsonify({'ok': False}), 503
    # Verify Stripe signature
    sig_header = request.headers.get('Stripe-Signature', '')
    if not sig_header:
        return jsonify({'ok': False, 'error': 'Missing signature'}), 401
    try:
        import stripe
        event = stripe.Webhook.construct_event(
            request.data, sig_header, stripe_secret
        )
    except ValueError:
        return jsonify({'ok': False}), 400
    except stripe.error.SignatureVerificationError:
        print('[stripe] WARNING: Webhook signature verification FAILED')
        return jsonify({'ok': False}), 401
    except Exception as exc:
        print(f'[stripe] Unexpected webhook error: {exc}')
        return jsonify({'ok': False}), 403
    if event['type'] == 'checkout.session.completed':
        obj   = event['data']['object']
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

    # Determine plan label and app access
    plan_label = 'Sin plan'
    has_all_apps = False
    can_options = False
    can_fiscal = False

    if sub:
        plan = (sub['plan'] or '').lower()
        is_super = bool(sub['superuser'])

        if is_super:
            plan_label = 'Lifetime (Superuser)'
            has_all_apps = True
        elif plan == 'unlimited':
            plan_label = 'Unlimited'
            has_all_apps = True
        elif plan == 'basic':
            plan_label = 'Basic'
        elif plan == 'monthly':
            plan_label = 'Basic'
        elif plan == 'lifetime':
            plan_label = 'Lifetime'
            has_all_apps = True
        elif plan == 'free':
            plan_label = 'Free'
        else:
            plan_label = plan.capitalize() if plan else 'Free'

        if has_all_apps:
            can_options = True
            can_fiscal = True
        else:
            # Free and Basic plans: both apps available (1-app limit managed elsewhere)
            can_options = sub['status'] == 'active'
            can_fiscal = sub['status'] == 'active'

    return render_template('account.html', email=email, sub=sub,
                           plan_label=plan_label, has_all_apps=has_all_apps,
                           can_options=can_options, can_fiscal=can_fiscal)

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
        admin = session.get('email', '')
        print(f'[audit] ADMIN_ADD: admin={admin} added user={email} months={months} ip={request.remote_addr}')
    return redirect(url_for('billing.admin_subscribers'))

@billing_bp.route('/admin/subscribers/cancel', methods=['POST'])
@_superadmin_required
def admin_cancel():
    email = request.form.get('email', '').strip().lower()
    if email:
        cancel_subscriber(email)
        admin = session.get('email', '')
        print(f'[audit] ADMIN_CANCEL: admin={admin} cancelled user={email} ip={request.remote_addr}')
    return redirect(url_for('billing.admin_subscribers'))
