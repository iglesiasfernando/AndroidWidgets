"""Proveedor Travelpayouts / Aviasales Data API (gratis, precios cacheados).

Los precios provienen de búsquedas reales de usuarios de las últimas 48 h,
así que puede haber días sin dato. Token gratis en https://www.travelpayouts.com
"""

from __future__ import annotations

import os
import time
from datetime import date, datetime, timedelta

from ..models import Quote, Route
from .base import PriceProvider, ProviderError, cheapest_per_trip, get_json

API_URL = "https://api.travelpayouts.com/aviasales/v3/prices_for_dates"
SITE = "https://www.aviasales.com"


class TravelpayoutsProvider(PriceProvider):
    def __init__(self, config):
        super().__init__(config)
        self.token = os.environ.get("TRAVELPAYOUTS_TOKEN", "")
        if not self.token:
            raise ProviderError("Falta la variable de entorno TRAVELPAYOUTS_TOKEN")

    def _month_pairs(self, dates: list[date]) -> list[tuple[str, str | None]]:
        """Combinaciones (mes de ida, mes de vuelta) a consultar."""
        stays = self.config.stay_range
        pairs = set()
        for d in dates:
            dep = d.strftime("%Y-%m")
            if not stays:
                pairs.add((dep, None))
            else:
                for n in stays:
                    pairs.add((dep, (d + timedelta(days=n)).strftime("%Y-%m")))
        return sorted(pairs, key=lambda p: (p[0], p[1] or ""))

    def fetch(self, route: Route, dates: list[date]) -> list[Quote]:
        wanted = set(dates)
        quotes: list[Quote] = []
        for dep_month, ret_month in self._month_pairs(dates):
            params = {
                "origin": route.origin,
                "destination": route.destination,
                "departure_at": dep_month,
                "currency": self.config.currency.lower(),
                "sorting": "price",
                "unique": "false",
                "direct": str(self.config.direct_only).lower(),
                "limit": 1000,
                "page": 1,
                "one_way": "true" if ret_month is None else "false",
                "token": self.token,
            }
            if ret_month:
                params["return_at"] = ret_month
            data = get_json(API_URL, params)
            if not data.get("success", False):
                raise ProviderError(data.get("error") or "Respuesta sin éxito")
            for item in data.get("data", []):
                q = self._parse(route, item)
                if q and q.departure in wanted and self._stay_ok(q):
                    quotes.append(q)
            time.sleep(0.2)
        return cheapest_per_trip(quotes)

    def _stay_ok(self, q: Quote) -> bool:
        stays = self.config.stay_range
        if not stays:
            return q.return_date is None
        return (
            q.return_date is not None
            and (q.return_date - q.departure).days in stays
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
