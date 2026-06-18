"""DataUpdateCoordinator pour CCEG Déchets."""
from __future__ import annotations

import logging
from datetime import date, timedelta

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    CcegApiError,
    CollecteZone,
    fetch_zone_by_fid,
    fetch_zone_by_gps,
    next_collection_dates,
)
from .const import (
    CONF_SELECTION_MODE,
    CONF_ZONE_FID,
    DEFAULT_SCAN_INTERVAL_HOURS,
    DOMAIN,
    KEY_DAYS_UNTIL_DM,
    KEY_DAYS_UNTIL_DR,
    KEY_NEXT_DM,
    KEY_NEXT_DR,
    KEY_ZONE,
    MODE_GPS,
)

_LOGGER = logging.getLogger(__name__)


class CcegDataUpdateCoordinator(DataUpdateCoordinator[dict]):
    """Interroge l'API ArcGIS CCEG une fois par jour."""

    def __init__(
        self,
        hass: HomeAssistant,
        session: aiohttp.ClientSession,
        entry: ConfigEntry,
    ) -> None:
        self._session = session
        self._mode: str = entry.data[CONF_SELECTION_MODE]
        self._fid: int = entry.data[CONF_ZONE_FID]

        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{self._fid}",
            update_interval=timedelta(hours=DEFAULT_SCAN_INTERVAL_HOURS),
        )

    async def _async_update_data(self) -> dict:
        """Récupère la zone et calcule les prochaines dates de collecte."""
        try:
            zone = await self._fetch_zone()
        except CcegApiError as err:
            raise UpdateFailed(str(err)) from err

        today = date.today()
        next_dates = next_collection_dates(zone, from_date=today)

        next_dm: date | None = next_dates.get("om")
        next_dr: date | None = next_dates.get("jj")

        return {
            KEY_ZONE: zone,
            KEY_NEXT_DM: next_dm,
            KEY_NEXT_DR: next_dr,
            KEY_DAYS_UNTIL_DM: (next_dm - today).days if next_dm else None,
            KEY_DAYS_UNTIL_DR: (next_dr - today).days if next_dr else None,
        }

    async def _fetch_zone(self) -> CollecteZone:
        """
        Récupère la zone selon le mode configuré.

        Mode GPS : relit les coordonnées de zone.home à chaque refresh
        (utile si la famille déménage ou si on teste depuis un autre endroit).
        Mode manuel : utilise directement le FID stocké.
        """
        if self._mode == MODE_GPS:
            home_zone = self.hass.states.get("zone.home")
            if home_zone is None:
                raise CcegApiError("zone.home introuvable dans Home Assistant")
            lat = home_zone.attributes.get("latitude")
            lon = home_zone.attributes.get("longitude")
            if lat is None or lon is None:
                raise CcegApiError("Coordonnées GPS absentes de zone.home")
            return await fetch_zone_by_gps(self._session, lat, lon)

        # Mode manuel : FID fixe
        return await fetch_zone_by_fid(self._session, self._fid)
