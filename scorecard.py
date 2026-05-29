"""Regenerative Microclimate Scorecard — infrared.city SDK 0.4.9 demo.

A single-file "killer app" for the infrared.city Buildathon that:

  1. Runs the three focus analyses — UTCI (thermal comfort), wind, and solar —
     over a real site polygon, in one workflow, via the new SDK.
  2. Compares a *baseline* (bare site) against a *regenerative intervention*
     (real tree canopy fetched and injected through the SDK's vegetation
     service) — the same baseline-vs-intervention logic as the AT6012 toolkit,
     now driven by submit-and-run analyses instead of pre-baked simulations.
  3. Scores each result with the ported regenerative metrics
     (heat-stress %, Thermal Assembly Complexity Index) and prints the delta.
  4. Renders a one-page scorecard figure for the wrap-up demo.

Migration note (old toolkit -> this):
  - infrared_config.py + infrared_client.py  ->  ir.InfraredClient() (env key)
  - get_simulation_results(sim_id)            ->  run_area_and_wait(request, polygon)
  - UTCI-only                                 ->  UTCI + wind + solar
  - manual JSON -> DataFrame                  ->  AreaResult.merged_grid (numpy)
  - thermal_analysis.py metrics               ->  regenerative_metrics.py (kept, grid-native)

Usage:
  python scorecard.py                 # SAFE: preview tiling + validate, no billing
  python scorecard.py --run           # LIVE: submit billable analyses, build scorecard
  python scorecard.py --run --analyses utci          # scope which analyses run
  python scorecard.py --run --scenario baseline      # skip the vegetation run
  python scorecard.py --run --max-tiles 1            # hard cap tiles (cost guard)
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from typing import Callable, Optional

import infrared_sdk as ir
from infrared_sdk.models import TimePeriod

import regenerative_metrics as rm


# --------------------------------------------------------------------------- #
# Site definition — Marseille (AT6012 case study), small polygon (~1 tile).
# A GeoJSON Polygon: coordinates are [[ [lon, lat], ... ]] (closed ring).
# --------------------------------------------------------------------------- #
@dataclass
class Site:
    name: str
    lat: float
    lon: float
    polygon: dict
    weather_hint: str = ""  # substring to prefer when choosing a weather station


def _square(lat: float, lon: float, half_lat_deg: float) -> dict:
    """GeoJSON square centred on (lat,lon), roughly equal-sided in metres."""
    # Compensate longitude for latitude so the box is ~square on the ground.
    import math
    half_lon_deg = half_lat_deg / max(math.cos(math.radians(lat)), 1e-6)
    ring = [
        [lon - half_lon_deg, lat - half_lat_deg],
        [lon + half_lon_deg, lat - half_lat_deg],
        [lon + half_lon_deg, lat + half_lat_deg],
        [lon - half_lon_deg, lat + half_lat_deg],
        [lon - half_lon_deg, lat - half_lat_deg],
    ]
    return {"type": "Polygon", "coordinates": [ring]}


def marseille_site() -> Site:
    lat, lon = 43.2951, 5.3739  # Marseille centre (Vieux-Port area)
    return Site(name="Marseille (Vieux-Port)", lat=lat, lon=lon,
                polygon=_square(lat, lon, 0.0036),  # ~800 m site (enlarged case study)
                weather_hint="Marseille")


def cork_site() -> Site:
    # CCAE / Nano Nagle Place, Douglas Street, Cork.
    lat, lon = 51.8936, -8.4759
    return Site(name="Cork — Nano Nagle Place (Douglas St)", lat=lat, lon=lon,
                polygon=_square(lat, lon, 0.0036),  # ~800 m site (larger area)
                weather_hint="Cork")


def rome_site() -> Site:
    # Municipio VIII (Garbatella / Ostiense) — where the city street-tree
    # register (DIPAMB:AlberatureSpecieMVIII, 58 species) has coverage.
    lat, lon = 41.8453, 12.4905
    return Site(name="Rome — Municipio VIII (Garbatella)", lat=lat, lon=lon,
                polygon=_square(lat, lon, 0.0036),  # ~800 m site
                weather_hint="Rome")


SITES = {"marseille": marseille_site, "cork": cork_site, "rome": rome_site}


def bbox_of(polygon: dict) -> tuple:
    ring = polygon["coordinates"][0]
    lons = [p[0] for p in ring]; lats = [p[1] for p in ring]
    return (min(lons), min(lats), max(lons), max(lats))


def city_vegetation(site: Site) -> dict:
    """Vegetation mapping sourced from CITY open data (species-tagged), formatted
    for SDK injection. Only Rome exposes per-tree points with species today."""
    import city_data as cd
    if "rome" not in site.name.lower() and site.weather_hint != "Rome":
        return {}
    fc = cd.rome_street_trees(limit=5000, bbox=bbox_of(site.polygon))
    veg = {}
    for i, f in enumerate(fc.get("features", [])):
        if not f.get("geometry"):
            continue
        p = f["properties"]
        veg[f"rome/{i}"] = {
            "type": "Feature", "id": f"rome/{i}", "geometry": f["geometry"],
            "properties": {"natural": "tree", "species": p.get("species"),
                           "genus": p.get("genus"), "leaf_type": None, "leaf_cycle": None,
                           "height": None, "circumference": None, "diameter_crown": None},
        }
    return veg


# Summer afternoon window (Marseille August baseline, matching the AT6012 toolkit).
TIME_PERIOD = TimePeriod(
    start_month=8, start_day=15, start_hour=9,
    end_month=8, end_day=15, end_hour=18,
)

# Prevailing Mistral wind for Marseille: NW (~315°), ~5 m/s.
WIND_SPEED = 5
WIND_DIRECTION = 315


# --------------------------------------------------------------------------- #
# Analysis registry — maps a short key to (request builder, preview type, unit).
# --------------------------------------------------------------------------- #
def fetch_utci_weather(client: ir.InfraredClient, site: Site) -> dict:
    """Fetch real EPW weather for the site and shape it into UTCI input arrays.

    The thermal-comfort-index analysis requires hourly weather series; without
    them the API rejects the job with HTTP 400. We pull the nearest station,
    filter to the analysis window, and transpose WeatherDataPoint objects into
    the per-field lists UtciModelRequest expects.
    """
    files = client.weather.get_weather_file_from_location(lat=site.lat, lon=site.lon)
    hint = site.weather_hint
    pick = next((f for f in files if hint and hint in f.get("fileName", "")), files[0])
    points = client.weather.filter_weather_data(identifier=pick["uuid"], time_period=TIME_PERIOD)
    print(f"  weather: {pick['fileName']} ({len(points)} hourly points)")
    return {
        "dry_bulb_temperature": [p.dryBulbTemperature for p in points],
        "wind_speed": [p.windSpeed for p in points],
        "relative_humidity": [p.relativeHumidity for p in points],
        "horizontal_infrared_radiation_intensity": [p.horizontalInfraredRadiationIntensity for p in points],
        "diffuse_horizontal_radiation": [p.diffuseHorizontalRadiation for p in points],
        "direct_normal_radiation": [p.directNormalRadiation for p in points],
        "global_horizontal_radiation": [p.globalHorizontalRadiation for p in points],
    }


def build_request(key: str, site: Site, weather: Optional[dict] = None):
    if key == "utci":
        if not weather:
            raise ValueError("UTCI request requires weather arrays (call fetch_utci_weather)")
        return ir.UtciModelRequest(
            latitude=site.lat, longitude=site.lon,
            analysis_type="thermal-comfort-index", time_period=TIME_PERIOD,
            **weather,
        )
    if key == "wind":
        return ir.WindModelRequest(
            analysis_type="wind-speed",
            wind_speed=WIND_SPEED, wind_direction=WIND_DIRECTION,
            latitude=site.lat, longitude=site.lon,
        )
    if key == "solar":
        return ir.SolarModelRequest(
            latitude=site.lat, longitude=site.lon,
            analysis_type="direct-sun-hours", time_period=TIME_PERIOD,
        )
    raise ValueError(f"unknown analysis '{key}'")


ANALYSES = {
    "utci": {"label": "UTCI (thermal comfort)", "preview_type": "thermal-comfort-index", "unit": "°C"},
    "wind": {"label": "Wind speed", "preview_type": "wind-speed", "unit": "m/s"},
    "solar": {"label": "Direct sun hours", "preview_type": "direct-sun-hours", "unit": "h"},
}


# --------------------------------------------------------------------------- #
# Preview (cheap) — report tiling per analysis without submitting jobs.
# --------------------------------------------------------------------------- #
def preview(client: ir.InfraredClient, site: Site, keys: list[str]) -> int:
    print(f"\nPREVIEW — {site.name}")
    print(f"  polygon centroid: {site.lat:.4f}, {site.lon:.4f}")
    total = 0
    for k in keys:
        meta = ANALYSES[k]
        try:
            p = client.preview_area(site.polygon, analysis_type=meta["preview_type"])
            tiles = getattr(p, "tile_count", None) or getattr(p, "num_tiles", None) or p
            print(f"  {meta['label']:<26} -> {tiles} tile(s)  (grid: {meta['preview_type']})")
            if isinstance(tiles, int):
                total += tiles
        except Exception as exc:  # noqa: BLE001
            print(f"  {meta['label']:<26} -> preview error: {exc}")
    print(f"\n  Validated {len(keys)} analysis request(s). No jobs submitted, no quota used.")
    print("  Run live with:  python scorecard.py --run")
    return total


# --------------------------------------------------------------------------- #
# Live run — vegetation fetch + baseline/intervention area runs + scoring.
# --------------------------------------------------------------------------- #
def progress_printer(tag: str) -> Callable:
    last = {"t": 0.0}

    def _cb(state) -> None:
        now = time.monotonic()
        if now - last["t"] < 1.0:
            return
        last["t"] = now
        done = getattr(state, "completed", None)
        total = getattr(state, "total", None)
        if done is not None and total:
            print(f"    [{tag}] {done}/{total} jobs", flush=True)

    return _cb


def score_result(key: str, result) -> dict:
    grid = result.merged_grid
    meta = ANALYSES[key]
    out = {"summary": rm.summarize_grid(grid, meta["label"], meta["unit"])}
    if key == "utci":
        out["utci"] = rm.utci_stats(grid)
        out["assembly"] = rm.thermal_assembly_index(grid)
    return out


def run_live(client: ir.InfraredClient, site: Site, keys: list[str],
             scenario: str, max_tiles: Optional[int], out_dir: str,
             veg_source: str = "sdk") -> int:
    scenarios = {"baseline": False, "intervention": True}
    if scenario == "baseline":
        scenarios = {"baseline": False}
    elif scenario == "intervention":
        scenarios = {"intervention": True}

    # Fetch real buildings once — context geometry for ALL scenarios.
    # (thermal-comfort-index requires geometry; buildings also shape wind/solar.)
    print(f"\nFetching buildings for {site.name} ...", flush=True)
    area_bld = client.buildings.get_area(site.polygon)
    bld_features = area_bld.buildings
    print(f"  {area_bld.total_buildings} buildings found ({area_bld.execution_time:.1f}s)")

    # Fetch vegetation once if any intervention scenario is requested.
    veg_features = None
    if any(scenarios.values()):
        if veg_source == "city":
            print(f"\nFetching CITY open-data vegetation (species-tagged) for {site.name} ...", flush=True)
            veg_features = city_vegetation(site)
            species = {v["properties"].get("species") for v in veg_features.values()}
            print(f"  {len(veg_features)} city trees, {len(species)} species "
                  f"(e.g. {', '.join([s for s in list(species)[:3] if s])})")
        else:
            print(f"\nFetching SDK (OSM) vegetation for {site.name} ...", flush=True)
            area_veg = client.vegetation.get_area(site.polygon)
            veg_features = area_veg.features
            print(f"  {area_veg.total_trees} trees found "
                  f"({len(veg_features)} feature group(s), {area_veg.execution_time:.1f}s)")

    # Fetch weather once if UTCI is requested (required input for thermal-comfort).
    weather = None
    if "utci" in keys:
        print(f"\nFetching weather for {site.name} ...", flush=True)
        weather = fetch_utci_weather(client, site)

    results: dict[str, dict] = {}  # results[scenario][analysis] = scored dict
    for scen_name, use_veg in scenarios.items():
        results[scen_name] = {}
        veg = veg_features if use_veg else None
        for k in keys:
            req = build_request(k, site, weather=weather if k == "utci" else None)
            print(f"\n[{scen_name}] running {ANALYSES[k]['label']} ...", flush=True)
            area = client.run_area_and_wait(
                req, site.polygon,
                buildings=bld_features,
                vegetation=veg,
                max_tiles_override=max_tiles,
                on_progress=progress_printer(f"{scen_name}:{k}"),
            )
            scored = score_result(k, area)
            scored["_area"] = area
            results[scen_name][k] = scored
            print("    " + scored["summary"].line())
            if "utci" in scored:
                print("    " + scored["utci"].line())
                print("    " + scored["assembly"].line())

    print_scorecard(site, keys, results)
    try:
        fig_path = render_figure(site, keys, results, out_dir)
        print(f"\nScorecard figure written: {fig_path}")
    except Exception as exc:  # noqa: BLE001
        print(f"\n(figure skipped: {exc})")
    return 0


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #
def print_scorecard(site: Site, keys: list[str], results: dict) -> None:
    print("\n" + "=" * 70)
    print(f"REGENERATIVE MICROCLIMATE SCORECARD — {site.name}")
    print("=" * 70)

    has_both = "baseline" in results and "intervention" in results
    if "utci" in keys:
        for scen in results:
            s = results[scen].get("utci")
            if s:
                print(f"\n[{scen}]  {s['utci'].line()}")
                print(f"          {s['assembly'].line()}")
        if has_both and results["baseline"].get("utci") and results["intervention"].get("utci"):
            b, i = results["baseline"]["utci"], results["intervention"]["utci"]
            d_heat = i["utci"].heat_stress_pct - b["utci"].heat_stress_pct
            d_taci = rm.pct_delta(b["assembly"].index, i["assembly"].index)
            print("\n  REGENERATIVE DELTA (intervention vs baseline):")
            print(f"    heat-stress area : {d_heat:+.1f} pts   "
                  f"({'improved' if d_heat < 0 else 'worse'})")
            print(f"    assembly complexity (TACI): {d_taci:+.1f}%   "
                  f"({'increased — regenerative' if d_taci > 15 else 'insufficient gain'})")

    for k in keys:
        if k == "utci":
            continue
        print()
        for scen in results:
            s = results[scen].get(k)
            if s:
                print(f"  [{scen}] {s['summary'].line()}")


def render_figure(site: Site, keys: list[str], results: dict, out_dir: str) -> str:
    import os
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    scens = list(results.keys())
    n = len(keys)
    fig, axes = plt.subplots(len(scens), n, figsize=(4.2 * n, 3.8 * len(scens)),
                             squeeze=False)
    fig.suptitle(f"Regenerative Microclimate Scorecard — {site.name}",
                 fontsize=14, fontweight="bold")
    cmaps = {"utci": "RdYlBu_r", "wind": "viridis", "solar": "magma"}
    for r, scen in enumerate(scens):
        for c, k in enumerate(keys):
            ax = axes[r][c]
            scored = results[scen].get(k)
            if not scored:
                ax.axis("off")
                continue
            area = scored["_area"]
            grid = np.asarray(area.merged_grid, dtype=float)
            extent = area.bounds if area.bounds else None
            im = ax.imshow(grid, origin="lower", cmap=cmaps.get(k, "viridis"),
                           extent=extent, aspect="auto")
            fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
            ax.set_title(f"{scen} — {ANALYSES[k]['label']}", fontsize=10)
            ax.set_xticks([])
            ax.set_yticks([])
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    os.makedirs(out_dir, exist_ok=True)
    slug = site.name.split("(")[0].split("—")[0].strip().lower().replace(" ", "_")
    path = os.path.join(out_dir, f"scorecard_{slug}.png")
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Regenerative Microclimate Scorecard")
    ap.add_argument("--run", action="store_true",
                    help="Submit LIVE billable analyses (default is safe preview only).")
    ap.add_argument("--analyses", default="utci,wind,solar",
                    help="Comma list from: utci,wind,solar (default: all).")
    ap.add_argument("--scenario", default="both",
                    choices=["both", "baseline", "intervention"],
                    help="Which scenarios to run (default: both).")
    ap.add_argument("--max-tiles", type=int, default=None,
                    help="Hard cap on tiles per area run (cost guard).")
    ap.add_argument("--out", default="output", help="Output directory for figures.")
    ap.add_argument("--site", default="marseille", choices=list(SITES),
                    help="Which site to analyse (default: marseille).")
    ap.add_argument("--veg-source", default="sdk", choices=["sdk", "city"],
                    help="Intervention vegetation source: SDK/OSM or city open data (default: sdk).")
    args = ap.parse_args(argv)

    keys = [k.strip() for k in args.analyses.split(",") if k.strip()]
    bad = [k for k in keys if k not in ANALYSES]
    if bad:
        print(f"Unknown analyses: {bad}. Choose from {list(ANALYSES)}.")
        return 2

    site = SITES[args.site]()
    try:
        client = ir.InfraredClient()  # reads INFRARED_API_KEY (.env auto-loaded)
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: could not construct client: {exc}")
        print("  Set INFRARED_API_KEY (see .env.example) and retry.")
        return 1

    try:
        if args.run:
            return run_live(client, site, keys, args.scenario, args.max_tiles,
                            args.out, veg_source=args.veg_source)
        return 0 if preview(client, site, keys) is not None else 1
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main())
