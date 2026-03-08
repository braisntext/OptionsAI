"""
Agente Autonomo de Monitoreo de Opciones v2.0
"""

import json, time
from datetime import datetime
from anthropic import Anthropic
from config import ANTHROPIC_API_KEY, WATCHLIST, AGENT_CONFIG, NOTIFICATION_CONFIG
from tools.options_scraper import get_multiple_options
from tools.analysis_tool import analyze_options_data, generate_report_chart, generate_interactive_chart
from tools.greeks_calculator import GreeksCalculator
from tools.notification_tool import display_analysis, console, _safe_print
from tools.email_notifier import EmailNotifier
from tools.telegram_notifier import TelegramNotifier
from tools.backtester import Backtester
from tools.premium_spike_tool import save_snapshot, detect_spikes
from tools.ntfy_notifier import notify_bulk_spikes
try:
    from config import PREMIUM_SPIKE_THRESHOLD
except ImportError:
    PREMIUM_SPIKE_THRESHOLD = 0.25

from memory.memory_store import AgentMemory
from memory.database import OptionsDatabase


class OptionsMonitorAgent:
    def __init__(self):
        self.client = Anthropic(api_key=ANTHROPIC_API_KEY)
        self.conversation_history = []
        self.memory = AgentMemory()
        self.db = OptionsDatabase()
        self.greeks_calc = GreeksCalculator()
        self.email_notifier = EmailNotifier()
        self.telegram_notifier = TelegramNotifier()
        self.backtester = Backtester(database=self.db)
        self.cycle_count = 0
        self.last_analysis = None

        self.system_prompt = """Eres un agente autonomo experto en analisis de opciones financieras (puts y calls).
Tienes acceso a datos en tiempo real de opciones, Greeks (Delta, Gamma, Theta, Vega), volatilidad implicita e historica.

Tu trabajo es:
1. OBSERVAR: Recibir datos de opciones
2. ANALIZAR: Identificar patrones y anomalias
3. ALERTAR: Señalar cambios significativos
4. INTERPRETAR: Dar contexto usando Greeks y volatilidad
5. RECOMENDAR: Interpretaciones del sentimiento

Capacidades:
- Greeks: Delta (direccion), Gamma (aceleracion), Theta (time decay), Vega (sensibilidad IV)
- IV vs HV: Detectar divergencias
- IV Skew: Diferencia entre IV puts vs calls
- Smart Money: Volumen/OI ratio alto
- Put/Call Ratio: Analisis de sentimiento

IMPORTANTE: Cuando el mensaje del usuario incluya una seccion [User data context], UTILIZA esos datos 
concretos para responder de forma especifica. Basa tu analisis en las cifras reales proporcionadas 
(precios, IV, Put/Call ratio, alertas). No des respuestas genericas si tienes datos del usuario.

Reglas:
- Responde SIEMPRE en español
- Explica tu razonamiento paso a paso
- Se conciso pero preciso
- Usa emojis
- NUNCA des consejos de inversion directos
- Menciona riesgos y limitaciones
- Si el usuario pregunta sobre un ticker concreto, centra tu respuesta en ese ticker

Adapta el formato a la pregunta. Para preguntas concretas, responde directamente.
Para analisis generales usa:
1. 📊 RESUMEN EJECUTIVO
2. 🔍 TOP PICKS
3. 📐 GREEKS INSIGHTS
4. ⚠️ ALERTAS
5. 🔥 SMART MONEY
6. 🧠 INTERPRETACION
7. 📋 PROXIMOS PASOS"""

    def _call_claude(self, user_message):
        self.conversation_history.append({"role": "user", "content": user_message})
        try:
            response = self.client.messages.create(
                model=AGENT_CONFIG["model"],
                max_tokens=AGENT_CONFIG["max_tokens"],
                temperature=AGENT_CONFIG["temperature"],
                system=self.system_prompt,
                messages=self.conversation_history)
            msg = response.content[0].text
            self.conversation_history.append({"role": "assistant", "content": msg})
            if len(self.conversation_history) > 20:
                self.conversation_history = self.conversation_history[-16:]
            return msg
        except Exception as e:
            err = f"Error with Claude: {e}"
            _safe_print(f"[red]{err}[/red]")
            return err

    def run_cycle(self):
        start = time.time()
        self.cycle_count += 1
        result = {"cycle": self.cycle_count, "timestamp": datetime.now().isoformat(), "status": "running"}

        _safe_print(f"\n[bold white on blue] 🔄 CYCLE #{self.cycle_count} [/bold white on blue]")
        _safe_print(f"[dim]{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}[/dim]\n")

        # PHASE 1: OBSERVE
        _safe_print("[bold yellow]🔭 PHASE 1: OBSERVING...[/bold yellow]")
        _safe_print(f" Monitoring: {', '.join(WATCHLIST)}")
        raw_data = get_multiple_options(WATCHLIST)
        # PREMIUM SPIKE DETECTION
        all_spikes = []
        for ticker_data in raw_data:
            t = ticker_data.get("ticker", "")
            opts = ticker_data.get("options", [])
            if not opts or ticker_data.get("status") == "no_options":
                continue
            try:
                # Detect spikes vs last snapshot
                spikes = detect_spikes(t, opts, threshold=PREMIUM_SPIKE_THRESHOLD)
                if spikes:
                    all_spikes.extend(spikes)
                # Save current snapshot for next cycle
                save_snapshot(t, opts)
            except Exception as _se:
                print(f"[spike] Error for {t}: {_se}")
        if all_spikes:
            _safe_print(f"\n[bold red]⚡ {len(all_spikes)} PREMIUM SPIKE(S) DETECTED[/bold red]")
            for _sp in all_spikes:
                _safe_print(f"  {_sp['ticker']} {_sp['option_type']} ${_sp['strike']} exp {_sp['expiration']}: {_sp['pct_change']:+.1f}%")
            try:
                notify_bulk_spikes(all_spikes)
            except Exception as _ne:
                print(f"[notify] Error: {_ne}")

        ok = [d for d in raw_data if d.get("status") == "success"]
        fail = [d for d in raw_data if d.get("status") == "error"]
        no_opts = [d for d in raw_data if d.get("status") == "no_options"]
        _safe_print(f" Got: {len(ok)}//{len(WATCHLIST)} | Sin opciones: {len(no_opts)}")

        # PHASE 2: GREEKS
        _safe_print("\n[bold yellow]📐 PHASE 2: GREEKS...[/bold yellow]")
        for i, data in enumerate(raw_data):
            if data.get("status") == "success":
                raw_data[i] = self.greeks_calc.enrich_options_with_greeks(data)
                _safe_print(f" ✅ Greeks for {data['ticker']}")

        # PHASE 3: ANALYZE
        _safe_print("\n[bold yellow]📊 PHASE 3: ANALYZING...[/bold yellow]")
        analysis = analyze_options_data(raw_data)
        chart_path = generate_report_chart(analysis)
        try:
            generate_interactive_chart(analysis)
        except Exception:
            pass
        changes = self.memory.detect_significant_changes(analysis, AGENT_CONFIG["alert_threshold_percent"])
        if changes:
            _safe_print(f" 🔄 Changes detected: {len(changes)}")

        # PHASE 4: THINK
        _safe_print("\n[bold yellow]🧠 PHASE 4: THINKING (Claude)...[/bold yellow]")
        context = self._build_context(analysis, changes)
        claude_out = self._call_claude(context)

        # PHASE 5: REPORT
        _safe_print("\n[bold yellow]📢 PHASE 5: REPORTING...[/bold yellow]")
        display_analysis(analysis, chart_path)
        _safe_print(f"\n[bold magenta]{'='*60}[/bold magenta]")
        _safe_print(f"[bold magenta]🤖 AGENT ANALYSIS (Claude) - Cycle #{self.cycle_count}[/bold magenta]")
        _safe_print(f"[bold magenta]{'='*60}[/bold magenta]")
        _safe_print(claude_out)
        _safe_print(f"[bold magenta]{'='*60}[/bold magenta]\n")

        # PHASE 6: NOTIFY
        _safe_print("[bold yellow]📬 PHASE 6: NOTIFYING...[/bold yellow]")
        self.email_notifier.send_report(analysis, chart_path)
        self.telegram_notifier.send_report(analysis, chart_path)
        high_alerts = [a for a in analysis.get("alerts", []) if a.get("severity") == "high"]
        if high_alerts:
            self.email_notifier.send_alert(high_alerts)
            self.telegram_notifier.send_alert(high_alerts)

        # PHASE 7: STORE
        _safe_print("\n[bold yellow]💾 PHASE 7: STORING...[/bold yellow]")
        self.memory.store_analysis(analysis)
        self.db.save_snapshot(analysis)
        self.db.save_alerts(analysis.get("alerts", []))
        self.db.save_unusual_activity(analysis.get("unusual_activity", []))
        exec_time = time.time() - start
        self.db.save_agent_log(analysis, claude_out, exec_time)
        _safe_print(" ✅ Saved to SQLite + JSON")

        # PHASE 8: BACKTEST
        _safe_print("\n[bold yellow]📈 PHASE 8: BACKTESTING...[/bold yellow]")
        new_sigs = self.backtester.record_signals_from_analysis(analysis)
        if self.cycle_count % 5 == 0:
            self.backtester.generate_backtest_report()

        exec_time = time.time() - start
        result.update({"status": "completed", "tickers_analyzed": len(ok),
            "alerts": len(analysis.get("alerts", [])),
            "unusual": len(analysis.get("unusual_activity", [])),
            "changes": len(changes), "signals": len(new_sigs),
            "sentiment": analysis.get("market_sentiment", ""),
            "time": round(exec_time, 2)})
        self.last_analysis = analysis
        _safe_print(f"\n[bold green]✅ Cycle #{self.cycle_count} done in {exec_time:.1f}s[/bold green]\n")
        return result

    def _build_context(self, analysis, changes):
        hist = self.memory.get_history_summary()
        stats = self.db.get_database_stats()
        clean = {}
        for t, d in analysis.get("summary", {}).items():
            clean[t] = {k: v for k, v in d.items() if k not in ("calls_raw_df", "puts_raw_df")}
        ctx = f"""=== OPTIONS DATA ===
Cycle: #{self.cycle_count} | {analysis['timestamp']}
Tickers: {', '.join(analysis.get('tickers_analyzed', []))}

=== AGENT STATE ===
{hist}
DB: {json.dumps(stats)}

=== SUMMARY (with Greeks) ===
{json.dumps(clean, indent=2, default=str)}

=== ALERTS ({len(analysis.get('alerts', []))}) ===
{json.dumps(analysis.get('alerts', []), indent=2)}

=== UNUSUAL ACTIVITY ({len(analysis.get('unusual_activity', []))}) ===
{json.dumps(analysis.get('unusual_activity', []), indent=2)}

=== MARKET ===
Sentiment: {analysis.get('market_sentiment', 'N/A')}
P/C: {analysis.get('overall_put_call_ratio', 'N/A')}
Call Vol: {analysis.get('total_call_volume', 0):,} | Put Vol: {analysis.get('total_put_volume', 0):,}
"""
        if changes:
            ctx += f"\n=== CHANGES ===\n{json.dumps(changes, indent=2)}\n"
        ctx += "\nAnalyze this data. Focus on Greeks, IV vs HV, IV Skew, Smart Money, and changes."
        return ctx

    def interactive_mode(self):
        _safe_print("\n[bold green]💬 Interactive Mode[/bold green]")
        _safe_print("[dim]Commands: backtest, history <ticker>, stats, refresh, exit[/dim]\n")
        while True:
            try:
                inp = input("You > ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not inp:
                continue
            if inp.lower() in ("exit", "quit", "salir"):
                break
            if inp.lower() == "backtest":
                self.backtester.generate_backtest_report(); continue
            if inp.lower() == "stats":
                _safe_print(json.dumps(self.db.get_database_stats(), indent=2)); continue
            if inp.lower() == "refresh":
                self.run_cycle(); continue
            if inp.lower().startswith("history "):
                t = inp.split(" ")[1].upper()
                h = self.db.get_ticker_history(t, 7)
                for x in h[-10:]:
                    _safe_print(f" {x['timestamp']} | ${x['price']:,.2f} | P/C:{x['pcr_volume']:.2f} | IV:C{x['call_iv']:.1f}% P{x['put_iv']:.1f}%")
                continue
            response = self._call_claude(inp)
            _safe_print(f"\n🤖 [bold cyan]Agent:[/bold cyan]\n{response}\n")

    def cleanup(self):
        self.db.close()
        _safe_print("[dim]Resources released.[/dim]")
