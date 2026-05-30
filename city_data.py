"""City open-data vegetation/ecology connectors, API-first, keyless.

Motivation
----------
The infrared.city SDK's vegetation comes from OpenStreetMap points whose rich
attributes are empty (`species`, `height`, `diameter_crown`, `leaf_type` are all
null). Municipal open data often carries those attributes, most importantly
*species*, so we can enrich the model with authoritative, keyless APIs.

Tiers (the "API-first" ladder)
------------------------------
Tier 1  CITY OPEN DATA  (this module, keyless, authoritative)
  - Rome      GeoServer WFS  : DIPAMB:AlberatureSpecieMVIII (street trees w/ GENERE, SPECIE)
  - Marseille Opendatasoft   : parks/gardens (per-tree register restricted)
  - Cork      CKAN           : cork-city-parks, tree-preservation-orders
Tier 2  SATELLITE / EO  (see eo_canopy stub, partly keyless)
  - ESA WorldCover 10 m landcover (open STAC, keyless)
  - Meta/WRI 1 m canopy height (AWS open data, keyless)  -> fills SDK null `height`
  - Sentinel-2 NDVI (Sentinel Hub / Planetary Computer, needs free key)
Tier 3  ROBOFLOW CV  (see roboflow_trees stub, needs ROBOFLOW_API_KEY + imagery)
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

try:  # load .env so standalone runs see the same keys the SDK does
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

TIMEOUT = 40


# --------------------------------------------------------------------------- #
# Rome, GeoServer WFS (street trees with species)
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
# Marseille, Opendatasoft Explore API v2.1 (parks / gardens)
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
# Cork, CKAN (parks; tree-preservation-orders)
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
# Tier 2 / Tier 3, documented stubs (need credentials / imagery)
# --------------------------------------------------------------------------- #
WORLDCOVER_CLASSES = {
    10: "Tree cover", 20: "Shrubland", 30: "Grassland", 40: "Cropland",
    50: "Built-up", 60: "Bare/sparse", 70: "Snow/ice", 80: "Water",
    90: "Wetland", 95: "Mangroves", 100: "Moss/lichen",
}


def eo_worldcover(bbox: tuple) -> dict:
    """ESA WorldCover 10 m land cover for a bbox via Microsoft Planetary Computer
    STAC (keyless). Returns the class distribution and the tree-cover fraction ,
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


def roboflow_trees(image_url: str, model: str | None = None,
                   api_key: str | None = None, confidence: int = 40) -> dict:
    """Detect trees/canopy in an aerial image via the Roboflow Inference API.

    Keys/model are read from the environment by default (see .env.example):
      ROBOFLOW_API_KEY, ROBOFLOW_MODEL (e.g. "detecting-tree-canopy/1" = project/version).
    `image_url` is a publicly reachable aerial/satellite tile. Returns Roboflow's
    predictions dict (boxes/polygons) to georeference into crown geometry.
    """
    import os
    api_key = api_key or os.getenv("ROBOFLOW_API_KEY")
    model = model or os.getenv("ROBOFLOW_MODEL")
    if not api_key or not model:
        raise RuntimeError("Set ROBOFLOW_API_KEY and ROBOFLOW_MODEL (e.g. 'detecting-tree-canopy/1') in .env")
    r = requests.post(f"https://detect.roboflow.com/{model}",
                      params={"api_key": api_key, "image": image_url, "confidence": confidence},
                      timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


# --- Web-Mercator slippy-tile helpers (keyless Esri World Imagery) ----------- #
ESRI_IMAGERY = ("https://server.arcgisonline.com/ArcGIS/rest/services/"
                "World_Imagery/MapServer/tile/{z}/{y}/{x}")


def _lonlat_to_tile(lon: float, lat: float, z: int) -> tuple[int, int]:
    import math
    n = 2 ** z
    xt = int((lon + 180.0) / 360.0 * n)
    yt = int((1.0 - math.log(math.tan(math.radians(lat))
                             + 1.0 / math.cos(math.radians(lat))) / math.pi) / 2.0 * n)
    return xt, yt


def _tile_bounds(xt: int, yt: int, z: int) -> tuple[float, float, float, float]:
    """Return (min_lon, min_lat, max_lon, max_lat) for slippy tile (xt, yt, z)."""
    import math
    n = 2 ** z

    def _lon(x):
        return x / n * 360.0 - 180.0

    def _lat(y):
        return math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))

    return _lon(xt), _lat(yt + 1), _lon(xt + 1), _lat(yt)


def roboflow_canopy(bbox: tuple, zoom: int = 18, model: str | None = None,
                    api_key: str | None = None, confidence: int = 25,
                    max_tiles: int = 12) -> dict:
    """Tier-3 CV vegetation source: detect tree canopies on keyless Esri World
    Imagery tiles across a bbox, then georeference each detection to a real
    lon/lat point with an estimated crown diameter (metres).

    bbox = (min_lon, min_lat, max_lon, max_lat). Imagery is keyless; only the
    Roboflow inference needs ROBOFLOW_API_KEY + ROBOFLOW_MODEL. Returns a
    FeatureCollection normalized to the same shape as the city connectors, with
    `crown_m` and `confidence` added per detection.
    """
    import math
    min_lon, min_lat, max_lon, max_lat = bbox
    x0, y1 = _lonlat_to_tile(min_lon, min_lat, zoom)   # SW
    x1, y0 = _lonlat_to_tile(max_lon, max_lat, zoom)   # NE
    tiles = [(xt, yt) for xt in range(min(x0, x1), max(x0, x1) + 1)
             for yt in range(min(y0, y1), max(y0, y1) + 1)]
    if len(tiles) > max_tiles:
        tiles = tiles[:max_tiles]
    feats, tiles_ok = [], 0
    for xt, yt in tiles:
        url = ESRI_IMAGERY.format(z=zoom, x=xt, y=yt)
        try:
            pred = roboflow_trees(url, model=model, api_key=api_key, confidence=confidence)
        except requests.HTTPError:
            continue
        tiles_ok += 1
        iw = pred.get("image", {}).get("width", 256)
        ih = pred.get("image", {}).get("height", 256)
        tlon0, tlat0, tlon1, tlat1 = _tile_bounds(xt, yt, zoom)
        # metres-per-degree at this latitude (for crown size in metres)
        midlat = (tlat0 + tlat1) / 2
        m_per_deg_lon = 111_320 * math.cos(math.radians(midlat))
        for p in pred.get("predictions", []):
            lon = tlon0 + (p["x"] / iw) * (tlon1 - tlon0)
            lat = tlat1 + (p["y"] / ih) * (tlat0 - tlat1)   # image y grows downward
            crown_deg = (p["width"] / iw) * (tlon1 - tlon0)
            feats.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [round(lon, 6), round(lat, 6)]},
                "properties": {
                    "source": "roboflow", "kind": "tree",
                    "species": None, "genus": None, "name": p.get("class"),
                    "crown_m": round(abs(crown_deg) * m_per_deg_lon, 1),
                    "confidence": round(p.get("confidence", 0), 3),
                },
            })
    return {"type": "FeatureCollection", "features": feats,
            "tiles_requested": len(tiles), "tiles_ok": tiles_ok, "zoom": zoom}


# --------------------------------------------------------------------------- #
# Sentinel Hub / Copernicus Data Space Ecosystem, Sentinel-2 NDVI (OAuth)
# --------------------------------------------------------------------------- #
SH_TOKEN_URL = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
SH_PROCESS_URL = "https://sh.dataspace.copernicus.eu/api/v1/process"

_NDVI_EVALSCRIPT = """//VERSION=3
function setup(){return{input:["B04","B08"],output:{bands:3}};}
function evaluatePixel(s){
  let ndvi=(s.B08-s.B04)/(s.B08+s.B04);
  if(ndvi<0.1) return[0.65,0.45,0.25];
  else if(ndvi<0.3) return[0.95,0.9,0.4];
  else if(ndvi<0.5) return[0.45,0.8,0.2];
  else return[0.0,0.45,0.0];
}"""


def sentinel_token(client_id: str | None = None, client_secret: str | None = None) -> str:
    """OAuth2 client-credentials token for Copernicus Data Space / Sentinel Hub.
    Reads SH_CLIENT_ID / SH_CLIENT_SECRET from env by default."""
    import os
    cid = client_id or os.getenv("SH_CLIENT_ID")
    cs = client_secret or os.getenv("SH_CLIENT_SECRET")
    if not cid or not cs:
        raise RuntimeError("Set SH_CLIENT_ID and SH_CLIENT_SECRET in .env")
    r = requests.post(SH_TOKEN_URL, timeout=TIMEOUT,
                      data={"grant_type": "client_credentials",
                            "client_id": cid, "client_secret": cs})
    r.raise_for_status()
    return r.json()["access_token"]


def sentinel_ndvi(bbox: tuple, start: str = "2024-06-01", end: str = "2024-09-01",
                  size: int = 256, max_cloud: int = 30, token: str | None = None) -> bytes:
    """Sentinel-2 L2A NDVI as a coloured PNG (bytes) for a bbox via the Process API.
    bbox = (min_lon, min_lat, max_lon, max_lat). Requires Sentinel Hub credentials."""
    token = token or sentinel_token()
    payload = {
        "input": {
            "bounds": {"bbox": list(bbox),
                       "properties": {"crs": "http://www.opengis.net/def/crs/EPSG/0/4326"}},
            "data": [{"type": "sentinel-2-l2a",
                      "dataFilter": {"timeRange": {"from": f"{start}T00:00:00Z", "to": f"{end}T00:00:00Z"},
                                     "maxCloudCoverage": max_cloud}}],
        },
        "output": {"width": size, "height": size,
                   "responses": [{"identifier": "default", "format": {"type": "image/png"}}]},
        "evalscript": _NDVI_EVALSCRIPT,
    }
    r = requests.post(SH_PROCESS_URL, json=payload, timeout=TIMEOUT,
                      headers={"Authorization": f"Bearer {token}"})
    r.raise_for_status()
    return r.content


# --------------------------------------------------------------------------- #
# GUS.earth (gAIa), urban-forest tree intelligence
# --------------------------------------------------------------------------- #
GUS_BASE = "https://backend.gus.earth"
GUS_TREES = "/api/v1/gus/trees"


def gus_trees(bbox: tuple | None = None, api_key: str | None = None,
              base: str | None = None, path: str = GUS_TREES, limit: int = 500) -> dict:
    """Authenticated client for the GUS.earth (gAIa) urban-forest API.

    Confirmed against https://backend.gus.earth/openapi.json (2026-05-30): the
    key goes in the `X-API-Key` header, trees live at `/api/v1/gus/trees`, and a
    bounding box is passed as `lnglatbounds`. Reads GUS_API_KEY / GUS_API_BASE
    from env. Returns the JSON response (a list of tree records).
    """
    import os
    api_key = api_key or os.getenv("GUS_API_KEY")
    base = base or os.getenv("GUS_API_BASE", GUS_BASE)
    if not api_key:
        raise RuntimeError("Set GUS_API_KEY in .env (see https://backend.gus.earth/docs)")
    params: dict = {"limit": limit}
    if bbox:  # lnglatbounds = min_lon,min_lat,max_lon,max_lat
        params["lnglatbounds"] = ",".join(str(x) for x in bbox)
    r = requests.get(f"{base.rstrip('/')}{path}", timeout=TIMEOUT,
                     headers={"X-API-Key": api_key}, params=params)
    r.raise_for_status()
    return r.json()


# Default verification bbox: Villa Doria Pamphilj park, Rome (dense real canopy).
_DEFAULT_BBOX = (12.4420, 41.8840, 12.4480, 41.8875)


def _parse_bbox(s: Optional[str]) -> tuple:
    if not s:
        return _DEFAULT_BBOX
    parts = [float(x) for x in s.split(",")]
    if len(parts) != 4:
        raise ValueError("--bbox must be 'min_lon,min_lat,max_lon,max_lat'")
    return tuple(parts)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Vegetation/ecology connectors (city + EO + CV)")
    ap.add_argument("source", choices=list(PROVIDERS) + ["roboflow", "sentinel", "gus", "worldcover"])
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--bbox", help="min_lon,min_lat,max_lon,max_lat (EO/CV sources)")
    ap.add_argument("--zoom", type=int, default=18, help="Esri imagery zoom for roboflow")
    args = ap.parse_args(argv)

    if args.source == "roboflow":
        fc = roboflow_canopy(_parse_bbox(args.bbox), zoom=args.zoom)
        feats = fc["features"]
        print(f"roboflow: {len(feats)} canopies from {fc['tiles_ok']}/{fc['tiles_requested']} "
              f"tiles @ z{fc['zoom']}")
        for f in feats[:5]:
            p = f["properties"]; c = f["geometry"]["coordinates"]
            print(f"  - {p['name']} | ({c[1]:.5f},{c[0]:.5f}) | crown~{p['crown_m']}m | conf={p['confidence']}")
        return 0
    if args.source == "worldcover":
        print(json.dumps(eo_worldcover(_parse_bbox(args.bbox)), indent=2))
        return 0
    if args.source == "sentinel":
        png = sentinel_ndvi(_parse_bbox(args.bbox))
        out = "output/ndvi_test.png"
        with open(out, "wb") as fh:
            fh.write(png)
        print(f"sentinel: NDVI PNG written to {out} ({len(png)} bytes)")
        return 0
    if args.source == "gus":
        print(json.dumps(gus_trees(_parse_bbox(args.bbox)), indent=2)[:1500])
        return 0

    fc = PROVIDERS[args.source](limit=args.limit)
    feats = fc.get("features", [])
    print(f"{args.source}: {len(feats)} features")
    with_species = [f for f in feats if f["properties"].get("species")]
    print(f"  with species: {len(with_species)}")
    for f in feats[:5]:
        p = f["properties"]
        g = (f.get("geometry") or {}).get("type", "wkt/none")
        print(f"  - {p.get('kind')} | {g} | species={p.get('species')} | name={p.get('name')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
