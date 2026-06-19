"""Client ArcGIS pour la collecte des déchets CCEG Erdre & Gesvres."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta

import aiohttp

from .holidays import effective_collection_date

_LOGGER = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Endpoints ArcGIS (service public, pas de token nécessaire)
# ──────────────────────────────────────────────────────────────────────────────
_ARCGIS_BASE = (
    "https://services3.arcgis.com/lJakwtA2QJJ4gJs4/arcgis/rest/services"
    "/CCEG_EPCI_DECHETS_COLLECTE_2025_PAVE_grand_public/FeatureServer/0"
)
_QUERY_URL = f"{_ARCGIS_BASE}/query"

_HEADERS = {
    "Referer": "https://experience.arcgis.com/",
    "Origin": "https://experience.arcgis.com",
    "User-Agent": "Mozilla/5.0 (compatible; HomeAssistant/cceg_dechets)",
    "Accept": "application/json",
}

# Tous les champs utiles du layer
_OUT_FIELDS = "FID,ccodep,codcomm,nom,jourcol,sempaire,semimpaire,paire,impaire,url"

# ──────────────────────────────────────────────────────────────────────────────
# Mapping jourcol → Python weekday (Monday = 0)
# ──────────────────────────────────────────────────────────────────────────────
JOURCOL_WEEKDAY: dict[str, int] = {
    "Lundi": 0,
    "Mardi": 1,
    "Mercredi": 2,
    "Jeudi": 3,
    "Vendredi": 4,
}


# ──────────────────────────────────────────────────────────────────────────────
# Dataclass zone
# ──────────────────────────────────────────────────────────────────────────────
@dataclass
class CollecteZone:
    """Représente une zone de collecte des déchets CCEG."""

    fid: int
    nom: str
    ccodep: str
    codcomm: str
    jourcol: str                  # "Lundi" … "Vendredi" ou "Apport volontaire"
    weekday: int | None           # None si apport volontaire
    om_semaine: str | None        # "paire" | "impaire" | None
    jj_semaine: str | None        # "paire" | "impaire" | None
    sempaire: str                 # description semaine paire
    semimpaire: str               # description semaine impaire
    url_calendrier: str

    @property
    def is_apport_volontaire(self) -> bool:
        return self.jourcol == "Apport volontaire" or self.weekday is None

    def __str__(self) -> str:
        return self.nom or f"Zone {self.fid}"


# ──────────────────────────────────────────────────────────────────────────────
# Exceptions
# ──────────────────────────────────────────────────────────────────────────────
class CcegApiError(Exception):
    """Erreur générique lors de l'appel à l'API ArcGIS."""


class CcegZoneNotFoundError(CcegApiError):
    """Aucune zone trouvée pour les critères donnés."""


# ──────────────────────────────────────────────────────────────────────────────
# Parsing
# ──────────────────────────────────────────────────────────────────────────────
def _parse_semaine(sempaire: str, semimpaire: str) -> tuple[str | None, str | None]:
    """
    Déduit quelle semaine correspond à OM et laquelle à JJ.

    Retourne (om_semaine, jj_semaine) avec valeurs "paire" | "impaire" | None.
    """
    s_paire = (sempaire or "").lower()
    s_impaire = (semimpaire or "").lower()

    if "ordures" in s_paire or "om" in s_paire:
        return "paire", "impaire"
    if "ordures" in s_impaire or "om" in s_impaire:
        return "impaire", "paire"
    if "jaune" in s_paire or "recyclable" in s_paire:
        return "impaire", "paire"
    if "jaune" in s_impaire or "recyclable" in s_impaire:
        return "paire", "impaire"
    return None, None


def _str_field(value) -> str:
    """
    Convertit un champ ArcGIS en chaîne utilisable.

    ArcGIS peut renvoyer None, 0 (entier), ou une chaîne vide pour les champs
    textuels non renseignés. On normalise tout ça en chaîne vide.
    """
    if value is None:
        return ""
    if not isinstance(value, str):
        return ""  # ignore les 0, entiers, etc.
    return value.strip()


def _attrs_to_zone(attrs: dict) -> CollecteZone:
    """Convertit un dict d'attributs ArcGIS en CollecteZone."""
    jourcol = _str_field(attrs.get("jourcol"))
    sempaire = _str_field(attrs.get("sempaire"))
    semimpaire = _str_field(attrs.get("semimpaire"))

    # Fallback sur paire/impaire si sempaire/semimpaire absents
    if not sempaire:
        sempaire = _str_field(attrs.get("paire"))
    if not semimpaire:
        semimpaire = _str_field(attrs.get("impaire"))

    om_semaine, jj_semaine = _parse_semaine(sempaire, semimpaire)

    return CollecteZone(
        fid=attrs.get("FID", 0),
        nom=(attrs.get("nom") or "").strip(),
        ccodep=(attrs.get("ccodep") or "").strip(),
        codcomm=(attrs.get("codcomm") or "").strip(),
        jourcol=jourcol,
        weekday=JOURCOL_WEEKDAY.get(jourcol),
        om_semaine=om_semaine,
        jj_semaine=jj_semaine,
        sempaire=sempaire,
        semimpaire=semimpaire,
        url_calendrier=(attrs.get("url") or "").strip(),
    )


# ──────────────────────────────────────────────────────────────────────────────
# Requêtes ArcGIS
# ──────────────────────────────────────────────────────────────────────────────
async def _query(
    session: aiohttp.ClientSession, params: dict
) -> list[dict]:
    """Effectue une requête query et retourne la liste des attributs."""
    base_params = {
        "f": "json",
        "outFields": _OUT_FIELDS,
        "returnGeometry": "false",
    }
    base_params.update(params)

    try:
        async with session.get(
            _QUERY_URL,
            params=base_params,
            headers=_HEADERS,
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            resp.raise_for_status()
            data = await resp.json(content_type=None)
    except aiohttp.ClientError as err:
        raise CcegApiError(f"Erreur réseau ArcGIS : {err}") from err

    if "error" in data:
        raise CcegApiError(f"Erreur ArcGIS : {data['error']}")

    return [f["attributes"] for f in data.get("features", [])]


async def fetch_zones_by_commune(
    session: aiohttp.ClientSession,
    codcomm: str,
) -> list[CollecteZone]:
    """
    Retourne toutes les zones de collecte d'une commune (par code commune).
    Exclut les zones "Apport volontaire".
    """
    attrs_list = await _query(
        session,
        {
            "where": f"codcomm='{codcomm}' AND jourcol<>'Apport volontaire'",
            "orderByFields": "nom ASC",
        },
    )
    if not attrs_list:
        raise CcegZoneNotFoundError(f"Aucune zone trouvée pour codcomm='{codcomm}'")
    return [_attrs_to_zone(a) for a in attrs_list]


async def fetch_zone_by_gps(
    session: aiohttp.ClientSession,
    latitude: float,
    longitude: float,
) -> CollecteZone:
    """
    Retourne la zone de collecte correspondant aux coordonnées GPS.

    Utilise une requête spatiale intersects avec le polygone de la zone.
    Les coordonnées sont converties de WGS84 → Web Mercator (EPSG:3857)
    car le service utilise ce référentiel.
    """
    # Conversion WGS84 → Web Mercator (EPSG:3857)
    import math
    x = longitude * 20037508.34 / 180
    y = math.log(math.tan((90 + latitude) * math.pi / 360)) / (math.pi / 180)
    y = y * 20037508.34 / 180

    attrs_list = await _query(
        session,
        {
            "geometry": f"{x},{y}",
            "geometryType": "esriGeometryPoint",
            "spatialRel": "esriSpatialRelIntersects",
            "inSR": "102100",
            "where": "1=1",
        },
    )
    if not attrs_list:
        raise CcegZoneNotFoundError(
            f"Aucune zone trouvée aux coordonnées ({latitude}, {longitude}). "
            "Êtes-vous bien dans la CCEG Erdre & Gesvres ?"
        )
    return _attrs_to_zone(attrs_list[0])


async def fetch_zone_by_fid(
    session: aiohttp.ClientSession,
    fid: int,
) -> CollecteZone:
    """Retourne une zone par son FID (après sélection manuelle)."""
    attrs_list = await _query(
        session,
        {"where": f"FID={fid}"},
    )
    if not attrs_list:
        raise CcegZoneNotFoundError(f"Zone FID={fid} introuvable")
    return _attrs_to_zone(attrs_list[0])


async def fetch_communes(
    session: aiohttp.ClientSession,
) -> list[dict]:
    """
    Retourne la liste des communes CCEG.
    Chaque entrée : {"nom": str, "codcomm": str}.
    """
    try:
        async with session.get(
            _QUERY_URL,
            params={
                "f": "json",
                "where": "jourcol<>'Apport volontaire'",
                "outFields": "codcomm,nom",
                "returnGeometry": "false",
                "returnDistinctValues": "true",
                "orderByFields": "codcomm ASC",
                "resultRecordCount": "200",
                "groupByFieldsForStatistics": "codcomm",
            },
            headers=_HEADERS,
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            resp.raise_for_status()
            data = await resp.json(content_type=None)
    except aiohttp.ClientError as err:
        raise CcegApiError(f"Erreur réseau : {err}") from err

    # Extraire les codcomm uniques + un nom de référence (premier nom de zone)
    seen: dict[str, str] = {}
    for feat in data.get("features", []):
        a = feat["attributes"]
        codcomm = (a.get("codcomm") or "").strip()
        nom = (a.get("nom") or "").strip()
        if codcomm and codcomm not in seen:
            # Le nom de zone inclut souvent le nom de la commune
            # On prend le préfixe avant le premier tiret ou espace
            commune_nom = _extract_commune_name(nom, codcomm)
            seen[codcomm] = commune_nom

    return [
        {"nom": nom, "codcomm": codcomm}
        for codcomm, nom in sorted(seen.items(), key=lambda x: x[1])
    ]


def _extract_commune_name(zone_nom: str, codcomm: str) -> str:
    """
    Tente d'extraire le nom de la commune depuis le nom de la zone.
    Ex: "CARQUEFOU - Nord" → "CARQUEFOU"
    Ex: "GRANDCHAMP-DES-FONTAINES" → "GRANDCHAMP-DES-FONTAINES"
    """
    for sep in [" - ", " – ", " / "]:
        if sep in zone_nom:
            return zone_nom.split(sep)[0].strip()
    return zone_nom.strip()


# ──────────────────────────────────────────────────────────────────────────────
# Calcul des prochaines dates
# ──────────────────────────────────────────────────────────────────────────────
def is_even_week(d: date | None = None) -> bool:
    """Retourne True si la semaine ISO de `d` est paire."""
    return (d or date.today()).isocalendar()[1] % 2 == 0


def next_collection_dates(
    zone: CollecteZone,
    from_date: date | None = None,
) -> dict[str, date]:
    """
    Calcule les prochaines dates de collecte déchets ménagers (om) et
    déchets recyclables (jj), en tenant compte des reports liés aux jours fériés.

    Retourne {"om": date_effective, "jj": date_effective}.
    Clé absente si non déterminable.
    """
    if zone.is_apport_volontaire or zone.weekday is None:
        return {}

    today = from_date or date.today()
    results: dict[str, date] = {}

    for flux, semaine_type in [
        ("om", zone.om_semaine),
        ("jj", zone.jj_semaine),
    ]:
        if semaine_type is None:
            continue
        # On cherche sur 21 jours (14 + marge pour les reports en fin de semaine)
        for delta in range(21):
            nominal = today + timedelta(days=delta)
            if nominal.weekday() != zone.weekday:
                continue
            week_even = is_even_week(nominal)
            if semaine_type == "paire" and not week_even:
                continue
            if semaine_type == "impaire" and week_even:
                continue
            # Bonne semaine de parité → appliquer le report éventuel
            effective, shifted = effective_collection_date(nominal)
            # La date effective doit être >= today
            if effective >= today:
                results[flux] = effective
                break
            # Si le report a repoussé la date à demain alors qu'on était aujourd'hui,
            # on continue pour trouver la prochaine occurrence non passée

    return results
