"""
Gestion des jours fériés français et calcul du report de collecte CCEG.

Règle CCEG (source : calendriers officiels) :
  "La collecte des jours fériés ET des jours suivants est reportée au lendemain."

Concrètement, pour une semaine donnée (lun→dim) :
  - On recense tous les jours fériés tombant un lundi à vendredi.
  - Pour chaque jour de collecte C de la semaine, le décalage est égal au nombre
    de jours fériés situés dans [lundi de la semaine … C].
  - Si plusieurs fériés tombent dans la même semaine, les reports se cumulent.

Exemple – semaine S19/2026 (4 fériés : 1er mai vendredi, 8 mai vendredi de S19,
Ascension jeudi S22, Pentecôte lundi S23) :
  Mai 2026 :
    S19 : 1er mai (vendredi) → collecte vendredi décalée au samedi          (+1)
    S20 : 8 mai  (vendredi) → collecte vendredi décalée au samedi           (+1)
    S22 : Ascension (jeudi) → collecte jeudi décalée au vendredi,
                               collecte vendredi décalée au samedi          (+1 chacun)
"""
from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache


# ──────────────────────────────────────────────────────────────────────────────
# Calcul des jours fériés français (algorithme de Gauss/Butcher pour Pâques)
# ──────────────────────────────────────────────────────────────────────────────

def _easter(year: int) -> date:
    """Retourne la date de Pâques pour l'année donnée (algorithme de Butcher)."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


@lru_cache(maxsize=10)
def french_public_holidays(year: int) -> frozenset[date]:
    """
    Retourne l'ensemble des jours fériés légaux français pour une année.

    Mis en cache par année (lru_cache) pour éviter les recalculs répétés
    lors de la génération des événements sur 365 jours.
    """
    easter = _easter(year)

    holidays = {
        date(year, 1, 1),           # Jour de l'An
        easter + timedelta(days=1), # Lundi de Pâques
        date(year, 5, 1),           # Fête du Travail
        date(year, 5, 8),           # Victoire 1945
        easter + timedelta(days=39),# Ascension (jeudi J+39)
        easter + timedelta(days=50),# Lundi de Pentecôte
        date(year, 7, 14),          # Fête Nationale
        date(year, 8, 15),          # Assomption
        date(year, 11, 1),          # Toussaint
        date(year, 11, 11),         # Armistice
        date(year, 12, 25),         # Noël
    }
    return frozenset(holidays)


def is_public_holiday(d: date) -> bool:
    """Retourne True si `d` est un jour férié en France."""
    return d in french_public_holidays(d.year)


# ──────────────────────────────────────────────────────────────────────────────
# Calcul du report de collecte
# ──────────────────────────────────────────────────────────────────────────────

def collection_date_with_shift(nominal_date: date) -> date:
    """
    Retourne la date effective de collecte en tenant compte des reports
    dus aux jours fériés.

    Algorithme :
      1. Identifier le lundi de la semaine ISO de `nominal_date`.
      2. Compter le nombre de jours fériés lun-ven dans [lundi … nominal_date].
         → c'est le décalage cumulé à appliquer.
      3. La date effective = nominal_date + décalage.

    Notes :
      - On ne regarde que les fériés du lundi au vendredi (sam/dim ne décalent
        pas la collecte car il n'y a pas de collecte ces jours-là).
      - Le décalage peut être 0, 1, 2… selon le nombre de fériés en début de
        semaine avant ou sur le jour de collecte.
    """
    # Lundi de la semaine ISO courante
    monday = nominal_date - timedelta(days=nominal_date.weekday())

    shift = 0
    # Parcourir chaque jour de lundi jusqu'au jour nominal inclus
    for delta in range(nominal_date.weekday() + 1):  # 0=lundi … weekday=jour nominal
        day = monday + timedelta(days=delta)
        if is_public_holiday(day):
            shift += 1

    return nominal_date + timedelta(days=shift)


def effective_collection_date(nominal_date: date) -> tuple[date, bool]:
    """
    Retourne (date_effective, est_decalee).

    `est_decalee` est True si la date a été modifiée par rapport à la date nominale.
    Utile pour annoter les événements du calendrier.
    """
    effective = collection_date_with_shift(nominal_date)
    return effective, effective != nominal_date
