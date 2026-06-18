"""Entité calendrier CCEG Déchets pour Home Assistant."""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .api import CollecteZone, is_even_week
from .const import (
    CALENDAR_LOOKAHEAD_DAYS,
    DOMAIN,
    EVENT_DM_SUMMARY,
    EVENT_DR_SUMMARY,
    KEY_ZONE,
)
from .coordinator import CcegDataUpdateCoordinator
from .holidays import effective_collection_date
from .sensor import _entry_display_name

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Crée le calendrier pour cette entrée."""
    coordinator: CcegDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([CcegCalendarEntity(coordinator, entry)])


def _build_description(zone: CollecteZone, flux: str, shifted: bool, shift_from: date | None = None) -> str:
    """Construit la description d'un événement de calendrier."""
    semaine = zone.om_semaine if flux == "dm" else zone.jj_semaine
    desc_semaine = zone.sempaire if semaine == "paire" else zone.semimpaire

    lines = [
        f"Zone : {zone.nom}",
        f"Semaines {semaine}s",
        desc_semaine,
    ]
    if shifted and shift_from is not None:
        lines.append(f"⚠️ Report dû à un jour férié (collecte nominale : {shift_from.strftime('%A %d/%m/%Y')})")
    return "\n".join(filter(None, lines))


def _generate_events(
    zone: CollecteZone,
    start: date,
    end: date,
) -> list[CalendarEvent]:
    """
    Génère la liste des CalendarEvent pour la période [start, end[.

    Pour chaque semaine de collecte :
      1. On détermine la date nominale (jour habituel de collecte).
      2. On applique le report éventuel dû aux jours fériés.
      3. Si la date effective tombe dans [start, end[, on crée l'événement.

    Deux événements distincts par occurrence (DM et DR).
    Les événements décalés indiquent le report dans leur titre et description.
    """
    if zone.is_apport_volontaire or zone.weekday is None:
        return []

    events: list[CalendarEvent] = []

    # On itère sur toutes les semaines de la période
    # En cherchant les jours nominaux de collecte dans une fenêtre élargie
    # (un report peut déplacer un événement hors de [start, end[ ou y faire entrer
    # un événement dont la date nominale serait juste avant start)
    search_start = start - timedelta(days=7)  # marge arrière pour les reports
    search_end = end

    current = search_start
    while current < search_end:
        if current.weekday() != zone.weekday:
            current += timedelta(days=1)
            continue

        nominal = current
        week_even = is_even_week(nominal)
        effective, shifted = effective_collection_date(nominal)

        # Vérifier que la date effective tombe dans la fenêtre demandée
        if effective < start or effective >= end:
            current += timedelta(days=1)
            continue

        suffix = " ⚠️ (report J.F.)" if shifted else ""

        # Déchets ménagers
        if zone.om_semaine is not None:
            dm_match = (zone.om_semaine == "paire" and week_even) or (
                zone.om_semaine == "impaire" and not week_even
            )
            if dm_match:
                events.append(
                    CalendarEvent(
                        start=effective,
                        end=effective + timedelta(days=1),
                        summary=f"{EVENT_DM_SUMMARY}{suffix}",
                        description=_build_description(
                            zone, "dm", shifted, nominal if shifted else None
                        ),
                    )
                )

        # Déchets recyclables
        if zone.jj_semaine is not None:
            dr_match = (zone.jj_semaine == "paire" and week_even) or (
                zone.jj_semaine == "impaire" and not week_even
            )
            if dr_match:
                events.append(
                    CalendarEvent(
                        start=effective,
                        end=effective + timedelta(days=1),
                        summary=f"{EVENT_DR_SUMMARY}{suffix}",
                        description=_build_description(
                            zone, "dr", shifted, nominal if shifted else None
                        ),
                    )
                )

        current += timedelta(days=1)

    return events


class CcegCalendarEntity(CoordinatorEntity[CcegDataUpdateCoordinator], CalendarEntity):
    """Calendrier des collectes de déchets pour une zone CCEG."""

    def __init__(
        self,
        coordinator: CcegDataUpdateCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry

        # Utilise le même nom d'affichage que les sensors (nom personnalisé en priorité)
        display_name = _entry_display_name(entry)

        self._attr_unique_id = f"cceg_dechets_{entry.entry_id}_calendar"
        self._attr_name = display_name
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=f"CCEG Déchets – {display_name}",
            manufacturer="CCEG Erdre & Gesvres",
            model="Collecte des déchets 2025",
            entry_type="service",
            configuration_url=(
                "https://experience.arcgis.com/experience/979c138e76054acc9a66858b08f628b0"
            ),
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Propriété event : prochain événement (affiché dans l'état de l'entité)
    # ──────────────────────────────────────────────────────────────────────────
    @property
    def event(self) -> CalendarEvent | None:
        """Retourne le prochain événement à venir (ou en cours aujourd'hui)."""
        zone: CollecteZone | None = self.coordinator.data.get(KEY_ZONE)
        if zone is None:
            return None

        today = dt_util.now().date()
        horizon = today + timedelta(days=21)  # fenêtre plus large pour les reports
        events = _generate_events(zone, today, horizon)

        if not events:
            return None

        events.sort(key=lambda e: e.start)
        return events[0]

    # ──────────────────────────────────────────────────────────────────────────
    # async_get_events : interrogée par HA pour afficher le calendrier
    # ──────────────────────────────────────────────────────────────────────────
    async def async_get_events(
        self,
        hass: HomeAssistant,
        start_date: datetime,
        end_date: datetime,
    ) -> list[CalendarEvent]:
        """Retourne les événements dans la fenêtre demandée par HA."""
        zone: CollecteZone | None = self.coordinator.data.get(KEY_ZONE)
        if zone is None:
            return []

        start = start_date.date() if isinstance(start_date, datetime) else start_date
        end = end_date.date() if isinstance(end_date, datetime) else end_date

        today = dt_util.now().date()
        max_end = today + timedelta(days=CALENDAR_LOOKAHEAD_DAYS)
        end = min(end, max_end)

        if start >= end:
            return []

        events = _generate_events(zone, start, end)
        events.sort(key=lambda e: e.start)
        return events
