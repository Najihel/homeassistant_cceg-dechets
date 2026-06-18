"""Constantes de l'intégration CCEG Déchets."""

DOMAIN = "cceg_dechets"

# Clés config entry
CONF_COMMUNE = "commune"
CONF_ZONE_NOM = "zone_nom"
CONF_ZONE_FID = "zone_fid"
CONF_SELECTION_MODE = "selection_mode"
CONF_ENTRY_NAME = "entry_name"        # Nom personnalisé saisi par l'utilisateur

# Modes de sélection de zone
MODE_GPS = "gps"
MODE_MANUAL = "manual"

# Mise à jour
DEFAULT_SCAN_INTERVAL_HOURS = 24

# Calendrier
CALENDAR_LOOKAHEAD_DAYS = 365         # Horizon de génération des événements
EVENT_DM_SUMMARY = "🗑️ Collecte déchets ménagers"
EVENT_DR_SUMMARY = "♻️ Collecte déchets recyclables"

# Clés coordinator
KEY_ZONE = "zone"
KEY_NEXT_DM = "next_dechets_menagers"
KEY_NEXT_DR = "next_dechets_recyclables"
KEY_DAYS_UNTIL_DM = "days_until_dechets_menagers"
KEY_DAYS_UNTIL_DR = "days_until_dechets_recyclables"
