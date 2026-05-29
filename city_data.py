"""City open-data vegetation/ecology connectors — API-first, keyless.

Motivation
----------
The infrared.city SDK's vegetation comes from OpenStreetMap points whose rich
attributes are empty (`species`, `height`, `diameter_crown`, `leaf_type` are all
null). Municipal open data often carries those attributes — most importantly
*species* — so we can enrich the model with authoritative, keyless APIs.

Tiers (the "API-first" ladder)
------------------------------
Tier 1  CITY OPEN DATA  (this module — keyless, authoritative)
  - Rome      GeoServer WFS  : DIPAMB:AlberatureSpecieMVIII (street trees w/ GENERE, SPECIE)
  - Marseille Opendatasoft   : parks/gardens (per-tree register restricted)
  - Cork      CKAN           : cork-city-parks, tree-preservation-orders
Tier 2  SATELLITE / EO  (see eo_canopy stub — partly keyless)
  - ESA WorldCover 10 m landcover (open STAC, keyless)
  - Meta/WRI 1 m canopy height (AWS open data, keyless)  -> fills SDK null `height`
  - Sentinel-2 NDVI (Sentinel Hub / Planetary Computer — needs free key)
Tier 3  ROBOFLOW CV  (see roboflow_trees stub — needs ROBOFLOW_API_KEY + imagery)
  - tree/canopy detection on aerial tiles -> crown polygons, species/health

Each Tier-1 provider returns a GeoJSON-style FeatureCollection normalized to:
  {"type":"FeatureCollection","features":[{"geometry":..., "properties":{
      "source": <city>, "kind": "tree"|"park", "species": str|None,
      "genus": str|None, "name": str|None }}]}

Usage:
  python city_data.py rome      [--limit 50]
  python city_data.py cork
  python city_data.py marseille [--limit 50]
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from typing import Optional

import requests

TIMEOUT = 40


# --------------------------------------------------------------------------- #
# Rome — GeoServer WFS (street trees with species)
# --------------------------------------------------------------------------- #
ROME_WFS = "https://geoportale.comune.roma.it/geoserver/ows"
ROME_TREES_LAYER = "DIPAMB:AlberatureSpecieMVIII"


def rome_street_trees(limit: int = 200, bbox: Optional[tuple] = None) -> dict:
    """Street trees with genus/species via WFS GetFeature (GeoJSON, EPSG:4326)."""
    params = {
        "service": "WFS", "version": "2.0.0", "request": "GetFeature",
        "typeNames": ROME_TREES_LAYER, "count": str(limit),
        "outputFormat": "application/json", "srsName": "EPSG:4326",
    }
    if bbox:  # (minlon, minlat, maxlon, maxlat) -> WFS 2.0 lat/lon axis order
        miny, minx, maxy, maxx = bbox[1], bbox[0], bbox[3], bbox[2]
        params["bbox"] = f"{miny},{minx},{maxy},{maxx},urn:ogc:def:crs:EPSG::4326"
    r = requests.get(ROME_WFS, params=params, timeout=TIMEOUT)
    r.raise_for_status()
    raw = r.json()
    feats = []
    for f in raw.get("features", []):
        p = f.get("properties", {})
        feats.append({
            "type": "Feature", "geometry": f.get("geometry"),
            "properties": {
                "source": "rome", "kind": "tree",
                "species": p.get("SPECIE"), "genus": p.get("GENERE"),
                "name": p.get("NOME"),
            },
        })
    return {"type": "FeatureCollection", "features": feats}


# --------------------------------------------------------------------------- #
# Marseille — Opendatasoft Explore API v2.1 (parks / gardens)
# --------------------------------------------------------------------------- #
MARS_ODS = "https://data.ampmetropole.fr/api/explore/v2.1"
MARS_PARKS = "parc-et-jardin-bd-topo-zone-dactivite-ou-dinteret"


def marseille_parks(limit: int = 200) -> dict:
    """Parks/gardens polygons via the Opendatasoft GeoJSON export."""
    url = f"{MARS_ODS}/catalog/datasets/{MARS_PARKS}/exports/geojson"
    r = requests.get(url, params={"limit": str(limit)}, timeout=TIMEOUT)
    r.raise_for_status()
    raw = r.json()
    feats = []
    for f in raw.get("features", []):
        p = f.get("properties", {})
        feats.append({
            "type": "Feature", "geometry": f.get("geometry"),
            "properties": {
                "source": "marseille", "kind": "park",
                "species": None, "genus": None,
                "name": p.get("toponyme") or p.get("nature_detaillee"),
            },
        })
    return {"type": "FeatureCollection", "features": feats}


# --------------------------------------------------------------------------- #
# Cork — CKAN (parks; tree-preservation-orders)
# --------------------------------------------------------------------------- #
CORK_CKAN = "https://data.corkcity.ie/api/3/action"


def _cork_csv_resource(dataset_id: str) -> Optional[str]:
    r = requests.get(f"{CORK_CKAN}/package_show", params={"id": dataset_id}, timeout=TIMEOUT)
    r.raise_for_status()
    for res in r.json()["result"].get("resources", []):
        if (res.get("format") or "").upper() == "CSV":
            return res.get("url")
    return None


def cork_parks(limit: int = 200) -> dict:
    """Cork parks from the CKAN CSV resource (geometry as WKT/columns if present)."""
    url = _cork_csv_resource("cork-city-parks")
    if not url:
        return {"type": "FeatureCollection", "features": [], "note": "no CSV resource"}
    r = requests.get(url, timeout=TIMEOUT)
    r.raise_for_status()
    rows = list(csv.DictReader(io.StringIO(r.text)))
    feats = []
    for row in rows[:limit]:
        name = row.get("NAME") or row.get("Name") or row.get("name")
        # Geometry may be WKT in a 'the_geom'/'geometry'/'WKT' column; keep raw for now.
        wkt = row.get("the_geom") or row.get("geometry") or row.get("WKT")
        feats.append({
            "type": "Feature", "geometry": {"wkt": wkt} if wkt else None,
            "properties": {"source": "cork", "kind": "park",
                           "species": None, "genus": None, "name": name},
        })
    return {"type": "FeatureCollection", "features": feats}


PROVIDERS = {
    "rome": rome_street_trees,
    "marseille": marseille_parks,
    "cork": cork_parks,
}


# --------------------------------------------------------------------------- #
# Tier 2 / Tier 3 — documented stubs (need credentials / imagery)
# --------------------------------------------------------------------------- #
WORLDCOVER_CLASSES = {
    10: "Tree cover", 20: "Shrubland", 30: "Grassland", 40: "Cropland",
    50: "Built-up", 60: "Bare/sparse", 70: "Snow/ice", 80: "Water",
    90: "Wetland", 95: "Mangroves", 100: "Moss/lichen",
}


def eo_worldcover(bbox: tuple) -> dict:
    """ESA WorldCover 10 m land cover for a bbox via Microsoft Planetary Computer
    STAC (keyless). Returns the class distribution and the tree-cover fraction —
    an authoritative vegetation-density signal to weight/validate canopy.

    bbox = (min_lon, min_lat, max_lon, max_lat)
    """
    import numpy as np
    import planetary_computer
    import pystac_client
    import rasterio
    from rasterio.windows import from_bounds

    cat = pystac_client.Client.open(
        "https://planetarycomputer.microsoft.com/api/stac/v1",
        modifier=planetary_computer.sign_inplace,
    )
    items = list(cat.search(collections=["esa-worldcover"], bbox=list(bbox)).items())
    if not items:
        return {"error": "no WorldCover item for bbox"}
    item = items[0]
    href = item.assets["map"].href
    with rasterio.open(href) as ds:
        win = from_bounds(*bbox, transform=ds.transform)
        arr = ds.read(1, window=win)
    classes, counts = np.unique(arr, return_counts=True)
    total = int(counts.sum()) or 1
    dist = {WORLDCOVER_CLASSES.get(int(c), str(int(c))): round(float(n) / total * 100, 1)
            for c, n in zip(classes, counts)}
    return {
        "item": item.id,
        "tree_cover_pct": dist.get("Tree cover", 0.0),
        "built_up_pct": dist.get("Built-up", 0.0),
        "class_distribution": dict(sorted(dist.items(), key=lambda kv: -kv[1])),
    }


WORLDCOVER_COLORS = {  # official ESA WorldCover palette (RGB)
    10: (0, 100, 0), 20: (255, 187, 34), 30: (255, 255, 76), 40: (240, 150, 255),
    50: (250, 0, 0), 60: (180, 180, 180), 70: (240, 240, 240), 80: (0, 100, 200),
    90: (0, 150, 160), 95: (0, 207, 117), 100: (250, 230, 160),
}


def eo_worldcover_overlay(bbox: tuple, out_path: str) -> dict:
    """Render ESA WorldCover for a bbox as a colour PNG (keyless) and return the
    geographic bounds, ready for a Leaflet imageOverlay. Demonstrates a real
    geo-referenced overlay with no API key."""
    import numpy as np
    import planetary_computer
    import pystac_client
    import rasterio
    from rasterio.windows import from_bounds, bounds as win_bounds
    from PIL import Image

    cat = pystac_client.Client.open(
        "https://planetarycomputer.microsoft.com/api/stac/v1",
        modifier=planetary_computer.sign_inplace,
    )
    items = list(cat.search(collections=["esa-worldcover"], bbox=list(bbox)).items())
    if not items:
        return {"error": "no WorldCover item"}
    with rasterio.open(items[0].assets["map"].href) as ds:
        win = from_bounds(*bbox, transform=ds.transform)
        arr = ds.read(1, window=win)
        left, bottom, right, top = win_bounds(win, ds.transform)
    h, w = arr.shape
    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    for cls, (r, g, b) in WORLDCOVER_COLORS.items():
        m = arr == cls
        rgba[m] = (r, g, b, 200)
    Image.fromarray(rgba, "RGBA").save(out_path)
    # Leaflet bounds: [[south, west], [north, east]]
    return {"path": out_path, "bounds": [[bottom, left], [top, right]],
            "size": [w, h]}


def roboflow_trees(image_path_or_url: str, model_id: str, api_key: str):
    """Detect trees/canopy from an aerial tile via the Roboflow Inference API.

    POSTs the image to https://detect.roboflow.com/<model_id>?api_key=...,
    returns detections to be georeferenced into crown polygons. Requires a
    Roboflow API key, a chosen model, and an imagery source.
    """
    raise NotImplementedError("Roboflow tier: needs ROBOFLOW_API_KEY + model + imagery.")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="City open-data vegetation connectors")
    ap.add_argument("city", choices=list(PROVIDERS))
    ap.add_argument("--limit", type=int, default=50)
    args = ap.parse_args(argv)

    fc = PROVIDERS[args.city](limit=args.limit)
    feats = fc.get("features", [])
    print(f"{args.city}: {len(feats)} features")
    with_species = [f for f in feats if f["properties"].get("species")]
    print(f"  with species: {len(with_species)}")
    for f in feats[:5]:
        p = f["properties"]
        g = (f.get("geometry") or {}).get("type", "wkt/none")
        print(f"  - {p.get('kind')} | {g} | species={p.get('species')} | name={p.get('name')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
