from __future__ import annotations

import logging
from datetime import date

from .config import Config
from .history import History
from .models import RouteResult
from .providers import PriceProvider, ProviderError
from .report import RouteReport

log = logging.getLogger(__name__)


def run_checks(
    config: Config, provider: PriceProvider, history: History, today: date
) -> list[RouteReport]:
    """Consulta todas las rutas, guarda el histórico y arma los datos del reporte."""
    dates = config.departure_dates(today)
    reports: list[RouteReport] = []
    for route in config.routes:
        log.info("Consultando %s (%d fechas)", route.key, len(dates))
        result = RouteResult(route=route, alert_price=config.alert_for(route))
        try:
            result.quotes = provider.fetch(route, dates)
        except ProviderError as e:
            log.warning("Error en %s: %s", route.key, e)
            result.error = str(e)

        # Leer el histórico antes de guardar el run de hoy.
        report = RouteReport(
            result=result,
            previous=history.previous(route, today, config.currency),
            historical_min=history.historical_min(route, config.currency),
        )
        history.save(today, result.quotes)
        reports.append(report)
    return reports
