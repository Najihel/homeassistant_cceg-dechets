"""Sensors CCEG Déchets."""
from __future__ import annotations

import logging
import re
from datetime import date

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_ENTRY_NAME,
    CONF_ZONE_FID,
    CONF_ZONE_NOM,
    DOMAIN,
    KEY_DAYS_UNTIL_DM,
    KEY_DAYS_UNTIL_DR,
    KEY_NEXT_DM,
    KEY_NEXT_DR,
    KEY_ZONE,
)
from .coordinator import CcegDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


def _slugify(text: str) -> str:
    """Convertit un texte en slug utilisable dans un entity_id."""
    text = text.lower()
    for src, dst in [
        ("é","e"),("è","e"),("ê","e"),("ë","e"),
        ("à","a"),("â","a"),("ä","a"),
        ("ô","o"),("ö","o"),
        ("ù","u"),("û","u"),("ü","u"),
        ("ç","c"),("î","i"),("ï","i"),("ñ","n"),
    ]:
        text = text.replace(src, dst)
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")


def _entry_display_name(entry: ConfigEntry) -> str:
    """
    Retourne le nom d'affichage de l'entrée.

    Priorité : nom personnalisé (CONF_ENTRY_NAME) > titre de l'entrée > nom de zone ArcGIS.
    """
    return (
        entry.data.get(CONF_ENTRY_NAME)
        or entry.title
        or entry.data.get(CONF_ZONE_NOM)
        or str(entry.data.get(CONF_ZONE_FID, ""))
    )


def _entry_slug(entry: ConfigEntry) -> str:
    """
    Retourne le slug stable pour construire les unique_id des entités.

    On utilise le nom personnalisé (CONF_ENTRY_NAME) s'il est défini,
    sinon le nom ArcGIS de la zone, sinon le FID.
    Le FID seul est utilisé en fallback ultime pour garantir l'unicité.
    """
    name = entry.data.get(CONF_ENTRY_NAME) or entry.data.get(CONF_ZONE_NOM) or ""
    slug = _slugify(name) if name else ""
    fid = entry.data.get(CONF_ZONE_FID, "")
    # On suffixe toujours par le FID pour garantir l'unicité entre deux
    # entrées dont l'utilisateur aurait choisi le même nom personnalisé.
    return f"{slug}_{fid}" if slug else str(fid)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Crée les sensors pour cette entrée."""
    coordinator: CcegDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    async_add_entities([
        CcegNextCollectionSensor(coordinator, entry, "dechets_menagers"),
        CcegNextCollectionSensor(coordinator, entry, "dechets_recyclables"),
        CcegDaysUntilSensor(coordinator, entry, "dechets_menagers"),
        CcegDaysUntilSensor(coordinator, entry, "dechets_recyclables"),
        CcegJourColSensor(coordinator, entry),
    ])


def _device_info(entry: ConfigEntry) -> DeviceInfo:
    display_name = _entry_display_name(entry)
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=f"CCEG Déchets – {display_name}",
        manufacturer="CCEG Erdre & Gesvres",
        model="Collecte des déchets 2025",
        entry_type="service",
        configuration_url=(
            "https://experience.arcgis.com/experience/979c138e76054acc9a66858b08f628b0"
        ),
    )


class _CcegBaseSensor(CoordinatorEntity[CcegDataUpdateCoordinator], SensorEntity):
    """Classe de base pour tous les sensors CCEG."""

    def __init__(self, coordinator: CcegDataUpdateCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_device_info = _device_info(entry)
        self._slug = _entry_slug(entry)
        self._display_name = _entry_display_name(entry)


class CcegNextCollectionSensor(_CcegBaseSensor):
    """Date de la prochaine collecte déchets ménagers ou recyclables."""

    _attr_device_class = SensorDeviceClass.DATE

    def __init__(
        self,
        coordinator: CcegDataUpdateCoordinator,
        entry: ConfigEntry,
        flux: str,
    ) -> None:
        super().__init__(coordinator, entry)
        self._flux = flux
        if flux == "dechets_menagers":
            self._attr_unique_id = f"cceg_dechets_{self._slug}_next_dechets_menagers"
            self._attr_name = f"Prochaine collecte déchets ménagers – {self._display_name}"
            self._attr_icon = "mdi:trash-can"
        else:
            self._attr_unique_id = f"cceg_dechets_{self._slug}_next_dechets_recyclables"
            self._attr_name = f"Prochaine collecte déchets recyclables – {self._display_name}"
            self._attr_icon = "mdi:recycle"

    @property
    def native_value(self) -> date | None:
        key = KEY_NEXT_DM if self._flux == "dechets_menagers" else KEY_NEXT_DR
        return self.coordinator.data.get(key)

    @property
    def extra_state_attributes(self) -> dict:
        zone = self.coordinator.data.get(KEY_ZONE)
        if zone is None:
            return {}
        flux_semaine = zone.om_semaine if self._flux == "dechets_menagers" else zone.jj_semaine
        return {
            "jour_collecte": zone.jourcol,
            "semaine": flux_semaine,
            "description_semaine_paire": zone.sempaire,
            "description_semaine_impaire": zone.semimpaire,
            "zone_nom": zone.nom,
            "url_calendrier": zone.url_calendrier,
        }


class CcegDaysUntilSensor(_CcegBaseSensor):
    """Nombre de jours avant la prochaine collecte."""

    _attr_native_unit_of_measurement = "j"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        coordinator: CcegDataUpdateCoordinator,
        entry: ConfigEntry,
        flux: str,
    ) -> None:
        super().__init__(coordinator, entry)
        self._flux = flux
        if flux == "dechets_menagers":
            self._attr_unique_id = f"cceg_dechets_{self._slug}_days_dechets_menagers"
            self._attr_name = f"Jours avant collecte déchets ménagers – {self._display_name}"
            self._attr_icon = "mdi:trash-can-outline"
        else:
            self._attr_unique_id = f"cceg_dechets_{self._slug}_days_dechets_recyclables"
            self._attr_name = f"Jours avant collecte déchets recyclables – {self._display_name}"
            self._attr_icon = "mdi:recycle-variant"

    @property
    def native_value(self) -> int | None:
        key = KEY_DAYS_UNTIL_DM if self._flux == "dechets_menagers" else KEY_DAYS_UNTIL_DR
        return self.coordinator.data.get(key)


class CcegJourColSensor(_CcegBaseSensor):
    """Jour de la semaine de collecte (texte)."""

    _attr_icon = "mdi:calendar-week"

    def __init__(self, coordinator: CcegDataUpdateCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"cceg_dechets_{self._slug}_jour_collecte"
        self._attr_name = f"Jour de collecte – {self._display_name}"

    @property
    def native_value(self) -> str | None:
        zone = self.coordinator.data.get(KEY_ZONE)
        return zone.jourcol if zone else None

    @property
    def extra_state_attributes(self) -> dict:
        zone = self.coordinator.data.get(KEY_ZONE)
        if zone is None:
            return {}
        return {
            "semaine_dechets_menagers": zone.om_semaine,
            "semaine_dechets_recyclables": zone.jj_semaine,
            "description_semaine_paire": zone.sempaire,
            "description_semaine_impaire": zone.semimpaire,
            "zone_nom": zone.nom,
            "zone_fid": zone.fid,
            "codcomm": zone.codcomm,
            "url_calendrier": zone.url_calendrier,
        }
