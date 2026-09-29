"""Proveedor SerpApi (Google Flights, precios en tiempo real).

Hace 1 request por fecha y ruta: ojo con la cuota del plan.
API key en https://serpapi.com
"""

from __future__ import annotations

import os
import urllib.parse
from datetime import date, timedelta

from ..models import Quote, Route
from .base import PriceProvider, ProviderError, get_json

API_URL = "https://serpapi.com/search.json"


class SerpApiProvider(PriceProvider):
    def __init__(self, config):
        super().__init__(config)
        self.api_key = os.environ.get("SERPAPI_KEY", "")
        if not self.api_key:
            raise ProviderError("Falta la variable de entorno SERPAPI_KEY")

    def fetch(self, route: Route, dates: list[date]) -> list[Quote]:
        quotes: list[Quote] = []
        errors: list[str] = []
        for d in dates:
            try:
                q = self._fetch_day(route, d)
            except ProviderError as e:
                errors.append(f"{d}: {e}")
                continue
            if q:
                quotes.append(q)
        if errors and not quotes:
            raise ProviderError("; ".join(errors[:3]))
        return quotes

    def _fetch_day(self, route: Route, d: date) -> Quote | None:
        ret = (
            d + timedelta(days=self.config.stay_nights)
            if self.config.stay_nights
            else None
        )
        params = {
            "engine": "google_flights",
            "departure_id": route.origin,
            "arrival_id": route.destination,
            "outbound_date": d.isoformat(),
            "currency": self.config.currency,
            "hl": "es",
            "type": 1 if ret else 2,
            "api_key": self.api_key,
        }
        if ret:
            params["return_date"] = ret.isoformat()
        if self.config.direct_only:
            params["stops"] = 1
        data = get_json(API_URL, params)
        if "error" in data:
            if "no results" in str(data["error"]).lower():
                return None
            raise ProviderError(data["error"])

        options = data.get("best_flights", []) + data.get("other_flights", [])
        options = [o for o in options if o.get("price")]
        if not options:
            return None
        best = min(options, key=lambda o: o["price"])
        legs = best.get("flights", [])
        airlines = sorted({leg.get("airline", "") for leg in legs} - {""})
        link = "https://www.google.com/travel/flights?" + urllib.parse.urlencode(
            {"q": f"Flights from {route.origin} to {route.destination} on {d}"}
        )
        return Quote(
            route=route,
            departure=d,
            return_date=ret,
            price=float(best["price"]),
            currency=self.config.currency,
            airline=", ".join(airlines),
            stops=max(len(legs) - 1, 0),
            duration_min=best.get("total_duration"),
            link=link,
        )
