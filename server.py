"""Microclimate Probe backend, FastAPI over the infrared.city SDK.

Powers the "Live" mode of tool.html. Keeps INFRARED_API_KEY server-side and
exposes one endpoint that runs UTCI/wind/solar over an arbitrary polygon and
returns a scorecard figure (base64 PNG) + metrics.

Run locally:
    pip install fastapi uvicorn        # already added to requirements.txt
    export INFRARED_API_KEY=...        # or use .env
    uvicorn server:app --host 0.0.0.0 --port 8000
Then set the tool's "Backend URL" to  http://localhost:8000/run
(expose to the deployed page with a tunnel, e.g. `cloudflared tunnel --url http://localhost:8000`).
"""

from __future__ import annotations

import base64

import infrared_sdk as ir
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from infrared_sdk.models import TimePeriod
from pydantic import BaseModel

import city_data as cd
import regenerative_metrics as rm  # noqa: F401  (kept for parity / future metrics)
import scorecard as sc

app = FastAPI(title="Microclimate Probe backend")
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])


class Req(BaseModel):
    lat: float
    lng: float
    half: float = 0.0036
    analyses: list[str] = ["utci", "wind", "solar"]
    scenario: str = "both"          # both | baseline | intervention
    veg_source: str = "sdk"         # sdk | city
    month: int = 8
    day: int = 15
    hour: int = 14
    wind_speed: int = 5
    wind_direction: int = 315
    max_tiles: int | None = None    # cost guard


@app.get("/health")
def health():
    return {"ok": True, "sdk": getattr(ir, "__version__", "?")}


class BBox(BaseModel):
    lat: float
    lng: float
    half: float = 0.0036


@app.post("/landcover")
def landcover(b: BBox):
    """Keyless ESA WorldCover class distribution + tree-cover for a bbox.
    No infrared key required."""
    bbox = sc.bbox_of(sc._square(b.lat, b.lng, b.half))
    return cd.eo_worldcover(bbox)


@app.post("/landcover_overlay")
def landcover_overlay(b: BBox):
    """Keyless WorldCover colour overlay (base64 PNG) + Leaflet bounds."""
    bbox = sc.bbox_of(sc._square(b.lat, b.lng, b.half))
    r = cd.eo_worldcover_overlay(bbox, "output/_ovl_tmp.png")
    if "error" in r:
        return r
    with open(r["path"], "rb") as fh:
        r["image"] = base64.b64encode(fh.read()).decode()
    return r


@app.post("/run")
def run(req: Req):
    # Configure the analysis window + wind via scorecard module globals.
    sh = req.hour if req.hour < 23 else 22
    eh = req.hour + 1 if req.hour < 23 else 23
    sc.TIME_PERIOD = TimePeriod(start_month=req.month, start_day=req.day, start_hour=sh,
                                end_month=req.month, end_day=req.day, end_hour=eh)
    sc.WIND_SPEED = req.wind_speed
    sc.WIND_DIRECTION = req.wind_direction

    site = sc.Site(name=f"Probe {req.lat:.4f},{req.lng:.4f}", lat=req.lat, lon=req.lng,
                   polygon=sc._square(req.lat, req.lng, req.half),
                   weather_hint=("Rome" if req.veg_source == "city" else ""))
    keys = [k for k in req.analyses if k in sc.ANALYSES] or ["utci"]

    scen = {"baseline": False, "intervention": True}
    if req.scenario == "baseline":
        scen = {"baseline": False}
    elif req.scenario == "intervention":
        scen = {"intervention": True}

    client = ir.InfraredClient()
    try:
        bld = client.buildings.get_area(site.polygon).buildings
        weather = sc.fetch_utci_weather(client, site) if "utci" in keys else None
        veg = None
        if any(scen.values()):
            veg = (sc.city_vegetation(site) if req.veg_source == "city"
                   else client.vegetation.get_area(site.polygon).features)

        results: dict = {}
        for name, use_veg in scen.items():
            results[name] = {}
            v = veg if use_veg else None
            for k in keys:
                rq = sc.build_request(k, site, weather=weather if k == "utci" else None)
                area = client.run_area_and_wait(rq, site.polygon, buildings=bld, vegetation=v,
                                                max_tiles_override=req.max_tiles)
                scored = sc.score_result(k, area)
                scored["_area"] = area
                results[name][k] = scored

        path = sc.render_figure(site, keys, results, "output")
        with open(path, "rb") as fh:
            b64 = base64.b64encode(fh.read()).decode()

        rows = ""
        for name in results:
            u = results[name].get("utci")
            if u:
                rows += f"<tr><td>{name}</td><td>{u['utci'].line()}</td></tr>"
            for k in keys:
                if k == "utci":
                    continue
                sm = results[name].get(k, {}).get("summary")
                if sm:
                    rows += f"<tr><td>{name} · {k}</td><td>{sm.line()}</td></tr>"
        html = (f"<table><tr><th>Scenario</th><th>Metrics</th></tr>{rows}</table>"
                if rows else "")
        return {"figure": b64, "metrics_html": html, "analyses": keys,
                "scenarios": list(results)}
    finally:
        client.close()
