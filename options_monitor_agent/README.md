# 🤖 Options Monitor Agent v2.0

Autonomous options monitoring agent powered by **Claude AI**.

## Features
- 📊 Real-time options monitoring (calls & puts)
- 📐 Full Greeks (Delta, Gamma, Theta, Vega, Rho)
- 🧠 Claude AI analysis & interpretation
- 🗄️ SQLite persistent database
- 📧 Email notifications & alerts
- 📱 Telegram real-time alerts
- 🌐 Interactive web dashboard
- 📈 Signal backtesting
- 🔥 Smart money detection
- 🔄 Continuous monitoring

## Quick Start

```bash
python setup_project.py          # Generate project
cd options_monitor_agent
python -m venv venv
source venv/bin/activate          # Linux/Mac
pip install -r requirements.txt
cp .env.example .env              # Edit with your API key
python main.py

def create_project():
    """Crea toda la estructura del proyecto."""

    print("=" * 60)
    print("🤖 OPTIONS MONITOR AGENT v2.0 - Project Generator")
    print("=" * 60)

    # Crear directorio principal
    if os.path.exists(PROJECT_NAME):
        response = input(f"
⚠️  '{PROJECT_NAME}/' already exists. Overwrite? (y/n): ").strip().lower()
        if response != 'y':
            print("❌ Cancelled.")
            return

    # Directorios necesarios
    directories = [
        PROJECT_NAME,
        os.path.join(PROJECT_NAME, "tools"),
        os.path.join(PROJECT_NAME, "memory"),
        os.path.join(PROJECT_NAME, "dashboard"),
        os.path.join(PROJECT_NAME, "dashboard", "templates"),
        os.path.join(PROJECT_NAME, "dashboard", "static"),
        os.path.join(PROJECT_NAME, "reports"),
        os.path.join(PROJECT_NAME, "backtest_results"),
    ]

    print("
📁 Creating directories...")
    for d in directories:
        os.makedirs(d, exist_ok=True)
        print(f"   ✅ {d}/")

    # Escribir archivos
    print("
📝 Writing files...")
    total_lines = 0
    total_files = 0

    for filepath, content in FILES.items():
        full_path = os.path.join(PROJECT_NAME, filepath)

        # Asegurar que el directorio padre existe
        parent_dir = os.path.dirname(full_path)
        if parent_dir:
            os.makedirs(parent_dir, exist_ok=True)

        # Escribir archivo
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(content.strip() + "
")

        lines = len(content.strip().split("
"))
        total_lines += lines
        total_files += 1
        print(f"   ✅ {filepath} ({lines} lines)")

    # Crear .env desde .env.example
    env_example = os.path.join(PROJECT_NAME, ".env.example")
    env_file = os.path.join(PROJECT_NAME, ".env")
    if os.path.exists(env_example) and not os.path.exists(env_file):
        import shutil
        shutil.copy(env_example, env_file)
        print(f"   ✅ .env (copied from .env.example)")

    # Crear .gitignore
    gitignore_content = """# Python
__pycache__/
*.py[cod]
*$py.class
*.egg-info/
dist/
build/
venv/
.venv/

# Environment
.env

# Database
*.db
*.sqlite3

# Reports
reports/
backtest_results/

# Memory
memory/history.json
memory/*.db

# IDE
.vscode/
.idea/
*.swp
*.swo

# OS
.DS_Store
Thumbs.db
