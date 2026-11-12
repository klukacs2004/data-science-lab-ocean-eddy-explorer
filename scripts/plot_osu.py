#!/usr/bin/env python3
"""OSU counterparts of Escudier et al. (2016), Figures 7–8.

Detection and tracking use the existing project modules. Run --help for usage.
No Mediterranean/model data or curves are fabricated.
"""

from __future__ import annotations
import argparse
from datetime import date, timedelta
import json
import os
from pathlib import Path
import sys

os.environ.setdefault("MPLCONFIGDIR", "/tmp/datalab-matplotlib")
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FixedLocator, StrMethodFormatter
import numpy as np
import pandas as pd
from scipy.stats import pearsonr, spearmanr

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "method_website"))
METHODS = ("Chelton", "Nencioli", "Halo")
COLORS = ("#b51624", "#ef8200", "#386830")
CLASSES = ((7, 25), (25, 50), (50, 100), (100, 150), (150, 200), (200, 250))
CYCLE_COLORS = ("#b51624", "#ef8200", "#708820", "#24205a", "#c00070", "#21898c")


def generate(start, end, output):
    """Daily detection, then association across the entire selected interval."""
    from django.conf import settings

    if not settings.configured:
        settings.configure(SLA_DATA_DIR=ROOT / "data")
    from explorer.methods import load_sla_day, load_velocity_field
    from explorer.datasets import get_available_dates
    from eddy_detection.chelton_method import scan_thresholds
    from eddy_detection.nencioli_method import detect_eddies
    from eddy_detection.halo_method import HaloDetector
    from eddy_detection.method_utils import (
        standardize_chelton,
        standardize_nencioli,
        standardize_okubo_weiss,
    )
    from eddy_tracking.chelton_tracking import track_chelton
    from eddy_tracking.nencioli_tracking import track_nencioli
    from eddy_tracking.halo_tracking import track_halo
    from eddy_tracking.halo_vorticity import representative_vorticity
    import xarray as xr

    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    available = get_available_dates()
    missing = [d.isoformat() for d in days if d.isoformat() not in available]
    if missing:
        raise ValueError(f"Missing daily input: {missing[:5]}")
    # The reference batch settings are independent of the interactive forms.
    config = {
        "Chelton": dict(
            east_km=30.0,
            west_km=50.0,
            north_south_km=30.0,
            min_amplitude_ratio=0.25,
            max_amplitude_ratio=2.5,
            min_area_ratio=0.25,
            max_area_ratio=2.5,
            min_lifetime_days=1,
        ),
        "Nencioli": dict(
            daily_radius_km=40.0,
            gap_radius_km=45.0,
            min_lifetime_days=1,
            max_gap_days=0,
            assignment_method="greedy",
        ),
        "Halo": dict(
            vorticity_scale_s=1e-5,
            max_displacement_km=50.0,
            position_scale_km=25.0,
            diameter_scale_km=200.0,
            max_generalized_distance=2.0,
            min_lifetime_days=1,
            assignment_method="global",
            max_gap_days=0,
        ),
    }
    # Detect each day first, keeping a separate catalogue for each method.
    catalogues = {m: {} for m in METHODS}
    vorticity_by_detection = {}
    excluded = 0
    for index, day in enumerate(days, 1):
        print(f"Detection {index}/{len(days)}: {day}", flush=True)
        height = load_sla_day(day)
        u, v = load_velocity_field(day)
        height, u, v = xr.align(height, u, v, join="exact")
        lat, lon = u.latitude.values, u.longitude.values
        catalogues["Chelton"][day] = standardize_chelton(
            scan_thresholds(height.transpose("longitude", "latitude")), day
        )
        found, diagnostics = detect_eddies(
            u.values, v.values, lat, lon, 2, 2, return_diagnostics=True
        )
        catalogues["Nencioli"][day] = standardize_nencioli(
            found, day, lat, lon, diagnostics=diagnostics
        )
        detector = HaloDetector(
            height.transpose("latitude", "longitude").values,
            lat,
            lon,
            u.values,
            v.values,
            contour_interval=0.02,
            max_diameter_km=600.0,
            filter_passes=2,
        )
        found = detector.detect_eddies()
        means, exclusions = representative_vorticity(
            found, detector.relative_vorticity, lat, lon, 0.0
        )
        excluded += len(exclusions)
        catalogues["Halo"][day] = [
            e for e in standardize_okubo_weiss(found, day, lat, lon) if e.id in means
        ]
        vorticity_by_detection.update(
            {(day, key): value for key, value in means.items()}
        )

    # Associate across the complete period, including year boundaries.
    trackers = {
        "Chelton": track_chelton,
        "Nencioli": track_nencioli,
        "Halo": track_halo,
    }
    records = []
    for method in METHODS:
        print(f"Tracking: {method}", flush=True)
        extra = (
            {"vorticity_by_detection": vorticity_by_detection}
            if method == "Halo"
            else {}
        )
        tracks = trackers[method](catalogues[method], **config[method], **extra)
        for track in tracks:
            for eddy in track.detections:
                records.append(
                    dict(
                        method=method,
                        track_id=track.id,
                        date=eddy.date,
                        radius_km=eddy.radius_km,
                        reliable_radius=eddy.has_reliable_radius,
                        polarity=eddy.polarity,
                        latitude=eddy.latitude,
                        longitude=eddy.longitude,
                        boundary_source=eddy.boundary_source,
                        left_censored=track.start_date == start,
                        right_censored=track.end_date == end,
                    )
                )
    columns = [
        "method",
        "track_id",
        "date",
        "radius_km",
        "reliable_radius",
        "polarity",
        "latitude",
        "longitude",
        "boundary_source",
        "left_censored",
        "right_censored",
    ]
    observations = pd.DataFrame(records, columns=columns)
    observations.to_csv(output / "observations.csv.gz", index=False)
    metadata = dict(
        start=str(start),
        end=str(end),
        tracking=config,
        detection=dict(
            Chelton="scan_thresholds, no additional high-pass filter",
            Nencioli=dict(a=2, b=2),
            Halo=dict(contour_interval_m=0.02, max_diameter_km=600.0, filter_passes=2),
        ),
        halo_vorticity_exclusions=excluded,
        inputs=[
            dict(
                path=str(p.relative_to(ROOT)),
                bytes=p.stat().st_size,
                mtime_ns=p.stat().st_mtime_ns,
            )
            for p in sorted(set(available[d.isoformat()] for d in days))
        ],
    )
    (output / "configuration.json").write_text(json.dumps(metadata, indent=2))
    return observations


def prepare(observations):
    required = {
        "method",
        "track_id",
        "date",
        "radius_km",
        "reliable_radius",
        "left_censored",
        "right_censored",
    }
    if not required <= set(observations):
        raise ValueError(f"Missing columns: {sorted(required-set(observations))}")
    obs = observations.copy()
    obs["date"] = pd.to_datetime(obs.date, errors="raise")
    for column in ("reliable_radius", "left_censored", "right_censored"):
        values = obs[column].astype(str).str.lower()
        if not values.isin(["true", "false", "1", "0"]).all():
            raise ValueError(f"Invalid boolean in {column}")
        obs[column] = values.isin(["true", "1"])
    obs["radius_km"] = pd.to_numeric(obs.radius_km, errors="raise")
    if obs.duplicated(["method", "track_id", "date"]).any():
        raise ValueError("Multiple observations for one track on one day")
    obs["usable_radius"] = (
        obs.reliable_radius & np.isfinite(obs.radius_km) & (obs.radius_km > 0)
    )
    obs["valid_radius"] = obs.radius_km.where(obs.usable_radius)
    tracks = (
        obs.groupby(["method", "track_id"])
        .agg(
            start=("date", "min"),
            end=("date", "max"),
            observations=("date", "size"),
            mean_radius_km=("valid_radius", "mean"),
            radius_observations=("valid_radius", "count"),
            left_censored=("left_censored", "max"),
            right_censored=("right_censored", "max"),
        )
        .reset_index()
    )
    tracks["span_days"] = (tracks.end - tracks.start).dt.days + 1
    obs = obs.merge(
        tracks[["method", "track_id", "start", "span_days"]],
        on=["method", "track_id"],
        validate="many_to_one",
    )
    obs["scaled_age"] = (obs.date - obs.start).dt.days / obs.span_days
    return obs, tracks


def cycle_table(obs, tracks, min_count=20, include_censored=False):
    """One-day class-scaled bins, equal track weighting within each bin.

    The paper specifies age and minimum count, not bin edges or interpolation.
    Actual observations are binned; missing detections are never interpolated.
    Shared class boundaries enter the next class; 250 enters the last class.
    """
    rows = []
    for method in METHODS:
        for lo, hi in CLASSES:
            selected = tracks[
                (tracks.method == method)
                & (tracks.span_days >= lo)
                & ((tracks.span_days <= hi) if hi == 250 else (tracks.span_days < hi))
            ]
            if not include_censored:
                selected = selected[~(selected.left_censored | selected.right_censored)]
            group = obs[
                (obs.method == method)
                & obs.track_id.isin(selected.track_id)
                & obs.usable_radius
            ].copy()
            reference = (lo + hi) / 2
            group["bin"] = np.floor(group.scaled_age * reference).astype(int)
            per_track = (
                group.groupby(["track_id", "bin"]).radius_km.mean().reset_index()
            )
            summary = per_track.groupby("bin").radius_km.agg(["mean", "count", "std"])
            for b in range(int(np.ceil(reference))):
                n = int(summary.loc[b, "count"]) if b in summary.index else 0
                mean = float(summary.loc[b, "mean"]) if n else np.nan
                rows.append(
                    dict(
                        method=method,
                        lifetime_class=f"{lo}-{hi}",
                        reference_days=reference,
                        age_days=b + 0.5,
                        contributors=n,
                        radius_km=mean if n >= min_count else np.nan,
                        mean_before_count_mask=mean,
                        class_tracks=len(selected),
                    )
                )
    return pd.DataFrame(rows)


def save_figure(fig, output, name):
    for extension in ("png", "pdf"):
        fig.savefig(output / f"{name}.{extension}", dpi=180, bbox_inches="tight")
    plt.close(fig)


def plot_figure8(cycles, output, min_count=20):
    """Render saved Figure 8 statistics with a shared upper limit that fits all curves."""
    fig, axes = plt.subplots(
        1, 3, figsize=(15, 4.7), sharex=True, sharey=True, constrained_layout=True
    )
    maximum = cycles.radius_km.max()
    upper = (
        max(65.0, np.ceil(maximum * 1.05 / 10.0) * 10.0)
        if np.isfinite(maximum)
        else 65.0
    )
    for ax, method in zip(axes, METHODS):
        for (lo, hi), color in zip(CLASSES, CYCLE_COLORS):
            data = cycles[
                (cycles.method == method) & (cycles.lifetime_class == f"{lo}-{hi}")
            ]
            ax.plot(data.age_days, data.radius_km, color=color, label=f"{lo}–{hi} days")
        ax.set(
            title=method,
            xlabel="Life (days)",
            xlim=(0, 225),
            ylim=(17.5, upper),
            xticks=[0, 50, 100, 150, 200],
            yticks=np.arange(20, upper + 1, 10),
        )
        ax.grid(alpha=0.25)
        if not np.isfinite(cycles.loc[cycles.method == method, "radius_km"]).any():
            ax.text(
                0.5,
                0.5,
                f"No age bins with ≥ {min_count} tracks",
                ha="center",
                transform=ax.transAxes,
            )
    axes[0].set_ylabel("Radius (km)")
    axes[-1].legend(fontsize=8)
    fig.suptitle(
        f"OSU — Figure 8: radius evolution (minimum {min_count} tracks per bin)"
    )
    save_figure(fig, output, "figure8_radius")


def plot_figure7(radius, survival, output):
    """Render distributions with x limits fitted to the visible data."""
    fig, axes = plt.subplots(2, 1, figsize=(7, 8), constrained_layout=True)
    for method, color in zip(METHODS, COLORS):
        data = radius[radius.method == method].sort_values("left_km")
        if len(data):
            edges = np.r_[data.left_km.to_numpy(), data.right_km.iloc[-1]]
            axes[0].stairs(
                data.percent,
                edges,
                color=color,
                label=f'{method} (n={data["count"].sum():,})',
            )
        data = survival[survival.method == method].sort_values("span_days")
        axes[1].step(
            data.span_days,
            data.percent.where(data.percent > 0),
            where="post",
            color=color,
            label=method,
        )
    max_radius = radius.loc[radius["count"] > 0, "right_km"].max()
    # Fit the lifetime axis to the portion visible above the log-axis floor.
    max_lifetime = survival.loc[survival.percent >= 0.3, "span_days"].max()
    radius_upper = (
        max(100.0, np.ceil(max_radius / 25.0) * 25.0)
        if np.isfinite(max_radius)
        else 100.0
    )
    lifetime_upper = (
        max(25.0, np.ceil(max_lifetime / 25.0) * 25.0)
        if np.isfinite(max_lifetime)
        else 25.0
    )
    axes[0].set(
        xlabel="Radius (km)",
        ylabel="% of eddy detected",
        title="OSU — Figure 7: size distribution",
        xlim=(0, radius_upper),
        ylim=(0, 18),
        xticks=np.arange(0, radius_upper + 1, 25),
        yticks=[0, 5, 10, 15],
    )
    axes[1].set(
        xlabel="Lifetime (days)",
        ylabel="cumulative % of\neddy detected",
        title="OSU — Figure 7: empirical upper-tail distribution",
        yscale="log",
        xlim=(0, lifetime_upper),
        ylim=(0.3, 100),
        xticks=np.arange(0, lifetime_upper + 1, 25),
    )
    axes[1].yaxis.set_major_locator(FixedLocator([1, 10, 100]))
    axes[1].yaxis.set_major_formatter(StrMethodFormatter("{x:g}"))
    for ax in axes:
        ax.grid(alpha=0.25, which="both")
        ax.legend()
    save_figure(fig, output, "figure7_distributions")


def plot(observations, output, min_count=20, include_censored=False):
    obs, tracks = prepare(observations)
    tracks.to_csv(output / "tracks.csv", index=False)
    cycles = cycle_table(obs, tracks, min_count, include_censored)
    cycles.to_csv(output / "figure8_data.csv", index=False)
    plt.rcParams.update(
        {"font.size": 10, "axes.spines.top": False, "axes.spines.right": False}
    )
    valid = obs[obs.usable_radius]
    max_radius = valid.radius_km.max() if len(valid) else 100
    edges = np.arange(0, max(100, np.ceil(max_radius / 2) * 2) + 2, 2.0)
    distribution_rows, survival_rows, correlation_rows = [], [], []
    for method, color in zip(METHODS, COLORS):
        radii = valid.loc[valid.method == method, "radius_km"]
        counts, _ = np.histogram(radii, edges)
        percentages = 100 * counts / len(radii) if len(radii) else counts.astype(float)
        distribution_rows.extend(
            dict(method=method, left_km=a, right_km=b, count=int(n), percent=p)
            for a, b, n, p in zip(edges[:-1], edges[1:], counts, percentages)
        )
        subset = tracks[tracks.method == method]
        thresholds = np.arange(
            1, max(250, int(subset.span_days.max()) if len(subset) else 250) + 1
        )
        spans = np.sort(subset.span_days.to_numpy())
        tail = (
            100
            * (len(spans) - np.searchsorted(spans, thresholds, side="left"))
            / len(spans)
            if len(spans)
            else np.zeros(len(thresholds))
        )
        survival_rows.extend(
            dict(method=method, span_days=t, percent=p)
            for t, p in zip(thresholds, tail)
        )
        paired = subset.dropna(subset=["mean_radius_km"])
        eligible = (
            len(paired) >= 3
            and paired.span_days.nunique() > 1
            and paired.mean_radius_km.nunique() > 1
        )
        correlation_rows.append(
            dict(
                method=method,
                tracks=len(paired),
                pearson_r=(
                    pearsonr(paired.span_days, paired.mean_radius_km).statistic
                    if eligible
                    else np.nan
                ),
                spearman_r=(
                    spearmanr(paired.span_days, paired.mean_radius_km).statistic
                    if eligible
                    else np.nan
                ),
            )
        )
    plot_figure7(pd.DataFrame(distribution_rows), pd.DataFrame(survival_rows), output)
    pd.DataFrame(distribution_rows).to_csv(
        output / "figure7_radius_data.csv", index=False
    )
    pd.DataFrame(survival_rows).to_csv(
        output / "figure7_survival_data.csv", index=False
    )
    pd.DataFrame(correlation_rows).to_csv(output / "correlations.csv", index=False)
    plot_figure8(cycles, output, min_count)
    fig, axes = plt.subplots(1, 3, figsize=(14, 4), constrained_layout=True)
    for ax, method, color in zip(axes, METHODS, COLORS):
        data = tracks[tracks.method == method]
        ax.scatter(data.span_days, data.mean_radius_km, s=7, alpha=0.25, color=color)
        # Use the paper's lifetime terminology; this supplementary plot uses
        # track-mean radius, so retain "Mean" to distinguish it from Figure 8.
        ax.set(title=method, xlabel="Lifetime (days)", ylabel="Mean radius (km)")
        ax.grid(alpha=0.25)
    save_figure(fig, output, "radius_span")
    return tracks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=date.fromisoformat, default=date(1993, 1, 1))
    parser.add_argument("--end", type=date.fromisoformat, default=date(2014, 12, 31))
    parser.add_argument(
        "--catalogue",
        type=Path,
        help="Reuse observations.csv.gz; skip detection/tracking",
    )
    parser.add_argument(
        "--figure7-csv",
        type=Path,
        help="Replot only Figure 7 from a directory containing its saved CSVs",
    )
    parser.add_argument(
        "--figure8-csv",
        type=Path,
        help="Replot only Figure 8 from saved figure8_data.csv",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Output directory; existing result files are overwritten",
    )
    parser.add_argument("--min-count", type=int, default=20)
    parser.add_argument(
        "--include-censored-cycles",
        action="store_true",
        help="Include tracks touching the analysis endpoints in Figure 8",
    )
    args = parser.parse_args()
    if args.end < args.start or args.min_count < 1:
        parser.error("Require end >= start and min-count >= 1")
    args.output.mkdir(parents=True, exist_ok=True)
    if (
        sum(
            value is not None
            for value in (args.catalogue, args.figure7_csv, args.figure8_csv)
        )
        > 1
    ):
        parser.error("Use only one of --catalogue, --figure7-csv, or --figure8-csv")
    if args.figure7_csv:
        plot_figure7(
            pd.read_csv(args.figure7_csv / "figure7_radius_data.csv"),
            pd.read_csv(args.figure7_csv / "figure7_survival_data.csv"),
            args.output,
        )
        print(f"Saved Figure 7: {args.output.resolve()}")
        return
    if args.figure8_csv:
        if args.catalogue:
            parser.error("Use either --figure8-csv or --catalogue")
        cycles = pd.read_csv(args.figure8_csv)
        # Keep the contributor threshold consistent with the saved means.
        cycles["radius_km"] = cycles.mean_before_count_mask.where(
            cycles.contributors >= args.min_count
        )
        plot_figure8(cycles, args.output, args.min_count)
        print(f"Saved Figure 8: {args.output.resolve()}")
        return
    obs = (
        pd.read_csv(args.catalogue)
        if args.catalogue
        else generate(args.start, args.end, args.output)
    )
    tracks = plot(obs, args.output, args.min_count, args.include_censored_cycles)
    (args.output / "plot_configuration.json").write_text(
        json.dumps(
            dict(
                catalogue=(
                    str(args.catalogue.resolve())
                    if args.catalogue
                    else "observations.csv.gz"
                ),
                min_count=args.min_count,
                include_censored_cycles=args.include_censored_cycles,
            ),
            indent=2,
        )
    )
    print(
        f"Saved {len(obs):,} observations, {len(tracks):,} tracks: {args.output.resolve()}"
    )


if __name__ == "__main__":
    main()
