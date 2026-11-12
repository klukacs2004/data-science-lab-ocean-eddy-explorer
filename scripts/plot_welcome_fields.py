#!/usr/bin/env python3
"""Plot the welcome page's daily and reference fields as one two-panel figure."""

from __future__ import annotations

import argparse
from datetime import date
import os
from pathlib import Path
import sys

os.environ.setdefault("MPLCONFIGDIR", "/tmp/datalab-matplotlib")
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter, FormatStrFormatter
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "method_website"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django

django.setup()
from explorer.datasets import get_available_dates
from explorer.methods import load_reference_mean, load_sla_day, load_velocity_field


def plot(day, output):
    daily = load_sla_day(day).transpose("latitude", "longitude")
    reference = load_reference_mean().transpose("latitude", "longitude")
    import xarray as xr

    daily, reference = xr.align(daily, reference, join="exact")
    u, v = load_velocity_field(day)
    daily, u, v = xr.align(daily, u, v, join="exact")
    u, v = (field.transpose("latitude", "longitude") for field in (u, v))
    longitude = ((daily.longitude.values + 180) % 360) - 180
    latitude = daily.latitude.values
    daily_cm, mean_cm = daily.values * 100.0, reference.values * 100.0
    # Use the same limits and palettes as the welcome page.
    daily_limit = (
        max(float(np.nanmax(np.abs(daily_cm))), float(np.nanmax(np.abs(mean_cm))))
        or 1.0
    )
    mean_low, mean_high = float(np.nanmin(mean_cm)), float(np.nanmax(mean_cm))
    if mean_low == mean_high:
        padding = max(abs(mean_low) * 0.01, 0.01)
        mean_low, mean_high = mean_low - padding, mean_high + padding
    fig, axes = plt.subplots(1, 2, figsize=(13.5, 7.0), sharex=True, sharey=True)
    fig.subplots_adjust(left=0.065, right=0.965, top=0.90, bottom=0.25, wspace=0.25)
    for ax, values, title, palette, limits, label in zip(
        axes,
        (daily_cm, mean_cm),
        (
            f"(a) Daily sea-level anomaly · {day.isoformat()}",
            "(b) Reference mean AVISO SLA · 1993–2012",
        ),
        ("RdBu_r", "viridis"),
        ((-daily_limit, daily_limit), (mean_low, mean_high)),
        ("SLA (cm)", "Mean SLA (cm)"),
    ):
        ax.set_facecolor("#e5e8e9")
        image = ax.pcolormesh(
            longitude,
            latitude,
            np.ma.masked_invalid(values),
            cmap=palette,
            vmin=limits[0],
            vmax=limits[1],
            shading="nearest",
            rasterized=True,
        )
        ax.set_title(title, loc="left", fontsize=11, pad=12)
        ax.set_xlabel("Longitude", fontsize=10)
        ax.set_aspect(1 / np.cos(np.deg2rad(float(latitude.mean()))))
        ax.set_xticks([-135, -130, -125, -120, -115])
        ax.set_yticks([32, 36, 40, 44, 48])
        ax.xaxis.set_major_formatter(FuncFormatter(lambda x, _: f"{abs(x):g}°W"))
        ax.yaxis.set_major_formatter(FuncFormatter(lambda y, _: f"{y:g}°N"))
        ax.tick_params(labelsize=9)
        ax.grid(alpha=0.16, linewidth=0.5)
        bar = fig.colorbar(
            image, ax=ax, fraction=0.045, pad=0.035, format=FormatStrFormatter("%.1f")
        )
        bar.set_label(label, fontsize=10)
        bar.ax.tick_params(labelsize=9)
    axes[0].set_ylabel("Latitude", fontsize=10)
    # Match the welcome map's arrow sampling and 72-hour displacement scale.
    x, y = np.meshgrid(longitude[::2], latitude[::2])
    east, north = u.values[::2, ::2], v.values[::2, ::2]
    valid = np.isfinite(east) & np.isfinite(north) & np.isfinite(daily_cm[::2, ::2])
    dx = np.rad2deg(east * 259.2 / (6371 * np.cos(np.deg2rad(y))))
    dy = np.rad2deg(north * 259.2 / 6371)
    axes[0].quiver(
        x[valid],
        y[valid],
        dx[valid],
        dy[valid],
        color="#183747",
        angles="xy",
        scale_units="xy",
        scale=1,
        width=0.002,
        headwidth=3.5,
    )
    # Keep both panels on the same geographic extent after adding arrows.
    dx_grid, dy_grid = abs(float(np.diff(longitude).mean())), abs(
        float(np.diff(latitude).mean())
    )
    axes[0].set_xlim(longitude.min() - dx_grid / 2, longitude.max() + dx_grid / 2)
    axes[0].set_ylim(latitude.min() - dy_grid / 2, latitude.max() + dy_grid / 2)
    fig.text(
        0.065,
        0.055,
        "Arrows: daily geostrophic velocity, sampled every second grid cell; 72-hour visual scale. Grey: no data.\n"
        "Each panel uses its own colour limits. Fields and velocities are plotted directly from the supplied NetCDF data.",
        fontsize=9,
        color="#354b55",
        linespacing=1.7,
    )
    output.mkdir(parents=True, exist_ok=True)
    for extension in ("png", "pdf"):
        path = output / f"welcome_sla_reference_comparison.{extension}"
        fig.savefig(path, dpi=300, bbox_inches="tight", facecolor="white")
        print(path.resolve())
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--date",
        type=date.fromisoformat,
        help="Daily field; defaults to the first available date, as on the welcome page",
    )
    parser.add_argument(
        "--output", type=Path, default=ROOT / "artifacts/welcome_snapshots"
    )
    args = parser.parse_args()
    day = args.date or date.fromisoformat(min(get_available_dates()))
    plot(day, args.output)


if __name__ == "__main__":
    main()
