# 🧰 Small Smart Tools

Multi-app financial tools platform built with Flask. Each app solves a specific investment problem — subscribe to the ones you need or get them all with a single plan.

**Live at**: [smallsmarttools.com](https://smallsmarttools.com)

## Apps

| App | Status | Description |
|-----|--------|-------------|
| **Options Monitor** | ✅ Live | Real-time options monitoring with Claude AI — IV, Greeks, spike alerts, backtesting |
| **Fiscal** | ✅ Live | Import broker statements (IBKR), auto-calculate IRPF tax, map to Spanish tax form casillas |
| **Gestión de Inversiones** | ✅ Live | Portfolio tracker with FIFO multi-broker, dividends, live prices, P&L, charts |
| **Alt Investments Tracker** | 🚧 Q2-Q4 2026 | Private equity, venture capital, real estate, hedge funds consolidation |

## Tech Stack

- **Backend**: Python 3.11 / Flask (app factory pattern)
- **Frontend**: Jinja2 templates, vanilla CSS (pastel theme + dark mode), vanilla JS
- **Database**: PostgreSQL (production via Render), SQLite (local dev)
- **Auth**: Magic links via Brevo + email/password login, session-based
- **Prices**: Yahoo Finance HTTP API + yfinance fallback
- **AI**: Anthropic Claude (options analysis chat)
- **Deployment**: Render (see `render.yaml`)

## Quick Start

```bash
# Clone
git clone https://github.com/braisntext/OptionsAI.git
cd OptionsAI

# Virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Dependencies
pip install -r requirements.txt

# Environment variables
cp .env.example .env
# Edit .env with your API keys (see .env.example for all options)

# Run dev server
python -m options_monitor_agent.dashboard.app
# → http://127.0.0.1:5000
```

## Project Structure

```
├── render.yaml                          # Render deployment config
├── requirements.txt                     # Python dependencies
├── wsgi.py                              # Gunicorn entry point
├── .env.example                         # Environment variables template
│
├── options_monitor_agent/
│   ├── dashboard/
│   │   ├── app.py                       # Flask app factory + all routes
│   │   ├── auth.py                      # Authentication (magic-link + password)
│   │   ├── billing.py                   # Subscription & payment routes
│   │   ├── subscribers.py               # User management, plans, limits, GDPR delete
│   │   ├── security.py                  # Background security agent (brute-force, rate anomaly)
│   │   ├── templates/                   # Jinja2 HTML templates
│   │   │   ├── landing.html             # Public landing page
│   │   │   ├── login.html               # Login (magic-link + password)
│   │   │   ├── home.html                # Post-login hub (app launcher)
│   │   │   ├── subscribe.html           # Pricing / plan selection
│   │   │   ├── index.html               # Options Monitor dashboard
│   │   │   ├── account.html             # User account & password mgmt
│   │   │   └── ...
│   │   └── static/
│   │       ├── landing.css              # Shared pastel theme (CSS custom vars)
│   │       ├── style.css                # Dashboard-specific styles
│   │       ├── app.js                   # Options Monitor JS
│   │       ├── investments.js           # Investments app JS
│   │       ├── two-tap.js               # Mobile-friendly two-tap confirm for destructive actions
│   │       └── i18n.js                  # EN/ES language switcher
│   │
│   ├── fiscal/
│   │   ├── routes.py                    # Fiscal blueprint routes
│   │   ├── database.py                  # Fiscal DB (statements, tax calcs)
│   │   ├── ibkr_parser.py              # Interactive Brokers CSV parser
│   │   ├── tax_engine.py               # IRPF calculation engine
│   │   └── exchange_rates.py           # ECB exchange rates
│   │
│   ├── investments/
│   │   ├── routes.py                    # Investments blueprint routes
│   │   ├── database.py                  # Positions, transactions, dividends DB
│   │   ├── fifo_engine.py              # FIFO lot matching engine
│   │   ├── price_service.py            # Yahoo Finance price fetching
│   │   └── import_fiscal.py            # Import from Fiscal module
│   │
│   ├── tools/
│   │   ├── options_scraper.py           # Options data scraping
│   │   ├── greeks_calculator.py         # Greeks calculation (Δ, Γ, Θ, ν, ρ)
│   │   ├── premium_spike_tool.py        # Premium spike detection
│   │   ├── backtester.py               # Signal backtesting
│   │   └── email_notifier.py           # Email/Telegram notifications
│   │
│   ├── memory/
│   │   └── database.py                  # Options Monitor SQLite persistence
│   │
│   └── db_utils.py                      # Shared SQLite↔PostgreSQL adapter
```

## Environment Variables

Copy `.env.example` to `.env` and fill in:

| Variable | Required | Description |
|----------|----------|-------------|
| `SECRET_KEY` | Yes* | Flask session secret (auto-generated on Render) |
| `ANTHROPIC_API_KEY` | Yes | Claude AI API key for options analysis |
| `BREVO_API_KEY` | Yes | Brevo transactional email (magic-link login) |
| `BREVO_SENDER_EMAIL` | Yes | Verified sender email in Brevo |
| `DATABASE_URL` | No | PostgreSQL URL (uses SQLite if absent) |
| `TELEGRAM_BOT_TOKEN` | No | Telegram bot for notifications |
| `TELEGRAM_CHAT_ID` | No | Telegram chat ID for alerts |

*On Render, `SECRET_KEY` is auto-generated and persists across deploys.

## Deployment (Render)

The project deploys automatically via `render.yaml`:

```bash
git push origin main  # Triggers auto-deploy on Render
```

Services:
- **Web**: Gunicorn (2 workers, 120s timeout)
- **Database**: PostgreSQL (free tier)

## Pricing Tiers

| Plan | Price | Features |
|------|-------|----------|
| Free | €0/mo | 1 app, 3 tickers, 3 alerts |
| Basic | €0.95/mo | 1 app, 25 tickers, 20 alerts, 5 AI queries/day |
| Unlimited | €9.95/mo | All apps, unlimited everything |

## Code Style

- **UI text**: Spanish
- **Code** (variables, functions, comments): English
- **CSS**: Custom properties defined in `landing.css`; dark mode via `prefers-color-scheme`
- **Auth**: `@login_required` decorator, CSRF on all mutating requests
- **Rate limiting**: Login (5/5min), contact (3/10min), external APIs (10/min per user)
- **Security**: Background agent — brute-force block (10 fails → 15 min ban), request anomaly detection, expired token cleanup
- **GDPR**: Full cascade delete of user data (subscribers, watchlists, spike configs, investments, fiscal)
- **Infra**: Self-ping keepalive for Render free tier, `/health` endpoint for uptime monitoring
- **Mobile UX**: Two-tap confirm pattern replaces `window.confirm()` on all destructive actions

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup instructions and guidelines.

## License

Proprietary — all rights reserved. See [LICENSE](LICENSE).
