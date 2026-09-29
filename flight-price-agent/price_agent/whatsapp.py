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
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime

from .report import RouteReport, fmt_price, fmt_trip, top_trips

MAX_CHARS = 1000  # por mensaje (CallMeBot usa GET: URLs largas fallan)


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


MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre"]

PLACE_NAMES = {
    "FLN": "Florianópolis", "NVT": "Camboriú (Navegantes)", "GIG": "Río de Janeiro",
    "SDU": "Río de Janeiro", "CFB": "Búzios (Cabo Frio)", "VIX": "Vitória",
    "BPS": "Porto Seguro", "IOS": "Itacaré (Ilhéus)", "SSA": "Salvador",
    "AJU": "Aracaju", "MCZ": "Maceió", "REC": "Recife", "JPA": "João Pessoa",
    "NAT": "Natal", "FOR": "Fortaleza", "JJD": "Jericoacoara",
    "BUE": "Buenos Aires", "EZE": "Ezeiza", "AEP": "Aeroparque",
}


def place(code: str) -> str:
    return PLACE_NAMES.get(code, code)


def _change(pct: float | None) -> str:
    if pct is None or abs(pct) < 1:
        return ""
    return f" {'🔻' if pct < 0 else '🔺'}{abs(pct):.0f}%"


def _details(q) -> str:
    parts = [q.airline] if q.airline else []
    if q.stops is not None:
        parts.append("directo" if q.stops == 0 else f"{q.stops} escala{'s' if q.stops > 1 else ''}")
    return " · ".join(parts)


def _split(blocks: list[str], limit: int = MAX_CHARS) -> list[str]:
    """Agrupa bloques en mensajes de hasta `limit` caracteres sin cortar un bloque."""
    messages, current = [], ""
    for block in blocks:
        candidate = f"{current}\n\n{block}" if current else block
        if len(candidate) > limit and current:
            messages.append(current)
            current = block[:limit]
        else:
            current = candidate[:limit]
    if current:
        messages.append(current)
    return messages


def build_whatsapp_messages(
    reports: list[RouteReport], now: datetime, config=None, top: int = 10
) -> list[str]:
    """Reporte completo para WhatsApp, dividido en uno o más mensajes."""
    header = f"✈️ *Vuelos a Brasil · {now.strftime('%d/%m %H:%M')}*"
    if config is not None and config.fixed_dates:
        days = [str(d.day) for d in config.fixed_dates]
        days_txt = ", ".join(days[:-1]) + f" o {days[-1]}" if len(days) > 1 else days[0]
        header += f"\nIda {days_txt} de {MESES[config.fixed_dates[0].month - 1]}"
        if config.stay_range:
            header += f" · vuelta a las {config.stay_nights_min}–{config.stay_nights_max} noches"
    header += f"\n{len(reports)} destinos revisados · precios ida y vuelta, 1 adulto"

    best = top_trips(reports, top)
    if not best:
        return [header + "\n\nNo se encontraron precios en esta corrida."]

    blocks = [header]

    lines = [f"🏆 *Top {len(best)} viajes más baratos*"]
    for i, (r, q) in enumerate(best, 1):
        lines.append(
            f"{i}. *{place(r.route.destination)}* {fmt_price(q.price, q.currency)}"
            f"{_change(r.change_pct(q))}\n    {fmt_trip(q)}"
            + (f"\n    {_details(q)}" if _details(q) else "")
        )
    blocks.append("\n".join(lines))

    by_dest: dict[str, tuple[RouteReport, object]] = {}
    for r in reports:
        c = r.result.cheapest
        if c and (r.route.destination not in by_dest or c.price < by_dest[r.route.destination][1].price):
            by_dest[r.route.destination] = (r, c)
    lines = ["📍 *Mejor precio por destino*"]
    for dest, (r, q) in sorted(by_dest.items(), key=lambda kv: kv[1][1].price):
        prev = r.previous_cheapest
        pct = (q.price - prev) / prev * 100 if prev else None
        lines.append(
            f"• {place(dest)}: *{fmt_price(q.price, q.currency)}*{_change(pct)}"
            f" · {q.departure.strftime('%d/%m')}→{q.return_date.strftime('%d/%m') if q.return_date else ''}"
            + (f" · {q.airline.split(' (')[0]}" if q.airline else "")
        )
    blocks.append("\n".join(lines))

    extras = []
    alerts = [r for r in reports if r.below_alert]
    if alerts:
        extras.append("🔔 *Bajo tu umbral:* " + ", ".join(
            f"{place(r.route.destination)} {fmt_price(r.below_alert[0].price, r.below_alert[0].currency)}"
            for r in alerts
        ))
    lows = [r for r in reports if r.is_new_low]
    if lows:
        extras.append("📉 *Mínimo histórico:* " + ", ".join(place(r.route.destination) for r in lows))
    missing = [place(r.route.destination) for r in reports if not r.result.quotes]
    if missing:
        extras.append("❌ *Sin vuelos encontrados:* " + ", ".join(missing))
    cheapest = best[0][1]
    if cheapest.link:
        extras.append(f"🔗 Ver el más barato: {cheapest.link}")
    if extras:
        blocks.append("\n".join(extras))

    return _split(blocks)


def build_whatsapp_text(reports: list[RouteReport], run_date: date, top: int = 10) -> str:
    """Versión en un solo texto (para consola y tests)."""
    now = datetime.combine(run_date, datetime.min.time())
    return "\n\n".join(build_whatsapp_messages(reports, now, top=top))


def send_whatsapp(settings: WhatsAppSettings, text: str | list[str], pause_s: float = 3) -> None:
    messages = [text] if isinstance(text, str) else text
    for i, msg in enumerate(messages):
        if i:
            time.sleep(pause_s)  # CallMeBot limita mensajes seguidos
        if settings.provider == "twilio":
            _send_twilio(settings, msg)
        else:
            _send_callmebot(settings, msg)


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
