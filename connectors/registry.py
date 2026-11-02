"""Connector lookup by name. Add a new source type here."""

from connectors.adzuna import AdzunaConnector
from connectors.arbeitnow import ArbeitnowConnector
from connectors.base import Connector
from connectors.greenhouse import GreenhouseConnector
from connectors.lever import LeverConnector
from connectors.rss import RssConnector

CONNECTORS: dict[str, type[Connector]] = {
    c.name: c
    for c in (
        GreenhouseConnector,
        LeverConnector,
        ArbeitnowConnector,
        AdzunaConnector,
        RssConnector,
    )
}


def get_connector_class(name: str) -> type[Connector]:
    try:
        return CONNECTORS[name]
    except KeyError:
        raise ValueError(f"Unknown connector {name!r}; available: {sorted(CONNECTORS)}") from None
