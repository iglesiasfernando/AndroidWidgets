"""Envío del resumen por WhatsApp.

Proveedores soportados (se elige con WHATSAPP_PROVIDER):
- callmebot (default): gratis para uso personal. Requiere activar el número una vez
  (ver README) para obtener la API key.
- twilio: WhatsApp Business vía Twilio (pago, o sandbox para pruebas).
"""

from __future__ import annotations

import base64
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date

from .report import RouteReport, fmt_price, fmt_trip, top_trips

MAX_CHARS = 1500


class WhatsAppError(RuntimeError):
    pass


@dataclass
class WhatsAppSettings:
    provider: str
    phone: str
    apikey: str = ""
    twilio_sid: str = ""
    twilio_token: str = ""
    twilio_from: str = ""

    @classmethod
    def from_env(cls) -> "WhatsAppSettings | None":
        """None si WhatsApp no está configurado (WHATSAPP_PHONE vacío)."""
        phone = os.environ.get("WHATSAPP_PHONE", "").strip()
        if not phone:
            return None
        phone = "+" + re.sub(r"\D", "", phone)
        provider = os.environ.get("WHATSAPP_PROVIDER", "callmebot").strip().lower() or "callmebot"
        s = cls(
            provider=provider,
            phone=phone,
            apikey=os.environ.get("CALLMEBOT_APIKEY", ""),
            twilio_sid=os.environ.get("TWILIO_ACCOUNT_SID", ""),
            twilio_token=os.environ.get("TWILIO_AUTH_TOKEN", ""),
            twilio_from=os.environ.get("TWILIO_WHATSAPP_FROM", ""),
        )
        if provider == "callmebot" and not s.apikey:
            raise WhatsAppError("Falta CALLMEBOT_APIKEY")
        if provider == "twilio" and not (s.twilio_sid and s.twilio_token and s.twilio_from):
            raise WhatsAppError(
                "Faltan TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN o TWILIO_WHATSAPP_FROM"
            )
        if provider not in {"callmebot", "twilio"}:
            raise WhatsAppError(f"WHATSAPP_PROVIDER desconocido: {provider}")
        return s


def build_whatsapp_text(reports: list[RouteReport], run_date: date, top: int = 5) -> str:
    lines = [f"✈️ *Vuelos {run_date.strftime('%d/%m/%Y')}*"]
    best = top_trips(reports, top)
    if not best:
        lines.append("No se encontraron precios en esta corrida.")
        return "\n".join(lines)

    lines.append("")
    lines.append("*Más baratos:*")
    for i, (r, q) in enumerate(best, 1):
        pct = r.change_pct(q)
        change = f" ({'▼' if pct < 0 else '▲'}{abs(pct):.0f}%)" if pct and abs(pct) >= 1 else ""
        lines.append(
            f"{i}. {r.route.origin}→{r.route.destination} {fmt_price(q.price, q.currency)}{change}"
            f"\n   {fmt_trip(q)}"
        )

    alerts = [r for r in reports if r.below_alert]
    if alerts:
        lines.append("")
        lines.append("🔔 *Bajo umbral:* " + ", ".join(
            f"{r.route.key} {fmt_price(r.below_alert[0].price, r.below_alert[0].currency)}"
            for r in alerts
        ))

    lines.append("")
    lines.append("Detalle completo en el mail.")
    text = "\n".join(lines)
    return text if len(text) <= MAX_CHARS else text[: MAX_CHARS - 1] + "…"


def send_whatsapp(settings: WhatsAppSettings, text: str) -> None:
    if settings.provider == "twilio":
        _send_twilio(settings, text)
    else:
        _send_callmebot(settings, text)


def _send_callmebot(s: WhatsAppSettings, text: str) -> None:
    query = urllib.parse.urlencode({"phone": s.phone, "text": text, "apikey": s.apikey})
    url = f"https://api.callmebot.com/whatsapp.php?{query}"
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            body = resp.read().decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError) as e:
        raise WhatsAppError(f"CallMeBot: {e}") from e
    # CallMeBot responde 200 incluso con errores; el texto indica el resultado.
    if "error" in body.lower() and "queued" not in body.lower():
        raise WhatsAppError(f"CallMeBot: {re.sub(r'<[^>]+>', ' ', body)[:200].strip()}")


def _send_twilio(s: WhatsAppSettings, text: str) -> None:
    url = f"https://api.twilio.com/2010-04-01/Accounts/{s.twilio_sid}/Messages.json"
    sender = s.twilio_from if s.twilio_from.startswith("whatsapp:") else f"whatsapp:{s.twilio_from}"
    data = urllib.parse.urlencode(
        {"From": sender, "To": f"whatsapp:{s.phone}", "Body": text}
    ).encode()
    auth = base64.b64encode(f"{s.twilio_sid}:{s.twilio_token}".encode()).decode()
    req = urllib.request.Request(url, data=data, headers={"Authorization": f"Basic {auth}"})
    try:
        with urllib.request.urlopen(req, timeout=30):
            pass
    except urllib.error.HTTPError as e:
        raise WhatsAppError(f"Twilio HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:200]}") from e
    except (urllib.error.URLError, TimeoutError) as e:
        raise WhatsAppError(f"Twilio: {e}") from e
