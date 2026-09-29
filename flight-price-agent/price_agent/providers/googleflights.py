"""Proveedor Google Flights con Chromium (Playwright). No requiere API key.

Abre la página pública de Google Flights para cada combinación de fechas y lee
los precios de los resultados. Incluye todas las aerolíneas (Aerolíneas
Argentinas, JetSMART, GOL, LATAM, Azul, etc.).

Hace una carga de página por ruta, fecha de ida y estadía, a ritmo tranquilo.
"""

from __future__ import annotations

import logging
import os
import re
import urllib.parse
from datetime import date, timedelta
from pathlib import Path

from ..models import Quote, Route
from .base import PriceProvider, ProviderError, cheapest_per_trip

log = logging.getLogger(__name__)

BASE_URL = "https://www.google.com/travel/flights"

# Ej.: "From 469 US dollars round trip total. 1 stop flight with GOL. Leaves ..."
PRICE_RE = re.compile(r"From ([\d,]+) (US dollars|[A-Za-z ]+?)(?: round trip| one way)? total", re.I)
STOPS_RE = re.compile(r"(Nonstop|(\d+) stops?) flight", re.I)
AIRLINE_RE = re.compile(r"flight with ([^.]+?)\.", re.I)
DURATION_RE = re.compile(r"Total duration (?:(\d+) hr)? ?(?:(\d+) min)?", re.I)
LEAVES_RE = re.compile(r"Leaves (.+?) at \d", re.I)
CHEAPEST_RE = re.compile(r"Cheapest\s+from \$([\d,]+)")

# Nombre del aeropuerto de salida (como lo muestra Google) -> código IATA.
AIRPORT_NAMES = {
    "ezeiza": "EZE",
    "aeroparque": "AEP",
    "jorge newbery": "AEP",
}


def airport_code(name: str) -> str:
    low = name.lower()
    for key, code in AIRPORT_NAMES.items():
        if key in low:
            return code
    return ""


def search_url(route: Route, dep: date, ret: date | None, currency: str) -> str:
    q = f"Flights to {route.destination} from {route.origin} on {dep.isoformat()}"
    q += f" through {ret.isoformat()}" if ret else " oneway"
    return f"{BASE_URL}?" + urllib.parse.urlencode(
        {"q": q, "curr": currency, "hl": "en", "gl": "us"}
    )


def parse_labels(
    labels: list[str], route: Route, dep: date, ret: date | None, currency: str, url: str
) -> list[Quote]:
    quotes = []
    for label in labels:
        m = PRICE_RE.search(label)
        if not m:
            continue
        stops = None
        sm = STOPS_RE.search(label)
        if sm:
            stops = 0 if sm.group(1).lower() == "nonstop" else int(sm.group(2))
        am = AIRLINE_RE.search(label)
        airline = am.group(1).replace(" and ", ", ") if am else ""
        lm = LEAVES_RE.search(label)
        origin = airport_code(lm.group(1)) if lm else ""
        if origin and origin != route.origin:
            airline = f"{airline} (sale de {origin})"
        dm = DURATION_RE.search(label)
        duration = None
        if dm and (dm.group(1) or dm.group(2)):
            duration = int(dm.group(1) or 0) * 60 + int(dm.group(2) or 0)
        quotes.append(
            Quote(
                route=route,
                departure=dep,
                return_date=ret,
                price=float(m.group(1).replace(",", "")),
                currency=currency,
                airline=airline,
                stops=stops,
                duration_min=duration,
                link=url,
            )
        )
    return quotes


class GoogleFlightsProvider(PriceProvider):
    def __init__(self, config):
        super().__init__(config)
        try:
            from playwright.sync_api import sync_playwright  # noqa: F401
        except ImportError as e:
            raise ProviderError(
                "Falta Playwright: pip install playwright && python -m playwright install chromium"
            ) from e
        self._pw = None
        self._browser = None
        self._page = None
        self.debug_dir = os.environ.get("GF_DEBUG_DIR")
        self.delay_ms = int(os.environ.get("GF_DELAY_MS", "1500"))

    # -- ciclo de vida del navegador -----------------------------------------

    def _ensure_page(self):
        if self._page:
            return self._page
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        kwargs = {}
        if os.environ.get("CHROMIUM_PATH"):
            kwargs["executable_path"] = os.environ["CHROMIUM_PATH"]
        self._browser = self._pw.chromium.launch(**kwargs)
        ctx = self._browser.new_context(
            locale="en-US", viewport={"width": 1366, "height": 900}
        )
        self._page = ctx.new_page()
        return self._page

    def close(self):
        if self._browser:
            self._browser.close()
        if self._pw:
            self._pw.stop()
        self._page = self._browser = self._pw = None

    # -- búsqueda ------------------------------------------------------------

    def fetch(self, route: Route, dates: list[date]) -> list[Quote]:
        quotes: list[Quote] = []
        errors: list[str] = []
        for d in dates:
            for nights in self.config.stay_range or [None]:
                ret = d + timedelta(days=nights) if nights else None
                try:
                    quotes.extend(self._search(route, d, ret))
                except ProviderError as e:
                    errors.append(f"{d}: {e}")
                    log.warning("%s %s→%s: %s", route.key, d, ret, e)
        if errors and not quotes:
            raise ProviderError("; ".join(errors[:2]))
        return cheapest_per_trip(quotes)

    def _search(self, route: Route, dep: date, ret: date | None) -> list[Quote]:
        from playwright.sync_api import TimeoutError as PWTimeout

        page = self._ensure_page()
        url = search_url(route, dep, ret, self.config.currency)
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
        except PWTimeout as e:
            raise ProviderError("timeout cargando Google Flights") from e

        if "/sorry/" in page.url or "unusual traffic" in page.content().lower():
            raise ProviderError("Google bloqueó temporalmente las búsquedas (captcha)")

        try:
            page.wait_for_selector('[aria-label^="From "]', timeout=25000)
        except PWTimeout:
            self._debug(page, route, dep, ret)
            text = page.inner_text("body")[:300].replace("\n", " ")
            if "no results" in text.lower() or "no flights" in text.lower():
                return []
            raise ProviderError("no aparecieron resultados")

        page.wait_for_timeout(self.delay_ms)
        labels = page.eval_on_selector_all(
            '[aria-label^="From "]', "els => els.map(e => e.getAttribute('aria-label'))"
        )
        quotes = parse_labels(labels, route, dep, ret, self.config.currency, url)

        # La pestaña "Cheapest" muestra el mínimo absoluto, que puede estar entre
        # los vuelos ocultos detrás de "View more flights".
        cm = CHEAPEST_RE.search(page.inner_text("body"))
        if cm:
            cheapest = float(cm.group(1).replace(",", ""))
            if not quotes or cheapest < min(q.price for q in quotes):
                quotes.append(Quote(route, dep, cheapest, self.config.currency,
                                    return_date=ret, link=url))
        if not quotes:
            self._debug(page, route, dep, ret)
        log.debug("%s %s→%s: %d resultados", route.key, dep, ret, len(quotes))
        return quotes

    def _debug(self, page, route: Route, dep: date, ret: date | None):
        if not self.debug_dir:
            return
        Path(self.debug_dir).mkdir(parents=True, exist_ok=True)
        name = f"{route.key}_{dep}_{ret}"
        page.screenshot(path=str(Path(self.debug_dir) / f"{name}.png"), full_page=True)
