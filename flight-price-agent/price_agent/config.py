from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

from .models import Route

IATA_RE = re.compile(r"^[A-Z]{3}$")


class ConfigError(ValueError):
    pass


@dataclass
class Config:
    provider: str
    currency: str
    days_ahead_start: int
    days_ahead_end: int
    stay_nights_min: Optional[int]
    stay_nights_max: Optional[int]
    direct_only: bool
    origins: list[str]
    destinations: list[str]
    alerts: dict[str, float] = field(default_factory=dict)
    fixed_dates: list[date] = field(default_factory=list)
    top_n: int = 5
    top_overall: int = 10
    max_routes_detail: int = 10
    change_threshold_pct: float = 5.0
    history_db: str = "data/prices.sqlite"

    @property
    def routes(self) -> list[Route]:
        return [
            Route(o, d)
            for o in self.origins
            for d in self.destinations
            if o != d
        ]

    @property
    def stay_range(self) -> Optional[list[int]]:
        """Noches de estadía a buscar (None = sólo ida)."""
        if self.stay_nights_min is None:
            return None
        return list(range(self.stay_nights_min, self.stay_nights_max + 1))

    def departure_dates(self, today: date) -> list[date]:
        if self.fixed_dates:
            return [d for d in self.fixed_dates if d >= today]
        return [
            today + timedelta(days=n)
            for n in range(self.days_ahead_start, self.days_ahead_end + 1)
        ]

    def alert_for(self, route: Route) -> Optional[float]:
        return self.alerts.get(route.key, self.alerts.get(route.destination))


def _iata_list(value, name: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ConfigError(f"'{name}' debe ser una lista no vacía de códigos IATA")
    codes = [str(v).strip().upper() for v in value]
    bad = [c for c in codes if not IATA_RE.match(c)]
    if bad:
        raise ConfigError(f"Códigos IATA inválidos en '{name}': {', '.join(bad)}")
    return codes


def load_config(path: str | Path) -> Config:
    path = Path(path)
    if not path.exists():
        raise ConfigError(
            f"No existe {path}. Copiá config.example.toml como config.toml."
        )
    with path.open("rb") as fh:
        raw = tomllib.load(fh)

    search = raw.get("search", {})
    airports = raw.get("airports", {})
    report = raw.get("report", {})
    storage = raw.get("storage", {})

    provider = str(search.get("provider", "travelpayouts")).lower()
    if provider not in {"travelpayouts", "serpapi", "demo"}:
        raise ConfigError(f"Proveedor desconocido: {provider}")

    start = int(search.get("days_ahead_start", 7))
    end = int(search.get("days_ahead_end", 60))
    if start < 0 or end < start:
        raise ConfigError("La ventana de días es inválida (0 <= start <= end)")

    stay = search.get("stay_nights")
    stay_min = search.get("stay_nights_min", stay)
    stay_max = search.get("stay_nights_max", stay_min)
    if (stay_min is None) != (stay_max is None):
        raise ConfigError("Definí stay_nights_min y stay_nights_max juntos")
    if stay_min is not None and not 0 < int(stay_min) <= int(stay_max):
        raise ConfigError("Rango de noches inválido (0 < min <= max)")

    try:
        fixed_dates = sorted(
            {date.fromisoformat(str(d)) for d in search.get("departure_dates", [])}
        )
    except ValueError as e:
        raise ConfigError(f"Fecha inválida en departure_dates: {e}") from e
    alerts = {
        str(k).upper(): float(v) for k, v in raw.get("alerts", {}).items()
    }

    return Config(
        provider=provider,
        currency=str(search.get("currency", "USD")).upper(),
        days_ahead_start=start,
        days_ahead_end=end,
        stay_nights_min=int(stay_min) if stay_min is not None else None,
        stay_nights_max=int(stay_max) if stay_max is not None else None,
        fixed_dates=fixed_dates,
        direct_only=bool(search.get("direct_only", False)),
        origins=_iata_list(airports.get("origins"), "airports.origins"),
        destinations=_iata_list(
            airports.get("destinations"), "airports.destinations"
        ),
        alerts=alerts,
        top_n=int(report.get("top_n", 5)),
        top_overall=int(report.get("top_overall", 10)),
        max_routes_detail=int(report.get("max_routes_detail", 10)),
        change_threshold_pct=float(report.get("change_threshold_pct", 5)),
        history_db=str(storage.get("history_db", "data/prices.sqlite")),
    )
