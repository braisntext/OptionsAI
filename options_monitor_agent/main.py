"""
🚀 Options Monitor Agent v2.0 - Main Entry Point
"""

import schedule, time, sys, threading
from rich.console import Console
from agent import OptionsMonitorAgent
from config import AGENT_CONFIG, WATCHLIST, DASHBOARD_CONFIG, NOTIFICATION_CONFIG

console = Console()


def show_banner():
    console.print("\n[bold cyan]╔══════════════════════════════════════════════════╗[/bold cyan]")
    console.print("[bold cyan]║[/bold cyan]   [bold white]🤖 OPTIONS MONITOR AGENT v2.0[/bold white]                   [bold cyan]║[/bold cyan]")
    console.print("[bold cyan]║[/bold cyan]   [dim]Autonomous Options Analytics[/dim]                    [bold cyan]║[/bold cyan]")
    console.print("[bold cyan]║[/bold cyan]   [dim]Powered by Claude AI[/dim]                            [bold cyan]║[/bold cyan]")
    console.print("[bold cyan]╚══════════════════════════════════════════════════╝[/bold cyan]")
    console.print(f"\n  📋 Watchlist ({len(WATCHLIST)}): {', '.join(WATCHLIST)}")
    console.print(f"  ⏱️  Interval: {AGENT_CONFIG['monitor_interval_minutes']}min | 🧠 {AGENT_CONFIG['model']}")
    console.print(f"  📐 Greeks: ✅ | 🗄️ SQLite: ✅ | 📧 Email: {'✅' if NOTIFICATION_CONFIG['enable_email'] else '❌'} | 📱 Telegram: {'✅' if NOTIFICATION_CONFIG['enable_telegram'] else '❌'}")
    console.print(f"  🌐 Dashboard: port {DASHBOARD_CONFIG['port']}\n")


def run_dashboard(agent):
    try:
        from dashboard.app import create_app
        app, socketio = create_app(database=agent.db, agent=agent)
        console.print(f"  🌐 Dashboard: http://localhost:{DASHBOARD_CONFIG['port']}")
        socketio.run(app, host=DASHBOARD_CONFIG["host"], port=DASHBOARD_CONFIG["port"],
                     debug=False, allow_unsafe_werkzeug=True, use_reloader=False)
    except Exception as e:
        console.print(f"  [red]Dashboard error: {e}[/red]")


def main():
    show_banner()
    agent = OptionsMonitorAgent()

    if len(sys.argv) > 1:
        mode = sys.argv[1]
    else:
        console.print("[bold]Select mode:[/bold]")
        console.print("  [cyan]1)[/cyan] 🔄 Continuous monitoring")
        console.print("  [cyan]2)[/cyan] 📊 Single analysis")
        console.print("  [cyan]3)[/cyan] 💬 Interactive")
        console.print("  [cyan]4)[/cyan] 🌐 Dashboard + Monitor")
        console.print("  [cyan]5)[/cyan] 🌐 Dashboard only")
        console.print("  [cyan]6)[/cyan] 📈 Backtest report")
        console.print("  [cyan]7)[/cyan] 🔄+💬 Analysis + Interactive\n")
        mode = input("Choice (1-7): ").strip()

    try:
        if mode == "1":
            agent.run_cycle()
            schedule.every(AGENT_CONFIG["monitor_interval_minutes"]).minutes.do(agent.run_cycle)
            console.print(f"[dim]Next in {AGENT_CONFIG['monitor_interval_minutes']}min. Ctrl+C to stop.[/dim]")
            while True: schedule.run_pending(); time.sleep(1)
        elif mode == "2":
            agent.run_cycle()
        elif mode == "3":
            agent.run_cycle(); agent.interactive_mode()
        elif mode == "4":
            threading.Thread(target=run_dashboard, args=(agent,), daemon=True).start()
            time.sleep(2); agent.run_cycle()
            schedule.every(AGENT_CONFIG["monitor_interval_minutes"]).minutes.do(agent.run_cycle)
            console.print(f"\n[bold]🌐 http://localhost:{DASHBOARD_CONFIG['port']}[/bold]")
            while True: schedule.run_pending(); time.sleep(1)
        elif mode == "5":
            run_dashboard(agent)
        elif mode == "6":
            agent.backtester.generate_backtest_report()
        elif mode == "7":
            agent.run_cycle(); agent.interactive_mode()
        else:
            console.print("[red]Invalid option[/red]")
    except KeyboardInterrupt:
        console.print("\n[yellow]⛔ Stopped.[/yellow]")
    finally:
        agent.cleanup()


if __name__ == "__main__":
    main()
