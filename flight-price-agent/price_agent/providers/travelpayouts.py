"""Proveedor Travelpayouts / Aviasales Data API (gratis, precios cacheados).

Los precios provienen de búsquedas reales de usuarios de las últimas 48 h,
así que puede haber días sin dato. Token gratis en https://www.travelpayouts.com
"""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta

from ..models import Quote, Route
from .base import PriceProvider, ProviderError, cheapest_per_day, get_json

API_URL = "https://api.travelpayouts.com/aviasales/v3/prices_for_dates"
SITE = "https://www.aviasales.com"


class TravelpayoutsProvider(PriceProvider):
    def __init__(self, config):
        super().__init__(config)
        self.token = os.environ.get("TRAVELPAYOUTS_TOKEN", "")
        if not self.token:
            raise ProviderError("Falta la variable de entorno TRAVELPAYOUTS_TOKEN")

    def fetch(self, route: Route, dates: list[date]) -> list[Quote]:
        wanted = set(dates)
        months = sorted({d.strftime("%Y-%m") for d in dates})
        quotes: list[Quote] = []
        for month in months:
            params = {
                "origin": route.origin,
                "destination": route.destination,
                "departure_at": month,
                "currency": self.config.currency.lower(),
                "sorting": "price",
                "unique": "false",
                "direct": str(self.config.direct_only).lower(),
                "limit": 1000,
                "page": 1,
                "token": self.token,
            }
            if self.config.stay_nights:
                params["one_way"] = "false"
            else:
                params["one_way"] = "true"
            data = get_json(API_URL, params)
            if not data.get("success", False):
                raise ProviderError(data.get("error") or "Respuesta sin éxito")
            for item in data.get("data", []):
                q = self._parse(route, item)
                if q and q.departure in wanted and self._stay_ok(q):
                    quotes.append(q)
        return cheapest_per_day(quotes)

    def _stay_ok(self, q: Quote) -> bool:
        if not self.config.stay_nights:
            return True
        return (
            q.return_date is not None
            and q.return_date == q.departure + timedelta(days=self.config.stay_nights)
        )

    def _parse(self, route: Route, item: dict) -> Quote | None:
        try:
            dep = datetime.fromisoformat(item["departure_at"]).date()
            ret = (
                datetime.fromisoformat(item["return_at"]).date()
                if item.get("return_at")
                else None
            )
            link = item.get("link", "")
            return Quote(
                route=route,
                departure=dep,
                return_date=ret,
                price=float(item["price"]),
                currency=self.config.currency,
                airline=item.get("airline", ""),
                stops=item.get("transfers"),
                duration_min=item.get("duration_to") or item.get("duration"),
                link=f"{SITE}{link}" if link.startswith("/") else link,
            )
        except (KeyError, TypeError, ValueError):
            return None
