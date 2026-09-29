from __future__ import annotations

import html
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

from .config import Config
from .models import Quote, RouteResult
from .providers.base import trip_key

DIAS = ["Lu", "Ma", "Mi", "Ju", "Vi", "Sa", "Do"]
DIAS_LARGO = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


@dataclass
class RouteReport:
    result: RouteResult
    previous: dict[tuple, float] = field(default_factory=dict)
    historical_min: Optional[float] = None

    @property
    def route(self):
        return self.result.route

    def change_pct(self, q: Quote) -> Optional[float]:
        prev = self.previous.get(trip_key(q))
        if not prev:
            return None
        return (q.price - prev) / prev * 100

    @property
    def previous_cheapest(self) -> Optional[float]:
        today_trips = {trip_key(q) for q in self.result.quotes}
        vals = [p for k, p in self.previous.items() if k in today_trips]
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


def fmt_num(value: float) -> str:
    return f"{value:,.0f}".replace(",", ".")


def fmt_date(d: date) -> str:
    return f"{DIAS[d.weekday()]} {d.strftime('%d/%m')}"


def fmt_trip(q: Quote) -> str:
    if not q.return_date:
        return fmt_date(q.departure)
    nights = (q.return_date - q.departure).days
    return f"{fmt_date(q.departure)} → {fmt_date(q.return_date)} ({nights}n)"


def fmt_stops(stops: Optional[int]) -> str:
    if stops is None:
        return ""
    return "directo" if stops == 0 else f"{stops} escala(s)"


def fmt_change(pct: Optional[float]) -> str:
    if pct is None:
        return "–"
    arrow = "▼" if pct < 0 else "▲" if pct > 0 else "="
    return f"{arrow} {abs(pct):.1f}%"


def sorted_reports(reports: list[RouteReport]) -> list[RouteReport]:
    """Rutas con precio primero, de la más barata a la más cara."""
    return sorted(
        reports,
        key=lambda r: (r.result.cheapest is None, r.result.cheapest.price if r.result.cheapest else 0),
    )


def top_trips(reports: list[RouteReport], n: int) -> list[tuple[RouteReport, Quote]]:
    pairs = [(r, q) for r in reports for q in r.result.quotes]
    return sorted(pairs, key=lambda p: p[1].price)[:n]


def build_subject(reports: list[RouteReport], run_date: date) -> str:
    alerts = sum(1 for r in reports if r.below_alert)
    best = top_trips(reports, 1)
    base = f"Precios de vuelos {run_date.strftime('%d/%m/%Y')}"
    if best:
        r, q = best[0]
        base += f" · mejor: {r.route.key} {fmt_price(q.price, q.currency)}"
    if alerts:
        base = f"🔔 {alerts} alerta(s) · " + base
    return base


# --------------------------------------------------------------------------- texto


def render_text(reports: list[RouteReport], run_date: date, config: Config) -> str:
    lines = [f"Reporte de precios de vuelos - {run_date.isoformat()}", ""]
    best = top_trips(reports, config.top_overall)
    if best:
        lines.append(f"Top {len(best)} viajes más baratos:")
        for r, q in best:
            lines.append(
                f"  {r.route.key:8} {fmt_trip(q):34} {fmt_price(q.price, q.currency):>11}"
                f"  {fmt_change(r.change_pct(q)):>9}  {q.airline} {fmt_stops(q.stops)}"
            )
        lines.append("")

    no_price = []
    for r in sorted_reports(reports):
        res = r.result
        if not res.quotes:
            no_price.append(f"{res.route.key}" + (f" (error: {res.error})" if res.error else ""))
            continue
        c = res.cheapest
        lines.append(f"== {res.route.key} ==")
        lines.append(f"  Más barato: {fmt_price(c.price, c.currency)} · {fmt_trip(c)} ({c.airline or 's/d'})")
        if r.previous_cheapest:
            lines.append(f"  Corrida anterior: {fmt_price(r.previous_cheapest, c.currency)}")
        if res.alert_price is not None:
            lines.append(
                f"  Alerta <= {fmt_price(res.alert_price, c.currency)}: {len(r.below_alert)} viaje(s)"
            )
        for q in sorted(res.quotes, key=lambda q: q.price)[: config.top_n]:
            lines.append(
                f"    {fmt_trip(q):34} {fmt_price(q.price, q.currency):>11}"
                f"  {fmt_change(r.change_pct(q)):>9}  {q.airline}"
            )
        lines.append("")
    if no_price:
        lines.append("Sin precios: " + ", ".join(no_price))
    return "\n".join(lines)


# --------------------------------------------------------------------------- HTML

GREEN = "#1a7f37"
RED = "#cf222e"
MUTED = "#6e7781"
TD = "padding:4px 8px"


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


def _price_link(q: Quote) -> str:
    price = fmt_price(q.price, q.currency)
    if q.link:
        return f'<a href="{html.escape(q.link)}" style="color:#0969da">{price}</a>'
    return price


def _cell(content: str, bg: str = "", bold: bool = False) -> str:
    style = "padding:4px 6px;text-align:center;font-size:12px;border:1px solid #fff;"
    if bg:
        style += f"background:{bg};"
    if bold:
        style += "font-weight:bold;"
    return f'<td style="{style}">{content}</td>'


def _stay_matrix(r: RouteReport) -> str:
    """Tabla fecha de ida × noches de estadía."""
    quotes = {trip_key(q): q for q in r.result.quotes}
    deps = sorted({q.departure for q in r.result.quotes})
    nights = sorted({(q.return_date - q.departure).days for q in r.result.quotes})
    prices = [q.price for q in quotes.values()]
    lo, hi = min(prices), max(prices)
    head = f'<th style="{TD};color:{MUTED};font-weight:normal">Ida \\ Noches</th>' + "".join(
        f'<th style="{TD};color:{MUTED};font-weight:normal">{n}</th>' for n in nights
    )
    rows = []
    for d in deps:
        cells = [f'<td style="{TD};font-size:12px">{fmt_date(d)}</td>']
        for n in nights:
            q = quotes.get((d, d + timedelta(days=n)))
            if q:
                cells.append(_cell(fmt_num(q.price), _heat(q.price, lo, hi), q.price == lo))
            else:
                cells.append(_cell('<span style="color:#bbb">–</span>'))
        rows.append("<tr>" + "".join(cells) + "</tr>")
    return (
        '<table style="border-collapse:collapse;margin-top:8px">'
        f"<tr>{head}</tr>{''.join(rows)}</table>"
    )


def _calendar(r: RouteReport) -> str:
    """Calendario semanal con el precio mínimo de cada fecha de ida."""
    by_day: dict[date, float] = {}
    for q in r.result.quotes:
        by_day[q.departure] = min(q.price, by_day.get(q.departure, q.price))
    lo, hi = min(by_day.values()), max(by_day.values())
    first, last = min(by_day), max(by_day)
    head = "".join(
        f'<th style="padding:2px 4px;font-weight:normal;color:{MUTED}">{d}</th>' for d in DIAS
    )
    rows = []
    d = first - timedelta(days=first.weekday())
    while d <= last:
        cells = []
        for _ in range(7):
            label = f'<div style="font-size:10px;color:#444">{d.strftime("%d/%m")}</div>'
            price = by_day.get(d)
            if price is not None:
                cells.append(_cell(label + fmt_num(price), _heat(price, lo, hi), price == lo))
            else:
                cells.append(_cell(f'<span style="color:#bbb;font-size:10px">{d.strftime("%d/%m")}</span>'))
            d += timedelta(days=1)
        rows.append("<tr>" + "".join(cells) + "</tr>")
    return (
        '<table style="border-collapse:collapse;margin-top:8px">'
        f"<tr>{head}</tr>{''.join(rows)}</table>"
    )


def _grid(r: RouteReport) -> str:
    quotes = r.result.quotes
    if not quotes:
        return ""
    round_trip = all(q.return_date for q in quotes)
    n_deps = len({q.departure for q in quotes})
    if round_trip and n_deps <= 10:
        return _stay_matrix(r)
    return _calendar(r)


def render_html(reports: list[RouteReport], run_date: date, config: Config) -> str:
    e = html.escape
    threshold = config.change_threshold_pct
    ordered = sorted_reports(reports)

    # Top global
    top_rows = []
    for r, q in top_trips(reports, config.top_overall):
        top_rows.append(
            "<tr>"
            f'<td style="{TD}"><b>{e(r.route.origin)} → {e(r.route.destination)}</b></td>'
            f'<td style="{TD}">{fmt_trip(q)}</td>'
            f'<td style="{TD};text-align:right"><b>{_price_link(q)}</b></td>'
            f'<td style="{TD}">{_change_html(r.change_pct(q), threshold)}</td>'
            f'<td style="{TD}">{e(q.airline)}</td>'
            f'<td style="{TD};color:{MUTED}">{fmt_stops(q.stops)}</td>'
            "</tr>"
        )
    top_html = (
        f'<h3 style="margin:16px 0 4px">🏆 Los {len(top_rows)} viajes más baratos</h3>'
        f'<table style="border-collapse:collapse;font-size:13px;width:100%">{"".join(top_rows)}</table>'
        if top_rows
        else f'<p style="color:{MUTED}">No se encontraron precios para ninguna ruta.</p>'
    )

    # Mejor precio por destino
    best_dest: dict[str, tuple[RouteReport, Quote]] = {}
    for r in reports:
        c = r.result.cheapest
        d = r.route.destination
        if c and (d not in best_dest or c.price < best_dest[d][1].price):
            best_dest[d] = (r, c)
    dest_rows = [
        "<tr>"
        f'<td style="{TD}"><b>{e(d)}</b></td>'
        f'<td style="{TD};text-align:right"><b>{_price_link(q)}</b></td>'
        f'<td style="{TD}">desde {e(r.route.origin)}</td>'
        f'<td style="{TD}">{fmt_trip(q)}</td>'
        f'<td style="{TD}">{e(q.airline)}</td>'
        "</tr>"
        for d, (r, q) in sorted(best_dest.items(), key=lambda kv: kv[1][1].price)
    ]
    dest_html = (
        f'<h3 style="margin:24px 0 4px">📍 Mejor precio por destino</h3>'
        f'<table style="border-collapse:collapse;font-size:13px;width:100%">{"".join(dest_rows)}</table>'
        if len(best_dest) > 1
        else ""
    )

    # Resumen por ruta
    summary_rows, no_price = [], []
    for r in ordered:
        res = r.result
        c = res.cheapest
        if not c:
            no_price.append(res.route.key + (" ⚠" if res.error else ""))
            continue
        prev = r.previous_cheapest
        vs = _change_html((c.price - prev) / prev * 100 if prev else None, threshold)
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
            f'<td style="{TD}"><b>{e(res.route.key)}</b></td>'
            f'<td style="{TD};text-align:right"><b>{fmt_price(c.price, c.currency)}</b></td>'
            f'<td style="{TD}">{fmt_trip(c)}</td>'
            f'<td style="{TD}">{vs}</td>'
            f'<td style="{TD}">{" ".join(badges)}</td>'
            "</tr>"
        )
    no_price_html = (
        f'<p style="color:{MUTED};font-size:12px">Sin precios disponibles: {e(", ".join(no_price))}</p>'
        if no_price
        else ""
    )

    # Detalle de las rutas más baratas
    sections = []
    detailed = [r for r in ordered if r.result.quotes][: config.max_routes_detail]
    for r in detailed:
        res = r.result
        rows = []
        for q in sorted(res.quotes, key=lambda q: q.price)[: config.top_n]:
            alert = " 🔔" if res.alert_price is not None and q.price <= res.alert_price else ""
            rows.append(
                "<tr>"
                f'<td style="{TD}">{fmt_trip(q)}</td>'
                f'<td style="{TD};text-align:right">{_price_link(q)}{alert}</td>'
                f'<td style="{TD}">{_change_html(r.change_pct(q), threshold)}</td>'
                f'<td style="{TD}">{e(q.airline)}</td>'
                f'<td style="{TD};color:{MUTED}">{fmt_stops(q.stops)}</td>'
                "</tr>"
            )
        umbral = (
            f" · umbral {fmt_price(res.alert_price, res.quotes[0].currency)}"
            if res.alert_price is not None
            else ""
        )
        sections.append(
            f'<h3 style="margin:24px 0 4px">{e(res.route.origin)} ✈ {e(res.route.destination)}'
            f'<span style="font-weight:normal;font-size:13px;color:{MUTED}">'
            f" · {len(res.quotes)} combinaciones con precio{umbral}</span></h3>"
            f'<table style="border-collapse:collapse;font-size:13px">{"".join(rows)}</table>'
            f"{_grid(r)}"
        )

    return f"""<!doctype html>
<html><body style="font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;color:#1f2328;max-width:760px;margin:0 auto;padding:16px">
<h2 style="margin:0 0 4px">Reporte diario de precios de vuelos</h2>
<div style="color:{MUTED};font-size:13px">{run_date.strftime('%d/%m/%Y')} · {len(reports)} rutas revisadas</div>
{top_html}
{dest_html}
<h3 style="margin:24px 0 4px">Mínimo por ruta</h3>
<table style="border-collapse:collapse;font-size:13px;width:100%">
<tr style="background:#f6f8fa;text-align:left">
<th style="{TD}">Ruta</th><th style="{TD};text-align:right">Mínimo</th>
<th style="{TD}">Viaje</th><th style="{TD}">vs. ayer</th><th style="{TD}"></th></tr>
{''.join(summary_rows)}
</table>
{no_price_html}
{''.join(sections)}
<p style="color:{MUTED};font-size:11px;margin-top:32px">Los precios son el valor más bajo encontrado para cada combinación de
fechas y pueden cambiar. "vs. ayer" compara contra el mismo viaje en la corrida anterior.</p>
</body></html>"""
