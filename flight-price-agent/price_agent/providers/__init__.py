from ..config import Config
from .base import PriceProvider, ProviderError


def build_provider(config: Config) -> PriceProvider:
    if config.provider == "travelpayouts":
        from .travelpayouts import TravelpayoutsProvider

        return TravelpayoutsProvider(config)
    if config.provider == "serpapi":
        from .serpapi import SerpApiProvider

        return SerpApiProvider(config)
    if config.provider == "demo":
        from .demo import DemoProvider

        return DemoProvider(config)
    raise ProviderError(f"Proveedor desconocido: {config.provider}")


__all__ = ["build_provider", "PriceProvider", "ProviderError"]
