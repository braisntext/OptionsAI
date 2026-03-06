"""
Herramienta: Notificaciones por Telegram
"""

import asyncio
import aiohttp
from datetime import datetime
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, NOTIFICATION_CONFIG


class TelegramNotifier:
    def __init__(self):
        self.enabled = NOTIFICATION_CONFIG["enable_telegram"]
        self.token = TELEGRAM_BOT_TOKEN
        self.chat_id = TELEGRAM_CHAT_ID
        self.base_url = f"https://api.telegram.org/bot{self.token}"

    def send_report(self, analysis, chart_path=""):
        if not self.enabled:
            print("  📱 Telegram deshabilitado")
            return False
        try:
            message = self._format(analysis)
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(self._send_message(message))
            if chart_path:
                loop.run_until_complete(self._send_photo(chart_path))
            loop.close()
            print("  📱 Reporte Telegram enviado")
            return result
        except Exception as e:
            print(f"  ❌ Error Telegram: {e}")
            return False

    def send_alert(self, alerts):
        if not self.enabled or not alerts:
            return False
        high = [a for a in alerts if a.get("severity") in ("high", "medium")]
        if not high:
            return False
        try:
            msg = "🚨 *ALERTAS*\n\n"
            for a in high:
                icon = "🔴" if a.get("severity") == "high" else "🟡"
                msg += f"{icon} *[{a['ticker']}]* {a['message']}\n"
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self._send_message(msg))
            loop.close()
            return True
        except Exception as e:
            print(f"  ❌ Telegram alert error: {e}")
            return False

    async def _send_message(self, text):
        url = f"{self.base_url}/sendMessage"
        payload = {"chat_id": self.chat_id, "text": text[:4096], "parse_mode": "Markdown"}
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as resp:
                return resp.status == 200

    async def _send_photo(self, path):
        url = f"{self.base_url}/sendPhoto"
        async with aiohttp.ClientSession() as session:
            with open(path, "rb") as photo:
                data = aiohttp.FormData()
                data.add_field("chat_id", self.chat_id)
                data.add_field("photo", photo, filename="report.png")
                async with session.post(url, data=data) as resp:
                    return resp.status == 200

    def _format(self, analysis):
        summary = analysis.get("summary", {})
        msg = f"📊 *OPTIONS MONITOR*\n{'─'*30}\n"
        msg += f"Sentiment: *{analysis.get('market_sentiment', 'N/A')}*\nP/C: *{analysis.get('overall_put_call_ratio', 0)}*\n\n"
        for ticker, data in summary.items():
            pcr = data.get("put_call_ratio_volume", 0)
            e = "🐻" if pcr > 1.2 else "🐂" if pcr < 0.8 else "😐"
            msg += f"*{ticker}* ${data.get('current_price',0):,.2f} {e}\n"
            msg += f"  P/C:{pcr:.2f} IV:C{data.get('avg_call_iv',0):.0f}% P{data.get('avg_put_iv',0):.0f}%\n\n"
        alerts = analysis.get("alerts", [])
        if alerts:
            msg += "⚠️ *ALERTAS:*\n"
            for a in alerts[:5]:
                msg += f"  [{a['ticker']}] {a['message']}\n"
        msg += f"\n⏰ {datetime.now().strftime('%H:%M')}"
        return msg
