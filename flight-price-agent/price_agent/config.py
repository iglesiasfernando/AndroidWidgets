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
    stay_nights: Optional[int]
    direct_only: bool
    origins: list[str]
    destinations: list[str]
    alerts: dict[str, float] = field(default_factory=dict)
    top_n: int = 5
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

    def departure_dates(self, today: date) -> list[date]:
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
    alerts = {
        str(k).upper(): float(v) for k, v in raw.get("alerts", {}).items()
    }

    return Config(
        provider=provider,
        currency=str(search.get("currency", "USD")).upper(),
        days_ahead_start=start,
        days_ahead_end=end,
        stay_nights=int(stay) if stay is not None else None,
        direct_only=bool(search.get("direct_only", False)),
        origins=_iata_list(airports.get("origins"), "airports.origins"),
        destinations=_iata_list(
            airports.get("destinations"), "airports.destinations"
        ),
        alerts=alerts,
        top_n=int(report.get("top_n", 5)),
        change_threshold_pct=float(report.get("change_threshold_pct", 5)),
        history_db=str(storage.get("history_db", "data/prices.sqlite")),
    )
