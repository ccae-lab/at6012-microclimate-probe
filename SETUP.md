# Setup & API keys

Everything you need to run the Regenerative Microclimate Probe on your own machine.

## 1. Prerequisites
- Python **3.10+** (developed on 3.13)
- Git, and a terminal

## 2. Install
```bash
git clone https://github.com/ccae-lab/at6012-microclimate-probe.git
cd at6012-microclimate-probe
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## 3. Enter your API keys — **one file: `.env`**
```bash
cp .env.example .env        # then open .env and paste your keys
```
`.env` is **gitignored** — it is never committed and never reaches the browser (the
backend reads it server-side). Treat every value like a password.

| # | Source | Env var(s) | Needed for | Where to get it |
|---|---|---|---|---|
| 1 | **infrared.city** | `INFRARED_API_KEY` | all SDK runs (UTCI/wind/solar) | infrared.city → account → API keys |
| 2 | **Roboflow** | `ROBOFLOW_API_KEY`, `ROBOFLOW_MODEL` | tree-canopy CV | roboflow.com → sign up (free) → Workspace → **Settings → API Keys** |
| 3 | **Copernicus / Sentinel Hub** | `SH_CLIENT_ID`, `SH_CLIENT_SECRET` | Sentinel-2 NDVI | dataspace.copernicus.eu → Sentinel Hub Dashboard → **User Settings → OAuth clients → Create** |
| 4 | **GUS.earth (gAIa)** | `GUS_API_KEY` | urban-forest tree models | gus.earth → sign up / request access · docs `backend.gus.earth/docs` |

> **Keyless** (no entry needed): ESA WorldCover land-cover/overlay, and the city
> open-data connectors (Rome WFS, Marseille ODS, Cork CKAN).

### Step-by-step per source
**Roboflow** — Sign up free (no card). Pick/enter your **Workspace** (keys are
workspace-scoped). **Settings → API Keys** → copy or *Generate New Key*. Set
`ROBOFLOW_MODEL` to `project/version` (e.g. `trees/3`). If a key leaks, **Roll API Key**.

**Copernicus / Sentinel Hub** — Register at dataspace.copernicus.eu and confirm email.
Open the **Sentinel Hub Dashboard → User Settings → OAuth clients → Create**. Copy the
**Client ID** and **Client Secret** (the secret shows once). The code exchanges these for a
token automatically (`city_data.sentinel_token()`).

**GUS.earth** — Sign up at gus.earth (app: gaia.gus.earth). Check `backend.gus.earth/docs`
for the auth scheme and confirm the endpoint; set `GUS_API_KEY` (and `GUS_API_BASE` if needed).

## 4. Verify & run
```bash
python verify_setup.py                                   # confirms the infrared key loads
python scorecard.py --run --site cork                    # live multi-physics scorecard
python scorecard.py --run --site rome --veg-source city  # city-data species enrichment
python time_series.py --run --site marseille             # diurnal UTCI sweep
uvicorn server:app --port 8000                           # backend for tool.html "live" mode
```
Open `output/tool.html` (or the live demo) and point its **Backend URL** at your server.

## 5. Use the connectors directly (keyless ones work with no setup)
```python
import city_data as cd
cd.eo_worldcover((12.485, 41.841, 12.495, 41.849))        # ESA WorldCover, keyless
cd.rome_street_trees(limit=50)                            # city register, keyless
cd.roboflow_trees("https://.../tile.jpg")                 # needs ROBOFLOW_API_KEY + MODEL
cd.sentinel_ndvi((12.485, 41.841, 12.495, 41.849))        # needs SH_CLIENT_ID/SECRET
```

## 6. Security best practices
- **Never commit `.env`** or hardcode keys (it's gitignored — keep it that way).
- Keys live **server-side only**; the browser/static pages never receive them.
- This repo is **public** — double-check before every commit. Rotate any key that is exposed.
- Editing displayed KPI numbers? That's data, not secrets: `output/kpis.json`.
