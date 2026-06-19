"""Config flow pour CCEG Déchets – sélection GPS ou manuelle + nom personnalisé."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import (
    CcegApiError,
    CcegZoneNotFoundError,
    CollecteZone,
    fetch_communes,
    fetch_zone_by_fid,
    fetch_zone_by_gps,
    fetch_zones_by_commune,
)
from .const import (
    CONF_COMMUNE,
    CONF_ENTRY_NAME,
    CONF_SELECTION_MODE,
    CONF_ZONE_FID,
    CONF_ZONE_NOM,
    DOMAIN,
    MODE_GPS,
    MODE_MANUAL,
)

_LOGGER = logging.getLogger(__name__)


class CcegDechetsConfigFlow(ConfigFlow, domain=DOMAIN):
    """
    Flux de configuration :
      1.  Choix du mode (GPS ou manuel)
      2a. [GPS]    → confirmation de la zone détectée
      2b. [Manuel] → sélection de la commune
      3.  [Manuel] → sélection de la zone/quartier
      4.  Nom personnalisé + confirmation finale (commun aux deux modes)
    """

    VERSION = 1

    def __init__(self) -> None:
        self._mode: str = ""
        self._communes: list[dict] = []
        self._codcomm: str = ""
        self._zones: list[CollecteZone] = []
        self._selected_zone: CollecteZone | None = None

    # ──────────────────────────────────────────────────────────────────────────
    # Étape 1 : choix du mode
    # ──────────────────────────────────────────────────────────────────────────
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Étape 1 – Choisir entre géolocalisation et sélection manuelle."""
        if user_input is not None:
            self._mode = user_input[CONF_SELECTION_MODE]
            if self._mode == MODE_GPS:
                return await self.async_step_gps()
            return await self.async_step_commune()

        schema = vol.Schema(
            {
                vol.Required(CONF_SELECTION_MODE, default=MODE_GPS): SelectSelector(
                    SelectSelectorConfig(
                        options=[
                            SelectOptionDict(
                                value=MODE_GPS,
                                label="📍 Utiliser ma position GPS (zone.home)",
                            ),
                            SelectOptionDict(
                                value=MODE_MANUAL,
                                label="🗺️ Choisir ma commune et mon quartier",
                            ),
                        ],
                        mode=SelectSelectorMode.LIST,
                    )
                )
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema)

    # ──────────────────────────────────────────────────────────────────────────
    # Étape 2a : détection GPS
    # ──────────────────────────────────────────────────────────────────────────
    async def async_step_gps(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Étape 2a – Détection automatique via zone.home."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # L'utilisateur a confirmé → on passe au nommage
            return await self.async_step_name()

        home_zone = self.hass.states.get("zone.home")
        if home_zone is None:
            errors["base"] = "no_home_zone"
            return self.async_show_form(
                step_id="gps", data_schema=vol.Schema({}), errors=errors
            )

        lat = home_zone.attributes.get("latitude")
        lon = home_zone.attributes.get("longitude")
        if lat is None or lon is None:
            errors["base"] = "no_home_zone"
            return self.async_show_form(
                step_id="gps", data_schema=vol.Schema({}), errors=errors
            )

        session = async_get_clientsession(self.hass)
        try:
            zone = await fetch_zone_by_gps(session, lat, lon)
            self._selected_zone = zone
        except CcegZoneNotFoundError:
            errors["base"] = "gps_zone_not_found"
            return self.async_show_form(
                step_id="gps", data_schema=vol.Schema({}), errors=errors
            )
        except CcegApiError as err:
            _LOGGER.error("Erreur API GPS : %s", err)
            errors["base"] = "api_error"
            return self.async_show_form(
                step_id="gps", data_schema=vol.Schema({}), errors=errors
            )

        # Construire des descriptions lisibles même si sempaire/semimpaire sont vides
        if zone.om_semaine and zone.jj_semaine:
            sempaire_display = f"Déchets ménagers (OM semaines {zone.om_semaine}s)"
            semimpaire_display = f"Déchets recyclables (semaines {zone.jj_semaine}s)"
        else:
            sempaire_display = zone.sempaire or "Non renseigné"
            semimpaire_display = zone.semimpaire or "Non renseigné"

        return self.async_show_form(
            step_id="gps",
            data_schema=vol.Schema({}),
            errors=errors,
            description_placeholders={
                "zone_nom": zone.nom or f"Zone #{zone.fid}",
                "jourcol": zone.jourcol or "Inconnu",
                "sempaire": sempaire_display,
                "semimpaire": semimpaire_display,
            },
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Étape 2b : sélection de la commune (mode manuel)
    # ──────────────────────────────────────────────────────────────────────────
    async def async_step_commune(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Étape 2b – Sélection de la commune."""
        errors: dict[str, str] = {}
        session = async_get_clientsession(self.hass)

        if not self._communes:
            try:
                self._communes = await fetch_communes(session)
            except CcegApiError as err:
                _LOGGER.error("Impossible de charger les communes : %s", err)
                errors["base"] = "api_error"
                self._communes = []

        if user_input is not None and not errors:
            self._codcomm = user_input[CONF_COMMUNE]
            return await self.async_step_zone()

        options = [
            SelectOptionDict(value=c["codcomm"], label=c["nom"])
            for c in self._communes
        ]
        schema = vol.Schema(
            {
                vol.Required(CONF_COMMUNE): SelectSelector(
                    SelectSelectorConfig(
                        options=options,
                        mode=SelectSelectorMode.DROPDOWN,
                        sort=True,
                    )
                )
            }
        )
        return self.async_show_form(
            step_id="commune", data_schema=schema, errors=errors
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Étape 3 : sélection de la zone/quartier (mode manuel)
    # ──────────────────────────────────────────────────────────────────────────
    async def async_step_zone(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Étape 3 – Sélection du quartier/zone dans la commune choisie."""
        errors: dict[str, str] = {}
        session = async_get_clientsession(self.hass)

        if not self._zones:
            try:
                self._zones = await fetch_zones_by_commune(session, self._codcomm)
            except CcegZoneNotFoundError:
                errors["base"] = "zone_not_found"
            except CcegApiError as err:
                _LOGGER.error("Erreur chargement zones : %s", err)
                errors["base"] = "api_error"

        if errors:
            return self.async_show_form(
                step_id="zone", data_schema=vol.Schema({}), errors=errors
            )

        # Une seule zone dans la commune → sélection automatique
        if len(self._zones) == 1:
            self._selected_zone = self._zones[0]
            return await self.async_step_name()

        if user_input is not None:
            fid = int(user_input[CONF_ZONE_FID])
            try:
                zone = await fetch_zone_by_fid(session, fid)
                self._selected_zone = zone
                return await self.async_step_name()
            except CcegApiError as err:
                _LOGGER.error("Erreur chargement zone FID=%s : %s", fid, err)
                errors["base"] = "api_error"

        options = [
            SelectOptionDict(value=str(z.fid), label=self._zone_label(z))
            for z in self._zones
        ]
        schema = vol.Schema(
            {
                vol.Required(CONF_ZONE_FID): SelectSelector(
                    SelectSelectorConfig(
                        options=options,
                        mode=SelectSelectorMode.LIST,
                    )
                )
            }
        )
        return self.async_show_form(
            step_id="zone", data_schema=schema, errors=errors
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Étape 4 : nom personnalisé (commun GPS et manuel)
    # ──────────────────────────────────────────────────────────────────────────
    async def async_step_name(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """
        Étape finale – Saisie d'un nom personnalisé pour cette entrée.

        Le nom sera utilisé comme titre de l'entrée, du device et du calendrier.
        Une valeur par défaut est proposée à partir du nom de zone ArcGIS.
        """
        zone = self._selected_zone
        default_name = zone.nom if zone else "Collecte CCEG"

        if user_input is not None:
            entry_name = user_input[CONF_ENTRY_NAME].strip() or default_name
            return self._create_entry(zone, entry_name)

        schema = vol.Schema(
            {
                vol.Required(CONF_ENTRY_NAME, default=default_name): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.TEXT)
                )
            }
        )
        # Construire un résumé lisible de la zone pour l'étape de nommage
        if zone:
            zone_nom_display = zone.nom or f"Zone #{zone.fid}"
            jourcol_display = zone.jourcol or "Inconnu"
            if zone.om_semaine and zone.jj_semaine:
                rotation_display = (
                    f"OM semaines {zone.om_semaine}s / "
                    f"Recyclables semaines {zone.jj_semaine}s"
                )
            elif zone.sempaire or zone.semimpaire:
                rotation_display = " | ".join(filter(None, [zone.sempaire, zone.semimpaire]))
            else:
                rotation_display = "Rotation non déterminée"
        else:
            zone_nom_display = ""
            jourcol_display = ""
            rotation_display = ""

        return self.async_show_form(
            step_id="name",
            data_schema=schema,
            description_placeholders={
                "zone_nom": zone_nom_display,
                "jourcol": jourcol_display,
                "rotation": rotation_display,
            },
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────────────────────────────────
    @staticmethod
    def _zone_label(zone: CollecteZone) -> str:
        """
        Construit un label discriminant pour le sélecteur de zones.

        Quand plusieurs zones d'une même commune ont le même nom et le même
        jourcol (cas réel observé sur SAINT-MARS-DU-DESERT), on différencie
        via la rotation OM/recyclables et en dernier recours via le FID.
        """
        label = zone.nom or f"Zone {zone.fid}"

        if zone.jourcol:
            label += f"  —  {zone.jourcol}"

        # Afficher la rotation si disponible (info la plus utile pour l'utilisateur)
        if zone.om_semaine and zone.jj_semaine:
            label += f"  (OM sem. {zone.om_semaine}s / Recyclables sem. {zone.jj_semaine}s)"
        elif zone.sempaire:
            label += f"  (sem. paire : {zone.sempaire[:50]})"
        elif zone.semimpaire:
            label += f"  (sem. impaire : {zone.semimpaire[:50]})"
        else:
            # Dernier recours : FID pour distinguer des zones sans description
            label += f"  [zone #{zone.fid}]"

        return label

    def _create_entry(self, zone: CollecteZone, entry_name: str) -> ConfigFlowResult:
        """Crée l'entrée de configuration."""
        return self.async_create_entry(
            title=entry_name,
            data={
                CONF_SELECTION_MODE: self._mode,
                CONF_ZONE_FID: zone.fid,
                CONF_ZONE_NOM: zone.nom,
                CONF_COMMUNE: zone.codcomm,
                CONF_ENTRY_NAME: entry_name,
            },
        )
