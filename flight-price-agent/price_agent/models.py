from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional


@dataclass(frozen=True)
class Route:
    origin: str
    destination: str

    @property
    def key(self) -> str:
        return f"{self.origin}-{self.destination}"


@dataclass
class Quote:
    """Precio más barato encontrado para una ruta en una fecha de salida."""

    route: Route
    departure: date
    price: float
    currency: str
    return_date: Optional[date] = None
    airline: str = ""
    stops: Optional[int] = None
    duration_min: Optional[int] = None
    link: str = ""


@dataclass
class RouteResult:
    route: Route
    quotes: list[Quote] = field(default_factory=list)
    error: Optional[str] = None
    alert_price: Optional[float] = None

    @property
    def cheapest(self) -> Optional[Quote]:
        return min(self.quotes, key=lambda q: q.price) if self.quotes else None
