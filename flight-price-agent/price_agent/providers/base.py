from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod
from datetime import date

from ..config import Config
from ..models import Quote, Route


class ProviderError(RuntimeError):
    pass


class PriceProvider(ABC):
    def __init__(self, config: Config):
        self.config = config

    @abstractmethod
    def fetch(self, route: Route, dates: list[date]) -> list[Quote]:
        """Devuelve la cotización más barata por fecha de salida (una por día)."""


def cheapest_per_day(quotes: list[Quote]) -> list[Quote]:
    best: dict[date, Quote] = {}
    for q in quotes:
        if q.departure not in best or q.price < best[q.departure].price:
            best[q.departure] = q
    return [best[d] for d in sorted(best)]


def get_json(url: str, params: dict, retries: int = 3, timeout: int = 30) -> dict:
    full = f"{url}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(
        full, headers={"Accept": "application/json", "User-Agent": "price-agent/0.1"}
    )
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")[:300]
            last_err = ProviderError(f"HTTP {e.code}: {body}")
            if e.code < 500 and e.code != 429:
                break
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            last_err = ProviderError(str(e))
        time.sleep(2 ** attempt)
    raise last_err or ProviderError("Error desconocido")
