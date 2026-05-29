"""Diurnal microclimate time series — infrared.city SDK 0.4.9.

The area analyses return one spatial grid aggregated over a time window, so a
*temporal* series is built by running the same site across several windows and
tracking how the microclimate evolves through the day.

This example sweeps UTCI across a representative summer day on a compact
single-tile site (kept small to limit cost) and plots mean UTCI and
heat-stress area against the hour, alongside the driving air temperature.

Usage:
  python time_series.py                 # preview the plan (no billing)
  python time_series.py --run           # LIVE: one UTCI job per hour sampled
  python time_series.py --run --site cork --hours 6,9,12,15,18,21
"""

from __future__ import annotations

import argparse
import os
import sys

import infrared_sdk as ir
from infrared_sdk.models import TimePeriod

import regenerative_metrics as rm
import scorecard as sc

MONTH, DAY = 8, 15  # representative summer day


def weather_for_hour(client, station_uuid: str, hour: int):
    """Weather input arrays + TimePeriod for a single hour."""
    # TimePeriod must span >0 hours, so sample a 1-hour window [h, h+1].
    end_hour = hour + 1 if hour < 23 else 23
    start_hour = hour if hour < 23 else 22
    tp = TimePeriod(start_month=MONTH, start_day=DAY, start_hour=start_hour,
                    end_month=MONTH, end_day=DAY, end_hour=end_hour)
    pts = client.weather.filter_weather_data(identifier=station_uuid, time_period=tp)
    arrays = {
        "dry_bulb_temperature": [p.dryBulbTemperature for p in pts],
        "wind_speed": [p.windSpeed for p in pts],
        "relative_humidity": [p.relativeHumidity for p in pts],
        "horizontal_infrared_radiation_intensity": [p.horizontalInfraredRadiationIntensity for p in pts],
        "diffuse_horizontal_radiation": [p.diffuseHorizontalRadiation for p in pts],
        "direct_normal_radiation": [p.directNormalRadiation for p in pts],
        "global_horizontal_radiation": [p.globalHorizontalRadiation for p in pts],
    }
    air_temp = arrays["dry_bulb_temperature"][0] if pts else float("nan")
    return arrays, tp, air_temp


def render(site_name: str, rows: list[dict], out_dir: str) -> str:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    hours = [r["hour"] for r in rows]
    utci = [r["mean_utci"] for r in rows]
    heat = [r["heat_pct"] for r in rows]
    air = [r["air_temp"] for r in rows]

    fig, ax1 = plt.subplots(figsize=(9, 5))
    fig.suptitle(f"Diurnal microclimate time series — {site_name}",
                 fontsize=13, fontweight="bold")
    ax1.plot(hours, utci, "o-", color="#c0392b", lw=2, label="Mean UTCI (°C)")
    ax1.plot(hours, air, "s--", color="#7f8c8d", lw=1.5, label="Air temp (°C)")
    ax1.set_xlabel("Hour of day")
    ax1.set_ylabel("Temperature (°C)")
    ax1.grid(alpha=0.25)

    ax2 = ax1.twinx()
    ax2.bar(hours, heat, width=0.6, alpha=0.18, color="#e67e22", label="Heat-stress area (%)")
    ax2.set_ylabel("Heat-stress area (%)")
    ax2.set_ylim(0, 100)

    l1, lb1 = ax1.get_legend_handles_labels()
    l2, lb2 = ax2.get_legend_handles_labels()
    ax1.legend(l1 + l2, lb1 + lb2, loc="upper left", fontsize=9)

    os.makedirs(out_dir, exist_ok=True)
    slug = site_name.split("(")[0].split("—")[0].strip().lower().replace(" ", "_")
    path = os.path.join(out_dir, f"timeseries_{slug}.png")
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Diurnal microclimate time series")
    ap.add_argument("--run", action="store_true", help="Submit LIVE jobs (default: preview only).")
    ap.add_argument("--site", default="marseille", choices=list(sc.SITES))
    ap.add_argument("--hours", default="8,11,14,17,20", help="Comma list of hours (0-23).")
    ap.add_argument("--out", default="output")
    args = ap.parse_args(argv)

    hours = [int(h) for h in args.hours.split(",") if h.strip()]
    base = sc.SITES[args.site]()
    # Compact single-tile polygon to keep the temporal sweep cheap.
    poly = sc._square(base.lat, base.lon, 0.0011)

    if not args.run:
        print(f"PREVIEW — diurnal UTCI sweep over {base.name}")
        print(f"  hours: {hours}  ({len(hours)} live UTCI jobs on a single tile)")
        print("  Run live with:  python time_series.py --run")
        return 0

    client = ir.InfraredClient()
    try:
        files = client.weather.get_weather_file_from_location(lat=base.lat, lon=base.lon)
        station = next((f for f in files if base.weather_hint and base.weather_hint in f.get("fileName", "")), files[0])
        print(f"weather station: {station['fileName']}")
        buildings = client.buildings.get_area(poly).buildings
        print(f"buildings: {len(buildings)}")

        rows = []
        for h in hours:
            weather, tp, air = weather_for_hour(client, station["uuid"], h)
            req = ir.UtciModelRequest(
                latitude=base.lat, longitude=base.lon,
                analysis_type="thermal-comfort-index", time_period=tp, **weather,
            )
            area = client.run_area_and_wait(req, poly, buildings=buildings, max_tiles_override=1)
            st = rm.utci_stats(area.merged_grid)
            rows.append({"hour": h, "mean_utci": st.mean,
                         "heat_pct": st.heat_stress_pct, "air_temp": air})
            print(f"  {h:02d}:00  air={air:5.1f}°C  meanUTCI={st.mean:5.1f}°C  "
                  f"heat-stress={st.heat_stress_pct:5.1f}%")

        print("\nDIURNAL SUMMARY")
        peak = max(rows, key=lambda r: r["mean_utci"])
        print(f"  peak mean UTCI {peak['mean_utci']:.1f}°C at {peak['hour']:02d}:00")
        amp = max(r["mean_utci"] for r in rows) - min(r["mean_utci"] for r in rows)
        print(f"  diurnal UTCI amplitude: {amp:.1f}°C")
        path = render(base.name, rows, args.out)
        print(f"figure: {path}")
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main())
