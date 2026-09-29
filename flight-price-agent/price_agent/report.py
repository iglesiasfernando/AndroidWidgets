from __future__ import annotations

import html
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

from .models import Quote, RouteResult

DIAS = ["Lu", "Ma", "Mi", "Ju", "Vi", "Sa", "Do"]
DIAS_LARGO = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


@dataclass
class RouteReport:
    result: RouteResult
    previous: dict[date, float] = field(default_factory=dict)
    historical_min: Optional[float] = None

    @property
    def route(self):
        return self.result.route

    def change_pct(self, q: Quote) -> Optional[float]:
        prev = self.previous.get(q.departure)
        if not prev:
            return None
        return (q.price - prev) / prev * 100

    @property
    def previous_cheapest(self) -> Optional[float]:
        today_dates = {q.departure for q in self.result.quotes}
        vals = [p for d, p in self.previous.items() if d in today_dates]
        return min(vals) if vals else None

    @property
    def below_alert(self) -> list[Quote]:
        limit = self.result.alert_price
        if limit is None:
            return []
        return sorted(
            (q for q in self.result.quotes if q.price <= limit), key=lambda q: q.price
        )

    @property
    def is_new_low(self) -> bool:
        c = self.result.cheapest
        return (
            c is not None
            and self.historical_min is not None
            and c.price < self.historical_min
        )


def fmt_price(value: float, currency: str) -> str:
    return f"{currency} {value:,.0f}".replace(",", ".")


def fmt_date(d: date) -> str:
    return f"{DIAS[d.weekday()]} {d.strftime('%d/%m')}"


def fmt_change(pct: Optional[float]) -> str:
    if pct is None:
        return "–"
    arrow = "▼" if pct < 0 else "▲" if pct > 0 else "="
    return f"{arrow} {abs(pct):.1f}%"


def build_subject(reports: list[RouteReport], run_date: date) -> str:
    alerts = sum(1 for r in reports if r.below_alert)
    lows = [r for r in reports if r.result.cheapest]
    base = f"Precios de vuelos {run_date.strftime('%d/%m/%Y')}"
    if lows:
        best = min(lows, key=lambda r: r.result.cheapest.price)
        c = best.result.cheapest
        base += f" · mejor: {best.route.key} {fmt_price(c.price, c.currency)}"
    if alerts:
        base = f"🔔 {alerts} alerta(s) · " + base
    return base


# --------------------------------------------------------------------------- texto


def render_text(reports: list[RouteReport], run_date: date, top_n: int) -> str:
    lines = [f"Reporte de precios de vuelos - {run_date.isoformat()}", ""]
    for r in reports:
        res = r.result
        lines.append(f"== {res.route.key} ==")
        if res.error:
            lines.append(f"  Error: {res.error}")
        elif not res.quotes:
            lines.append("  Sin precios disponibles.")
        else:
            c = res.cheapest
            lines.append(
                f"  Más barato: {fmt_price(c.price, c.currency)} el {fmt_date(c.departure)}"
                f" ({c.airline or 's/d'})"
            )
            if r.previous_cheapest:
                lines.append(
                    f"  Ayer: {fmt_price(r.previous_cheapest, c.currency)}"
                )
            if res.alert_price is not None:
                lines.append(
                    f"  Alerta <= {fmt_price(res.alert_price, c.currency)}: "
                    f"{len(r.below_alert)} fecha(s)"
                )
            lines.append(f"  Top {top_n}:")
            for q in sorted(res.quotes, key=lambda q: q.price)[:top_n]:
                lines.append(
                    f"    {fmt_date(q.departure)}  {fmt_price(q.price, q.currency):>12}"
                    f"  {fmt_change(r.change_pct(q)):>9}  {q.airline}"
                )
        lines.append("")
    return "\n".join(lines)


# --------------------------------------------------------------------------- HTML

GREEN = "#1a7f37"
RED = "#cf222e"
MUTED = "#6e7781"


def _heat(price: float, lo: float, hi: float) -> str:
    """Verde (barato) -> amarillo -> rojo (caro)."""
    t = 0.0 if hi <= lo else (price - lo) / (hi - lo)
    stops = [(198, 239, 206), (255, 235, 156), (255, 199, 206)]
    a, b = (stops[0], stops[1]) if t < 0.5 else (stops[1], stops[2])
    u = t * 2 if t < 0.5 else (t - 0.5) * 2
    r, g, bl = (round(x + (y - x) * u) for x, y in zip(a, b))
    return f"rgb({r},{g},{bl})"


def _change_html(pct: Optional[float], threshold: float) -> str:
    if pct is None:
        return f'<span style="color:{MUTED}">–</span>'
    color = GREEN if pct <= -threshold else RED if pct >= threshold else MUTED
    return f'<span style="color:{color}">{fmt_change(pct)}</span>'


def _calendar(r: RouteReport) -> str:
    quotes = {q.departure: q for q in r.result.quotes}
    if not quotes:
        return ""
    prices = [q.price for q in quotes.values()]
    lo, hi = min(prices), max(prices)
    first, last = min(quotes), max(quotes)
    start = first - timedelta(days=first.weekday())
    head = "".join(
        f'<th style="padding:2px 4px;font-weight:normal;color:{MUTED}">{d}</th>'
        for d in DIAS
    )
    rows = []
    d = start
    while d <= last:
        cells = []
        for _ in range(7):
            q = quotes.get(d)
            if q:
                bold = "font-weight:bold;" if q.price == lo else ""
                cells.append(
                    f'<td style="padding:3px 4px;text-align:center;background:{_heat(q.price, lo, hi)};'
                    f'{bold}font-size:12px;border:1px solid #fff">'
                    f'<div style="font-size:10px;color:#444">{d.strftime("%d/%m")}</div>'
                    f"{f'{q.price:,.0f}'.replace(',', '.')}</td>"
                )
            else:
                cells.append(
                    f'<td style="padding:3px 4px;text-align:center;color:#bbb;font-size:10px;'
                    f'border:1px solid #fff">{d.strftime("%d/%m")}</td>'
                )
            d += timedelta(days=1)
        rows.append("<tr>" + "".join(cells) + "</tr>")
    return (
        '<table style="border-collapse:collapse;margin-top:8px">'
        f"<tr>{head}</tr>{''.join(rows)}</table>"
    )


def render_html(
    reports: list[RouteReport], run_date: date, top_n: int, change_threshold: float
) -> str:
    e = html.escape
    summary_rows = []
    for r in reports:
        res = r.result
        c = res.cheapest
        if not c:
            status = e(res.error) if res.error else "Sin precios"
            summary_rows.append(
                f'<tr><td style="padding:6px 8px"><b>{e(res.route.key)}</b></td>'
                f'<td colspan="4" style="padding:6px 8px;color:{MUTED}">{status}</td></tr>'
            )
            continue
        prev = r.previous_cheapest
        vs = _change_html((c.price - prev) / prev * 100 if prev else None, change_threshold)
        badges = []
        if r.below_alert:
            badges.append(
                f'<span style="background:{GREEN};color:#fff;padding:1px 6px;border-radius:8px;font-size:11px">'
                f"🔔 {len(r.below_alert)} bajo umbral</span>"
            )
        if r.is_new_low:
            badges.append(
                '<span style="background:#8250df;color:#fff;padding:1px 6px;border-radius:8px;font-size:11px">'
                "mínimo histórico</span>"
            )
        summary_rows.append(
            "<tr>"
            f'<td style="padding:6px 8px"><b>{e(res.route.key)}</b></td>'
            f'<td style="padding:6px 8px;text-align:right"><b>{fmt_price(c.price, c.currency)}</b></td>'
            f'<td style="padding:6px 8px">{fmt_date(c.departure)}</td>'
            f'<td style="padding:6px 8px">{vs}</td>'
            f'<td style="padding:6px 8px">{" ".join(badges)}</td>'
            "</tr>"
        )

    sections = []
    for r in reports:
        res = r.result
        if not res.quotes:
            continue
        top_rows = []
        for q in sorted(res.quotes, key=lambda q: q.price)[:top_n]:
            ret = f" → {q.return_date.strftime('%d/%m')}" if q.return_date else ""
            stops = (
                "directo" if q.stops == 0 else f"{q.stops} escala(s)"
                if q.stops is not None else ""
            )
            price = fmt_price(q.price, q.currency)
            if q.link:
                price = f'<a href="{e(q.link)}" style="color:#0969da">{price}</a>'
            alert = (
                " 🔔" if res.alert_price is not None and q.price <= res.alert_price else ""
            )
            top_rows.append(
                "<tr>"
                f'<td style="padding:4px 8px">{DIAS_LARGO[q.departure.weekday()]} '
                f'{q.departure.strftime("%d/%m")}{ret}</td>'
                f'<td style="padding:4px 8px;text-align:right">{price}{alert}</td>'
                f'<td style="padding:4px 8px">{_change_html(r.change_pct(q), change_threshold)}</td>'
                f'<td style="padding:4px 8px">{e(q.airline)}</td>'
                f'<td style="padding:4px 8px;color:{MUTED}">{stops}</td>'
                "</tr>"
            )
        umbral = (
            f' · umbral {fmt_price(res.alert_price, res.quotes[0].currency)}'
            if res.alert_price is not None
            else ""
        )
        sections.append(
            f'<h3 style="margin:24px 0 4px">{e(res.route.origin)} ✈ {e(res.route.destination)}'
            f'<span style="font-weight:normal;font-size:13px;color:{MUTED}">'
            f" · {len(res.quotes)} días con precio{umbral}</span></h3>"
            f'<table style="border-collapse:collapse;font-size:13px">{"".join(top_rows)}</table>'
            f"{_calendar(r)}"
        )

    return f"""<!doctype html>
<html><body style="font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;color:#1f2328;max-width:720px;margin:0 auto;padding:16px">
<h2 style="margin:0 0 4px">Reporte diario de precios de vuelos</h2>
<div style="color:{MUTED};font-size:13px;margin-bottom:16px">{run_date.strftime('%d/%m/%Y')}</div>
<table style="border-collapse:collapse;font-size:14px;width:100%">
<tr style="background:#f6f8fa;text-align:left">
<th style="padding:6px 8px">Ruta</th><th style="padding:6px 8px;text-align:right">Mínimo</th>
<th style="padding:6px 8px">Fecha</th><th style="padding:6px 8px">vs. ayer</th><th style="padding:6px 8px"></th></tr>
{''.join(summary_rows)}
</table>
{''.join(sections)}
<p style="color:{MUTED};font-size:11px;margin-top:32px">Los precios son el valor más bajo encontrado para cada fecha de salida
y pueden cambiar. "vs. ayer" compara contra el precio de la misma fecha en la corrida anterior.</p>
</body></html>"""
