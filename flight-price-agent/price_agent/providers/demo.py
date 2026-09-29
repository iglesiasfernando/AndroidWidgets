"""Proveedor de prueba: precios ficticios pero estables por ruta y fecha."""

from __future__ import annotations

import hashlib
from datetime import date, timedelta

from ..models import Quote, Route
from .base import PriceProvider


class DemoProvider(PriceProvider):
    def __init__(self, config, seed: str = ""):
        super().__init__(config)
        self.seed = seed or date.today().isoformat()

    def fetch(self, route: Route, dates: list[date]) -> list[Quote]:
        base = 150 + self._rand(route.key) % 700
        quotes = []
        for d in dates:
            noise = self._rand(f"{route.key}{d}{self.seed}") % 200 - 60
            weekend = 40 if d.weekday() in (4, 5, 6) else 0
            quotes.append(
                Quote(
                    route=route,
                    departure=d,
                    return_date=(
                        d + timedelta(days=self.config.stay_nights)
                        if self.config.stay_nights
                        else None
                    ),
                    price=float(max(base + noise + weekend, 49)),
                    currency=self.config.currency,
                    airline=["AR", "LA", "AA", "IB", "G3"][self._rand(str(d)) % 5],
                    stops=self._rand(f"s{route.key}{d}") % 3,
                    duration_min=180 + self._rand(route.key) % 600,
                )
            )
        return quotes

    @staticmethod
    def _rand(s: str) -> int:
        return int(hashlib.sha256(s.encode()).hexdigest()[:8], 16)
