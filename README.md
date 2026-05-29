# Regenerative Microclimate Probe

**AT6012 × infrared.city Buildathon 2026 — CCAE / UCC School of Architecture**

A probing tool over the [infrared.city](https://infrared.city) SDK that grounds urban
microclimate analysis in **real vegetation data**, and tests regenerative interventions
across three cohort cities.

> **The gap this addresses.** The infrared SDK fetches street trees from OpenStreetMap —
> but their attributes come back empty: `species`, `height`, `diameter_crown`, `leaf_type`
> are all `null`. We know *where* trees are, not *what* they are. This project fills that
> gap with **authoritative public data** and shows what it changes.

## What it does

For any site polygon it runs the three focus analyses — **UTCI (thermal comfort), wind, and
solar** — and compares a **baseline** (buildings only) against a **vegetation intervention**,
scoring each with grid-native regenerative metrics (heat-stress %, Thermal Assembly
Complexity Index, after Alberti 2016 and the UTCI scale of Błażejczyk et al. 2013).

### The "API-first" enrichment ladder
1. **City open data (keyless):** Rome `geoportale.comune.roma.it` WFS street-tree register
   *with species*, Marseille `data.ampmetropole.fr` parks, Cork `data.corkcity.ie` CKAN.
2. **Earth observation (keyless):** ESA WorldCover 10 m land-cover / tree-cover via the
   Microsoft Planetary Computer STAC — also drawn as a geo-referenced map overlay.
3. **Credentialed (optional):** Sentinel-2 NDVI, Roboflow tree-canopy CV, GUS.earth urban-forest
   models — documented adapters, switch on with a key.

## Case studies (live, real API results)

| City | Vegetation source | Headline finding |
|---|---|---|
| **Marseille** (Vieux-Port) | SDK/OSM | 93% built-up (EO); canopy *raised* modelled heat-stress — dense-canyon trapping + cell masking |
| **Cork** (Nano Nagle Place) | SDK/OSM | Mild maritime climate, 0% heat-stress; canopy adds thermal-zone diversity (+7.6%) |
| **Rome** (Municipio VIII) | **City register, 757 trees / 33 species** | Data-provenance proof: municipal species data drives a live analysis |

The honest through-line: **"add trees" is not automatically regenerative** — placement,
density, and street geometry decide the outcome. That critical result is the point.

## Components

| File | Role |
|---|---|
| `output/tool.html` | **Probe tool** — Leaflet map (`?lat=&lng=&zoom=`), controls, case-study presets, WorldCover overlay, live-backend hook |
| `scorecard.py` | Multi-site runner (`--site`, `--veg-source sdk\|city`, `--run`) |
| `time_series.py` | Diurnal UTCI sweep |
| `city_data.py` | Keyless city open-data connectors + ESA WorldCover + overlay renderer; documented Roboflow/Sentinel stubs |
| `regenerative_metrics.py` | UTCI bands, Thermal Assembly Complexity Index (grid-native) |
| `server.py` | FastAPI backend for live probing + keyless `/landcover` |
| `output/*.html`, `output/*.png` | Deployable pages, scorecard figures, WorldCover overlays |

## Run it

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # paste your INFRARED_API_KEY
python verify_setup.py
python scorecard.py --run --site rome --veg-source city   # live multi-physics run
uvicorn server:app --port 8000                            # backend for tool.html "live" mode
```

Get an infrared.city API key at <https://infrared.city>. The key is read from the environment /
`.env` (gitignored) and is never committed or sent to the browser.

**Setting up on your own?** [`SETUP.md`](SETUP.md) has step-by-step account + API-key
instructions for every source (infrared.city · Roboflow · Copernicus/Sentinel Hub · GUS.earth),
which are keyless, and full run commands. All keys go in one file: `.env` (from `.env.example`).

## Live demo

- design.curricula.dev/at6012/infrared.city/tool.html
- ccae.curricula.dev/at6012/infrared.city/tool.html

## Credits

AT6012 Design Research, CCAE / UCC School of Architecture. Built on the
[infrared.city SDK](https://infrared.city/docs/sdk/) and its
[skills/cookbook](https://github.com/Infrared-city/infrared-skills). Regenerative-metrics
lineage from the 2025 AT6012 toolkit. Data: Roma Capitale, Aix-Marseille Métropole, Cork City
Council open data; ESA WorldCover via Microsoft Planetary Computer.

**Apache License 2.0** — see `LICENSE` (consistent with the upstream infrared.city
[infrared-skills](https://github.com/Infrared-city/infrared-skills), and chosen for its
explicit patent grant in the spirit of the open-source community of practice). See `NOTICE`
for attributions.
