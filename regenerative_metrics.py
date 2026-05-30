"""Regenerative microclimate metrics, grid-native.

This is the SDK-agnostic intellectual core ported from the AT6012 infrared
toolkit (`thermal_analysis.py`, UCC School of Architecture, Oct 2025).

The original metrics operated on a DataFrame of (x, y, utci) point samples
returned by the legacy REST client. The new infrared-sdk 0.4.9 returns a
clean 2-D numpy grid (`AreaResult.merged_grid`, NaN outside the polygon), so
these reimplementations operate directly on that grid, simpler and faster
(true gradients via np.gradient instead of nearest-neighbour estimates).

References:
  Błażejczyk et al. (2013), Universal Thermal Climate Index (UTCI)
  Alberti (2016), Cities That Think Like Planets (assembly complexity)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np


# --------------------------------------------------------------------------- #
# UTCI thermal-stress scale (°C), Błażejczyk et al. (2013)
# --------------------------------------------------------------------------- #
UTCI_COMFORT_LOWER = 9.0
UTCI_COMFORT_UPPER = 26.0
UTCI_MODERATE_HEAT = 32.0
UTCI_STRONG_HEAT = 38.0
UTCI_VERY_STRONG_HEAT = 46.0

UTCI_BANDS = [
    (-40.0, "Extreme cold stress"),
    (-27.0, "Very strong cold stress"),
    (-13.0, "Strong cold stress"),
    (0.0, "Moderate cold stress"),
    (9.0, "Slight cold stress"),
    (26.0, "No thermal stress (comfortable)"),
    (32.0, "Moderate heat stress"),
    (38.0, "Strong heat stress"),
    (46.0, "Very strong heat stress"),
    (float("inf"), "Extreme heat stress"),
]


def categorize_utci(value: float) -> str:
    """Map a single UTCI value to its thermal-stress band."""
    for upper, label in UTCI_BANDS:
        if value < upper:
            return label
    return "Extreme heat stress"


def _finite(grid: np.ndarray) -> np.ndarray:
    """Flatten to finite values only (drops NaN gaps / outside-polygon cells)."""
    arr = np.asarray(grid, dtype=float).ravel()
    return arr[np.isfinite(arr)]


@dataclass
class GridSummary:
    """Generic descriptive stats for any analysis grid (wind, solar, ...)."""

    analysis: str
    unit: str
    mean: float
    minimum: float
    maximum: float
    std: float
    coverage: float  # fraction of grid cells with finite data

    def line(self) -> str:
        return (
            f"{self.analysis:<22} mean={self.mean:7.2f} {self.unit}  "
            f"range=[{self.minimum:.2f}, {self.maximum:.2f}]  "
            f"σ={self.std:.2f}  coverage={self.coverage*100:.0f}%"
        )


def summarize_grid(grid: np.ndarray, analysis: str, unit: str = "") -> GridSummary:
    vals = _finite(grid)
    total = np.asarray(grid).size or 1
    if vals.size == 0:
        return GridSummary(analysis, unit, float("nan"), float("nan"),
                           float("nan"), float("nan"), 0.0)
    return GridSummary(
        analysis=analysis,
        unit=unit,
        mean=float(vals.mean()),
        minimum=float(vals.min()),
        maximum=float(vals.max()),
        std=float(vals.std()),
        coverage=float(vals.size) / float(total),
    )


@dataclass
class UTCIStats:
    mean: float
    comfortable_pct: float
    heat_stress_pct: float  # UTCI > 26 °C (moderate heat and above)
    severe_heat_pct: float  # UTCI > 38 °C (strong heat and above)
    dominant_band: str

    def line(self) -> str:
        return (
            f"UTCI mean={self.mean:.1f}°C  comfortable={self.comfortable_pct:.1f}%  "
            f"heat-stress={self.heat_stress_pct:.1f}%  severe={self.severe_heat_pct:.1f}%  "
            f"[{self.dominant_band}]"
        )


def utci_stats(grid: np.ndarray) -> UTCIStats:
    """Thermal-comfort breakdown of a UTCI grid."""
    vals = _finite(grid)
    if vals.size == 0:
        return UTCIStats(float("nan"), 0.0, 0.0, 0.0, "no data")
    comfortable = np.mean((vals >= UTCI_COMFORT_LOWER) & (vals <= UTCI_COMFORT_UPPER))
    heat = np.mean(vals > UTCI_COMFORT_UPPER)
    severe = np.mean(vals > UTCI_STRONG_HEAT)
    return UTCIStats(
        mean=float(vals.mean()),
        comfortable_pct=float(comfortable * 100),
        heat_stress_pct=float(heat * 100),
        severe_heat_pct=float(severe * 100),
        dominant_band=categorize_utci(float(np.median(vals))),
    )


@dataclass
class AssemblyIndex:
    """Thermal Assembly Complexity Index (TACI), Alberti (2016), grid-native."""

    index: float
    num_zones: int
    spatial_variability: float
    spatial_diversity: float  # Shannon
    edge_complexity: float
    interpretation: str
    components: dict = field(default_factory=dict)

    def line(self) -> str:
        return (
            f"TACI index={self.index:.1f}  zones={self.num_zones}  "
            f"Shannon={self.spatial_diversity:.2f}  edge={self.edge_complexity:.3f}  "
            f"[{self.interpretation}]"
        )


def thermal_assembly_index(grid: np.ndarray, zone_step: float = 2.0) -> AssemblyIndex:
    """Composite microclimate-complexity index from a 2-D UTCI grid.

    TACI = (zones / 10) × (variability / 5) × Shannon × (edge × 10)

    Mirrors the original toolkit's normalisation so values stay comparable to
    the AT6012 reference (Low <20, Moderate 20-50, High 50-100, Very high >100),
    but computes edge complexity from true grid gradients.
    """
    arr = np.asarray(grid, dtype=float)
    vals = _finite(arr)
    if vals.size < 4:
        return AssemblyIndex(0.0, 0, 0.0, 0.0, 0.0, "insufficient data")

    # 1. Microclimate zones, bin the value range in `zone_step`-wide bands.
    lo, hi = float(vals.min()), float(vals.max())
    edges = np.arange(lo, hi + zone_step, zone_step)
    zone_ids = np.clip(np.digitize(vals, edges), 1, max(len(edges) - 1, 1))
    num_zones = int(np.unique(zone_ids).size)

    # 2. Spatial variability, spread of values across the site.
    spatial_variability = float(vals.std())

    # 3. Spatial diversity, Shannon index over zone occupancy.
    _, counts = np.unique(zone_ids, return_counts=True)
    p = counts / counts.sum()
    shannon = float(-np.sum(p * np.log(p)))

    # 4. Edge complexity, mean normalised gradient magnitude across the grid
    #    (true thermal-boundary density, NaN-safe).
    filled = np.where(np.isfinite(arr), arr, np.nanmean(vals))
    gy, gx = np.gradient(filled)
    grad_mag = np.sqrt(gx ** 2 + gy ** 2)
    denom = abs(np.nanmean(vals)) + 1e-6
    edge_complexity = float(np.nanmean(grad_mag) / denom)

    index = (num_zones / 10.0) * (spatial_variability / 5.0) * shannon * (edge_complexity * 10.0)

    if index < 20:
        interp = "Low complexity, limited microclimate diversity"
    elif index < 50:
        interp = "Moderate complexity, some thermal variation"
    elif index < 100:
        interp = "High complexity, diverse thermal niches"
    else:
        interp = "Very high complexity, rich thermal assemblage"

    return AssemblyIndex(
        index=float(index),
        num_zones=num_zones,
        spatial_variability=spatial_variability,
        spatial_diversity=shannon,
        edge_complexity=edge_complexity,
        interpretation=interp,
        components={
            "microclimate_zones": num_zones,
            "spatial_variability_C": round(spatial_variability, 2),
            "shannon_diversity": round(shannon, 3),
            "edge_complexity": round(edge_complexity, 4),
        },
    )


def pct_delta(baseline: float, intervention: float) -> float:
    """Percentage change of intervention relative to baseline (NaN-safe)."""
    if not np.isfinite(baseline) or baseline == 0:
        return float("nan")
    return (intervention / baseline - 1.0) * 100.0
