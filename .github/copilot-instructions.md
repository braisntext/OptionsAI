# Small Smart Tools — Project Guidelines

## Project Overview
Multi-app financial tools platform ("Small Smart Tools") built with Flask.
Current apps: **Options Monitor** (live), **Alt Investments Tracker** (planned Q2-Q4 2026).

## Tech Stack
- **Backend**: Python 3 / Flask (app factory pattern `create_app()`)
- **Frontend**: Jinja2 templates, vanilla CSS (pastel theme with CSS custom properties), vanilla JS
- **Auth**: Magic links via Brevo (sib_api_v3_sdk), session-based, `login_required` decorator
- **Email**: Brevo transactional API
- **Deployment**: Render (see `render.yaml`)
- **Git**: `main` branch → `https://github.com/braisntext/OptionsAI.git`

## Architecture
- `options_monitor_agent/dashboard/app.py` — Main Flask app with all routes and APIs
- `options_monitor_agent/dashboard/templates/` — Jinja2 HTML templates
- `options_monitor_agent/dashboard/static/` — CSS (`landing.css`, `style.css`), JS (`app.js`, `i18n.js`)
- `options_monitor_agent/tools/` — Scrapers, calculators, notifiers
- `options_monitor_agent/memory/` — Persistent storage (SQLite via `database.py`)

## Code Style
- Language: Spanish for user-facing content, English for code (variables, functions, comments)
- CSS: Use CSS custom properties defined in `landing.css`; `style.css` extends for dashboard
- Flask routes: decorators for auth (`@login_required`), CSRF protection on forms
- Keep templates self-contained with inline `<style>` blocks for page-specific CSS

## Conventions
- Pricing tiers: Free (€0), Basic (€0.95/mo), Unlimited (€9.95/mo)
- All public pages share `landing.css` pastel theme; dashboard uses `landing.css` + `style.css`
- Dark mode via `prefers-color-scheme` media query in CSS
- Rate limiting on public APIs (e.g., contact form: 3 requests / 10 min)

## Build & Run
```bash
source .venv/bin/activate
pip install -r requirements.txt
python -m options_monitor_agent.dashboard.app  # Dev server
```
