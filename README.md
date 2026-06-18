# CCEG Déchets – Home Assistant Integration

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![HA Version](https://img.shields.io/badge/Home%20Assistant-2026.3%2B-blue.svg)](https://www.home-assistant.io/)
[![Version](https://img.shields.io/badge/version-1.0.0-green)](https://github.com/Najihel/homeassistant_cceg-dechets/releases)

Intégration Home Assistant pour connaître les **jours de collecte des déchets ménagers et des déchets recyclables** au sein de la **Communauté de Communes Erdre & Gesvres (CCEG)**.

Source des données : [Carte ArcGIS CCEG – Mes jours de collecte](https://experience.arcgis.com/experience/979c138e76054acc9a66858b08f628b0)

---

## Fonctionnalités

- Détection automatique de votre zone via les coordonnées GPS de `zone.home`
- Ou sélection manuelle par commune puis par quartier
- **Calendrier Home Assistant** avec les événements de collecte sur 365 jours (2 événements par semaine de collecte : un "Déchets Ménagers" et un "Déchets Recyclables")
- Plusieurs zones configurables indépendamment (un calendrier et un device par zone)
- **Report automatique des jours fériés** : lorsqu'un jour férié tombe en semaine, la collecte et toutes celles qui suivent dans la même semaine sont décalées d'un jour (événements marqués ⚠️ dans le calendrier)
- Nom personnalisé pour chaque entrée (ex. *Maison*, *Bureau*)
- 5 entités sensor par zone configurée :

| Entité | Classe | Description |
|--------|--------|-------------|
| `sensor.cceg_dechets_*_next_dechets_menagers` | `date` | Prochaine date de collecte des déchets ménagers |
| `sensor.cceg_dechets_*_next_dechets_recyclables` | `date` | Prochaine date de collecte des déchets recyclables |
| `sensor.cceg_dechets_*_days_dechets_menagers` | `measurement` (j) | Compte à rebours déchets ménagers |
| `sensor.cceg_dechets_*_days_dechets_recyclables` | `measurement` (j) | Compte à rebours déchets recyclables |
| `sensor.cceg_dechets_*_jour_collecte` | — | Jour de la semaine (Lundi … Vendredi) |

---

## Installation via HACS

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Najihel&repository=homeassistant_cceg-dechets&category=integration)

Ou manuellement dans HACS :

1. **HACS → Intégrations → ⋮ → Dépôts personnalisés**
2. Ajouter l'URL : `https://github.com/Najihel/homeassistant_cceg-dechets`  
   Catégorie : **Intégration**
3. Chercher **CCEG Déchets** et installer
4. Redémarrer Home Assistant

## Installation manuelle

1. Copier le dossier `custom_components/cceg_dechets/` dans `config/custom_components/`
2. Redémarrer Home Assistant

---

## Configuration

[![Open your Home Assistant instance and start setting up a new integration of a specific brand.](https://my.home-assistant.io/badges/brand.svg)](https://my.home-assistant.io/redirect/brand/?brand=cceg_dechets)

Ou via **Paramètres → Intégrations → Ajouter une intégration → CCEG Déchets**.

Pour configurer **plusieurs quartiers**, ajoutez l'intégration autant de fois que nécessaire — chaque ajout crée un calendrier et un device indépendants.

### Flux de configuration

```
Étape 1 : Choix du mode
    ├── 📍 GPS → Étape 2 : Confirmation de la zone détectée
    └── 🗺️ Manuel → Étape 2 : Commune → Étape 3 : Zone/quartier
                                              ↓
                              Étape 4 (commun) : Nom personnalisé
```

**Étape 1 – Mode de sélection**

- **GPS** : utilise les coordonnées de `zone.home` pour une requête spatiale précise sur le polygone ArcGIS.
- **Manuel** : sélection de la commune dans la liste CCEG, puis du quartier parmi les zones disponibles.

**Étape finale – Nom personnalisé**

Un nom est proposé automatiquement (ex. *CARQUEFOU - Nord*). Vous pouvez le modifier librement — il devient le titre du calendrier et du device (ex. *Maison*, *Parents*).

---

## Calendrier

L'intégration crée un **calendrier HomeAssistant** nommé d'après votre entrée. Il contient deux types d'événements journée entière :

- 🗑️ **Collecte déchets ménagers** — les semaines correspondantes
- ♻️ **Collecte déchets recyclables** — les semaines alternées

Les événements sont générés sur **365 jours glissants** et mis à jour une fois par jour.

### Intégration dans une automatisation via le calendrier

```yaml
alias: "Rappel sortie des poubelles"
trigger:
  - platform: calendar
    event: start
    offset: "-12:00:00"   # 12h avant le début de l'événement
    entity_id: calendar.maison
action:
  - service: notify.mobile_app
    data:
      title: "🗑️ Collecte demain"
      message: "{{ trigger.calendar_event.summary }}"
```

---

## Report des jours fériés

Conformément au calendrier officiel CCEG, **lorsqu'un jour férié tombe un lundi à vendredi**, la collecte de ce jour et de tous les jours de collecte qui suivent dans la même semaine (ISO) est **reportée au lendemain** — et les reports se cumulent si plusieurs fériés tombent dans la même semaine.

Exemple — mai 2026 :
| Semaine | Férié | Collecte nominale | Collecte effective |
|---------|-------|------------------|--------------------|
| S18 | 1er mai (vendredi) | vendredi | **samedi** |
| S19 | 8 mai (vendredi) | vendredi | **samedi** |
| S22 | Ascension (jeudi) | jeudi | **vendredi** |
| S22 | Ascension (jeudi) | vendredi | **samedi** |

Les fériés pris en compte sont les **11 jours fériés légaux français** (Jour de l'An, Lundi de Pâques, 1er Mai, 8 Mai, Ascension, Lundi de Pentecôte, 14 Juillet, Assomption, Toussaint, Armistice, Noël). Ils sont calculés dynamiquement, sans dépendance externe.

Dans le calendrier HA, les événements reportés sont signalés par **⚠️ (report J.F.)** dans leur titre, avec la date nominale originale en description.


## Exemple de carte Lovelace

```yaml
type: entities
title: Collecte des déchets CCEG
entities:
  - entity: calendar.maison
    name: Prochain événement
  - entity: sensor.cceg_dechets_ma_zone_next_dechets_menagers
    name: Prochaine collecte ménagers
    icon: mdi:trash-can
  - entity: sensor.cceg_dechets_ma_zone_next_dechets_recyclables
    name: Prochaine collecte recyclables
    icon: mdi:recycle
  - entity: sensor.cceg_dechets_ma_zone_days_dechets_menagers
    name: Dans (ménagers)
  - entity: sensor.cceg_dechets_ma_zone_days_dechets_recyclables
    name: Dans (recyclables)
```

---

## Fonctionnement technique

L'intégration interroge le **service ArcGIS public de la CCEG** (pas d'authentification requise) :

```
https://services3.arcgis.com/lJakwtA2QJJ4gJs4/arcgis/rest/services/CCEG_EPCI_DECHETS_COLLECTE_2025_PAVE_grand_public/FeatureServer/0/query
```

Chaque polygone de zone contient :
- **`jourcol`** : jour de collecte (`Lundi` … `Vendredi`)
- **`sempaire`** / **`semimpaire`** : description du flux collecté selon la parité de la semaine ISO

La parité de semaine suit la **numérotation ISO 8601** (lundi = premier jour de semaine).

La mise à jour se fait **une fois par jour**. Les événements du calendrier sont recalculés à chaque mise à jour.

---

## Suivi des levées réalisées – Intégration Ecocito

> Pour aller plus loin que les jours de collecte planifiés, il est possible de connaître les **levées effectivement réalisées** par type de bac (nombre de vidages, poids, historique), grâce au service **Ecocito** utilisé par la CCEG pour la facturation incitative.

L'intégration Home Assistant **[ecocito-HA-Integration](https://github.com/taptada/ecocito-HA-Integration)** développée par **taptada** permet de récupérer ces données directement dans HA et est parfaitement complémentaire à cette intégration CCEG Déchets.

## Limitations connues

- Le service ArcGIS peut être indisponible ponctuellement (maintenance CCEG)
- Les zones "Apport volontaire" (déchèteries) ne sont pas gérées
- En cas d'évolution du service CCEG (nouvelle URL, nouveaux champs), mettre à jour `api.py`

---

## Compatibilité

Requiert Home Assistant 2026.3 ou supérieur.

---

## Crédits

- **Code** : généré par [Claude.ai](https://claude.ai)
- **Logo** : [Logo CC Erdre et Gesvres — Wikimedia Commons](https://fr.wikipedia.org/wiki/Fichier:Logo_CC_Erdre_et_Gesvres.png)
- **Portail** : [Communauté de Communes Erdre & Gesvres (CCEG) -](https://www.cceg.fr/)
