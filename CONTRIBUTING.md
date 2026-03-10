# Contributing to Small Smart Tools

Thanks for your interest in contributing! This guide will help you get up and running.

## Prerequisites

- Python 3.11+
- Git
- A code editor (VS Code recommended)

## Local Setup

```bash
# 1. Clone the repo
git clone https://github.com/braisntext/OptionsAI.git
cd OptionsAI

# 2. Create a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Set up environment variables
cp .env.example .env
# Edit .env — at minimum you need:
#   ANTHROPIC_API_KEY   (for AI chat)
#   BREVO_API_KEY       (for magic-link login)
#   BREVO_SENDER_EMAIL  (verified sender in Brevo)

# 5. Run the dev server
python -m options_monitor_agent.dashboard.app
# Open http://127.0.0.1:5000
```

### Local Database

Without `DATABASE_URL`, the app uses SQLite (files created in the project directory). This is fine for development — no setup needed.

To test against PostgreSQL locally:
```bash
export DATABASE_URL="postgresql://user:pass@localhost:5432/optionsai"
```

## Project Architecture

The app uses Flask's **app factory pattern** (`create_app()` in `app.py`).

### Blueprints

| Blueprint | Mount | File |
|-----------|-------|------|
| `auth` | `/login`, `/auth/*` | `dashboard/auth.py` |
| `billing` | `/subscribe`, `/payment` | `dashboard/billing.py` |
| `fiscal` | `/fiscal`, `/api/fiscal/*` | `fiscal/routes.py` |
| `investments` | `/investments`, `/api/investments/*` | `investments/routes.py` |

### Database Layer

All database access goes through `db_utils.py`, which transparently adapts SQL between SQLite and PostgreSQL:

- SQLite `?` placeholders → PostgreSQL `%s`
- `COLLATE NOCASE` → stripped for PostgreSQL (uses `ILIKE` instead)
- `AUTOINCREMENT` → `SERIAL` for PostgreSQL
- Connection pooling for PostgreSQL, file-based for SQLite

**Important**: When writing SQL with `ON CONFLICT DO UPDATE SET`, always qualify column names with the table name (PostgreSQL requires this):
```sql
-- ✅ Correct
ON CONFLICT(symbol) DO UPDATE SET
  name = COALESCE(excluded.name, investment_symbols_cache.name)

-- ❌ Wrong (ambiguous on PostgreSQL)
ON CONFLICT(symbol) DO UPDATE SET
  name = COALESCE(excluded.name, name)
```

### Frontend

- **Templates**: Jinja2 in `dashboard/templates/`
- **CSS**: `landing.css` (shared pastel theme) + `style.css` (dashboard)
- **JS**: Vanilla JS, no build step. Each app has its own JS file
- **Dark mode**: Automatic via `prefers-color-scheme` media query

CSS custom properties are defined in `landing.css` — use them instead of hardcoding colors:
```css
var(--primary)        /* Main accent color */
var(--bg)             /* Background */
var(--text-primary)   /* Primary text */
var(--text-muted)     /* Secondary text */
var(--border)         /* Borders */
var(--success)        /* Green */
var(--danger)         /* Red */
```

## Conventions

### Language

- **UI text**: Spanish (the app serves Spanish-speaking users)
- **Code** (variables, functions, comments, commit messages): English

### Security

Every mutating endpoint must:
1. Check authentication (`@login_required` or `_auth_guard()`)
2. Validate CSRF token (automatic via `_check_csrf` middleware)
3. Validate/sanitize user input

### Adding a New Route

```python
# In the appropriate routes.py / blueprint:
@blueprint.route('/api/your-endpoint', methods=['POST'])
def your_endpoint():
    email, err = _auth_guard()
    if err:
        return err
    # ... your logic
    return jsonify({'status': 'ok', 'data': result})
```

### Adding a New App/Module

1. Create a new directory under `options_monitor_agent/` (e.g., `options_monitor_agent/newapp/`)
2. Add `__init__.py`, `routes.py`, `database.py`
3. Register the blueprint in `app.py`'s `create_app()`
4. Add templates and static files
5. Add the app card to `landing.html`

## Git Workflow

- **Branch**: `main` (auto-deploys to Render on push)
- **Commits**: Use conventional commit messages:
  - `feat: add CSV import to investments`
  - `fix: qualify column names for PostgreSQL`
  - `docs: update README with setup instructions`

## Deployment

Pushing to `main` triggers an automatic deploy on Render. The configuration is in `render.yaml`.

```bash
git add -A
git commit -m "feat: your change description"
git push origin main
```

## Need Help?

Open an issue on GitHub or contact the team via the contact form at [smallsmarttools.com](https://smallsmarttools.com).
