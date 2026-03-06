"""
Herramienta: Visualizacion en terminal con Rich
"""
import sys
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box
from datetime import datetime

# Console seguro para entornos sin TTY (WSGI, threads, etc.)
try:
    _has_tty = sys.stdout.isatty()
except Exception:
    _has_tty = False

import io
_console_out = sys.stderr if not _has_tty else sys.stdout
console = Console(file=_console_out, force_terminal=_has_tty, highlight=False)


def _safe_print(*args, **kwargs):
    """Wrapper seguro para console.print que no falla sin TTY."""
    try:
        console.print(*args, **kwargs)
    except Exception:
        pass


def display_analysis(analysis, chart_path=""):
    """Muestra el analisis completo en terminal."""
    timestamp = analysis.get("timestamp", datetime.now().isoformat())

    _safe_print()
    _safe_print(Panel(
        f"[bold cyan]📊 MONITOR DE OPCIONES - REPORTE[/bold cyan]\n"
        f"[dim]{timestamp}[/dim]\n"
        f"Sentimiento: [bold]{analysis.get('market_sentiment', 'N/A')}[/bold]\n"
        f"P/C Ratio: [bold]{analysis.get('overall_put_call_ratio', 'N/A')}[/bold]\n"
        f"Vol Total - Calls: {analysis.get('total_call_volume', 0):,} | Puts: {analysis.get('total_put_volume', 0):,}",
        box=box.DOUBLE_EDGE, border_style="cyan"
    ))

    # Main table
    table = Table(title="Resumen por Ticker", box=box.ROUNDED, show_lines=True, border_style="blue")
    table.add_column("Ticker", style="bold cyan", justify="center")
    table.add_column("Precio", style="green", justify="right")
    table.add_column("Call Vol", justify="right")
    table.add_column("Put Vol", justify="right")
    table.add_column("P/C Vol", justify="center")
    table.add_column("Call IV%", justify="right")
    table.add_column("Put IV%", justify="right")
    table.add_column("HV%", justify="right")
    table.add_column("IV Skew", justify="center")

    for ticker, data in analysis.get("summary", {}).items():
        pcr = data.get("put_call_ratio_volume", 0)
        pcr_s = f"[bold red]{pcr:.2f}🐻[/bold red]" if pcr > 1.2 else f"[bold green]{pcr:.2f}🐂[/bold green]" if pcr < 0.8 else f"[yellow]{pcr:.2f}[/yellow]"
        skew = data.get("iv_skew", 0)
        skew_s = f"[red]{skew:+.1f}[/red]" if skew > 5 else f"[green]{skew:+.1f}[/green]" if skew < -5 else f"{skew:+.1f}"
        table.add_row(ticker, f"${data.get('current_price', 0):,.2f}",
            f"{data.get('call_volume', 0):,}", f"{data.get('put_volume', 0):,}",
            pcr_s, f"{data.get('avg_call_iv', 0):.1f}%",
            f"{data.get('avg_put_iv', 0):.1f}%",
            f"{data.get('historical_volatility', 0):.1f}%", skew_s)
    _safe_print(table)

    # Greeks table
    g_table = Table(title="📐 Greeks Promedio", box=box.ROUNDED, border_style="magenta")
    g_table.add_column("Ticker", style="bold")
    g_table.add_column("Delta Calls", justify="right")
    g_table.add_column("Delta Puts", justify="right")
    g_table.add_column("Gamma", justify="right")
    g_table.add_column("Theta", justify="right")
    g_table.add_column("Vega", justify="right")

    for ticker, data in analysis.get("summary", {}).items():
        g = data.get("greeks", {})
        g_table.add_row(ticker,
            f"{g.get('avg_delta_calls', 0):.4f}",
            f"{g.get('avg_delta_puts', 0):.4f}",
            f"{g.get('avg_gamma', 0):.6f}",
            f"{g.get('avg_theta', 0):.4f}",
            f"{g.get('avg_vega', 0):.4f}")
    _safe_print(g_table)

    # Unusual activity
    unusual = analysis.get("unusual_activity", [])
    if unusual:
        u_table = Table(title="🔥 Actividad Inusual", box=box.ROUNDED, border_style="yellow")
        u_table.add_column("Ticker", style="bold")
        u_table.add_column("Tipo", justify="center")
        u_table.add_column("Strike", justify="right")
        u_table.add_column("Exp", justify="center")
        u_table.add_column("Volume", justify="right")
        u_table.add_column("OI", justify="right")
        u_table.add_column("Vol/OI", justify="center", style="bold red")
        u_table.add_column("IV%", justify="right")
        for u in unusual[:10]:
            u_table.add_row(u["ticker"],
            ("CALL" if u["type"] == "CALL" else "PUT"),
                f"${u['strike']:,.2f}", u["expiration"],
                f"{u['volume']:,}", f"{u['open_interest']:,}",
                f"{u['vol_oi_ratio']:.1f}x", f"{u['implied_volatility']:.1f}%")
        _safe_print(u_table)

    # Alerts
    alerts = analysis.get("alerts", [])
    if alerts:
        _safe_print()
        _safe_print("[bold red]⚠️ ALERTAS:[/bold red]")
        for alert in alerts:
            icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(alert.get("severity", "medium"), "🟡")
            _safe_print(f" {icon} [{alert.get('ticker', '')}] {alert.get('message', '')}")

    if chart_path:
        _safe_print(f"\n📈 Grafico: [bold blue]{chart_path}[/bold blue]")
