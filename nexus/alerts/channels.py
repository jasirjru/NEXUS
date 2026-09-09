"""Alert delivery channels. Each channel degrades gracefully when unconfigured:
dashboard always works (DB-backed); email/webhook/slack no-op with a logged
warning if their settings are missing - alerts are never lost, only marked.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from nexus.config import settings
from nexus.core.logging_setup import get_logger

log = get_logger("nexus.alerts")


@dataclass
class OutgoingAlert:
    title: str
    body: str
    severity: str = "warning"
    entity_id: str | None = None
    payload: dict | None = None


class DashboardChannel:
    name = "dashboard"

    def send(self, alert: OutgoingAlert) -> bool:
        # dashboard alerts are persisted by the alerts service itself
        return True


class EmailChannel:
    name = "email"

    def send(self, alert: OutgoingAlert) -> bool:
        if not (settings.smtp_host and settings.alert_email_to):
            log.warning("email channel unconfigured; alert '%s' not emailed", alert.title)
            return False
        import smtplib
        from email.mime.text import MIMEText

        msg = MIMEText(alert.body)
        msg["Subject"] = f"[NEXUS][{alert.severity.upper()}] {alert.title}"
        msg["From"] = settings.smtp_user or "nexus@localhost"
        msg["To"] = settings.alert_email_to
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as smtp:
            if settings.smtp_user:
                smtp.starttls()
                smtp.login(settings.smtp_user, settings.smtp_password or "")
            smtp.send_message(msg)
        return True


class WebhookChannel:
    name = "webhook"

    def send(self, alert: OutgoingAlert, url: str | None = None) -> bool:
        target = url or None
        if target is None:
            log.warning("webhook channel: no url provided for alert '%s'", alert.title)
            return False
        try:
            resp = httpx.post(
                target,
                json={
                    "title": alert.title,
                    "body": alert.body,
                    "severity": alert.severity,
                    "entity_id": alert.entity_id,
                    "payload": alert.payload or {},
                },
                timeout=10,
            )
            return resp.status_code < 300
        except httpx.HTTPError as e:
            log.error("webhook delivery failed: %s", e)
            return False


class SlackChannel:
    name = "slack"

    def send(self, alert: OutgoingAlert) -> bool:
        if not settings.slack_webhook_url:
            log.warning("slack channel unconfigured; alert '%s' not sent", alert.title)
            return False
        emoji = {"critical": ":rotating_light:", "warning": ":warning:"}.get(alert.severity, ":information_source:")
        try:
            resp = httpx.post(
                settings.slack_webhook_url,
                json={"text": f"{emoji} *{alert.title}*\n{alert.body}"},
                timeout=10,
            )
            return resp.status_code < 300
        except httpx.HTTPError as e:
            log.error("slack delivery failed: %s", e)
            return False


CHANNELS = {
    "dashboard": DashboardChannel(),
    "email": EmailChannel(),
    "webhook": WebhookChannel(),
    "slack": SlackChannel(),
}
