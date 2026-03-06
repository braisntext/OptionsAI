"""
Herramienta: Notificaciones por Email
"""

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
from datetime import datetime
import os
from config import (EMAIL_ADDRESS, EMAIL_PASSWORD, EMAIL_SMTP_SERVER,
                    EMAIL_SMTP_PORT, EMAIL_RECIPIENTS, NOTIFICATION_CONFIG)


class EmailNotifier:
    def __init__(self):
        self.enabled = NOTIFICATION_CONFIG["enable_email"]
        self.sender = EMAIL_ADDRESS
        self.password = EMAIL_PASSWORD
        self.smtp_server = EMAIL_SMTP_SERVER
        self.smtp_port = EMAIL_SMTP_PORT
        self.recipients = [r.strip() for r in EMAIL_RECIPIENTS if r.strip()]

    def send_report(self, analysis, chart_path=""):
        if not self.enabled:
            print("  📧 Email deshabilitado")
            return False
        try:
            subject = f"📊 Options Report - {analysis.get('market_sentiment', 'N/A')} - {datetime.now().strftime('%Y-%m-%d %H:%M')}"
            html_body = self._build_html(analysis)
            msg = MIMEMultipart("related")
            msg["Subject"] = subject
            msg["From"] = self.sender
            msg["To"] = ", ".join(self.recipients)
            msg.attach(MIMEText(html_body, "html"))

            if chart_path and os.path.exists(chart_path):
                with open(chart_path, "rb") as f:
                    img = MIMEImage(f.read())
                    img.add_header("Content-Disposition", "attachment", filename=os.path.basename(chart_path))
                    msg.attach(img)

            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls()
                server.login(self.sender, self.password)
                server.sendmail(self.sender, self.recipients, msg.as_string())
            print(f"  📧 Email enviado a {len(self.recipients)} destinatarios")
            return True
        except Exception as e:
            print(f"  ❌ Error email: {e}")
            return False

    def send_alert(self, alerts):
        if not self.enabled or not alerts:
            return False
        high = [a for a in alerts if a.get("severity") == "high"]
        if not high:
            return False
        try:
            body = "<h2>🚨 Alertas Criticas</h2><ul>"
            for a in high:
                body += f"<li><strong>[{a['ticker']}]</strong> {a['message']}</li>"
            body += "</ul>"
            msg = MIMEText(body, "html")
            msg["Subject"] = f"🚨 OPTIONS ALERT - {len(high)} alertas"
            msg["From"] = self.sender
            msg["To"] = ", ".join(self.recipients)
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls()
                server.login(self.sender, self.password)
                server.sendmail(self.sender, self.recipients, msg.as_string())
            return True
        except Exception as e:
            print(f"  ❌ Error alert email: {e}")
            return False

    def _build_html(self, analysis):
        summary = analysis.get("summary", {})
        rows = ""
        for ticker, data in summary.items():
            pcr = data.get("put_call_ratio_volume", 0)
            c = "#e74c3c" if pcr > 1.2 else "#27ae60" if pcr < 0.8 else "#f39c12"
            rows += f"<tr><td><b>{ticker}</b></td><td>${data.get('current_price',0):,.2f}</td>"
            rows += f"<td>{data.get('call_volume',0):,}</td><td>{data.get('put_volume',0):,}</td>"
            rows += f"<td style=\"color:{c};font-weight:bold\">{pcr:.2f}</td>"
            rows += f"<td>{data.get('avg_call_iv',0):.1f}%</td><td>{data.get('avg_put_iv',0):.1f}%</td></tr>"

        return f"""<html><body style="font-family:Arial;background:#1a1a2e;color:#e0e0e0;padding:20px;">
        <div style="max-width:800px;margin:0 auto;background:#16213e;border-radius:10px;padding:20px;">
        <h1 style="color:#00d2ff;">📊 Options Monitor</h1>
        <p>Sentiment: <b>{analysis.get('market_sentiment','N/A')}</b> | P/C: <b>{analysis.get('overall_put_call_ratio','N/A')}</b></p>
        <table style="width:100%;border-collapse:collapse;color:#e0e0e0;">
        <tr style="background:#0f3460;"><th style="padding:8px;border:1px solid #333;">Ticker</th>
        <th style="padding:8px;border:1px solid #333;">Price</th><th style="padding:8px;border:1px solid #333;">Call Vol</th>
        <th style="padding:8px;border:1px solid #333;">Put Vol</th><th style="padding:8px;border:1px solid #333;">P/C</th>
        <th style="padding:8px;border:1px solid #333;">Call IV</th><th style="padding:8px;border:1px solid #333;">Put IV</th></tr>
        {rows}</table></div></body></html>"""
