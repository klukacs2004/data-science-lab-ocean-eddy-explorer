#!/usr/bin/env python3
"""Export slide-ready comparisons from saved Figure 7 and 8 statistics.

Uses the fixed axis windows read from Escudier et al. (2016), Figures 7–8
(DOI 10.1002/2015JC011371, PDF pages 9–10). No detection, tracking, or
statistical estimates are recomputed. Original result files are preserved.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/datalab-matplotlib")
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.ticker import FixedLocator, NullFormatter, StrMethodFormatter
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
METHODS = ("Chelton", "Nencioli", "Halo")
METHOD_COLORS = ("#b51624", "#df7900", "#386830")
CLASSES = ((7, 25), (25, 50), (50, 100), (100, 150), (150, 200), (200, 250))
CLASS_COLORS = ("#b51624", "#df7900", "#708820", "#24205a", "#c00070", "#21898c")
INK = "#172f43"
MUTED = "#536879"
PAPER_LIMITS = {
    "figure7_radius": {"x": [0, 100], "y": [0, 18]},
    "figure7_span": {"x": [0, 250], "y": [0.3, 100], "yscale": "log"},
    "figure8": {"x": [0, 225], "y": [17.5, 65]},
}
STYLE = {
    "font.family": "DejaVu Sans",
    "font.size": 18,
    "axes.titlesize": 25,
    "axes.titleweight": "bold",
    "axes.labelsize": 24,
    "axes.labelcolor": INK,
    "axes.edgecolor": "#8c9ba7",
    "axes.linewidth": 1.2,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "xtick.labelsize": 18,
    "ytick.labelsize": 18,
    "xtick.color": MUTED,
    "ytick.color": MUTED,
    "text.color": INK,
    "lines.linewidth": 2.6,
    "legend.fontsize": 18,
    "legend.frameon": False,
    "savefig.facecolor": "white",
}


def header(fig, title, subtitle):
    fig.text(0.07, 0.947, title, fontsize=32, weight="bold", va="top")
    fig.text(0.07, 0.877, subtitle, fontsize=17, color=MUTED, va="top")
    fig.add_artist(
        Line2D(
            [0.07, 0.97],
            [0.837, 0.837],
            transform=fig.transFigure,
            color="#dde5eb",
            linewidth=1,
        )
    )


def style_axis(ax):
    ax.grid(axis="both", color="#dde5eb", linewidth=0.8)
    ax.set_axisbelow(True)
    ax.tick_params(length=5, pad=8)
    ax.xaxis.labelpad = 14
    ax.yaxis.labelpad = 14


def save(fig, output, filename, dpi, title):
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    # All visible labels, ticks, legends, and titles must fit the slide canvas.
    for text in fig.findobj(matplotlib.text.Text):
        if text.get_visible() and text.get_text():
            bounds = text.get_window_extent(renderer)
            if (
                bounds.x0 < -1
                or bounds.y0 < -1
                or bounds.x1 > fig.bbox.x1 + 1
                or bounds.y1 > fig.bbox.y1 + 1
            ):
                raise ValueError(f"Text extends beyond the slide: {text.get_text()!r}")
    for legend in fig.legends:
        bounds = legend.get_window_extent(renderer)
        for ax in fig.axes:
            for label in (ax.xaxis.label, ax.yaxis.label, ax.title):
                if (
                    label.get_visible()
                    and label.get_text()
                    and bounds.overlaps(label.get_window_extent(renderer))
                ):
                    raise ValueError(f"Legend overlaps axis text: {label.get_text()!r}")
    path = output / filename
    fig.savefig(
        path,
        dpi=dpi,
        metadata={
            "Title": title,
            "Description": "OSU comparison; fixed axis ranges from Escudier et al. (2016).",
        },
    )
    plt.close(fig)
    print(path.resolve())


def figure7(radius, survival, output, dpi, subtitle):
    fig, axes = plt.subplots(1, 2, figsize=(16, 9))
    fig.subplots_adjust(left=0.105, right=0.97, bottom=0.24, top=0.68, wspace=0.36)
    header(fig, "Eddy size and lifetime distributions", subtitle)
    for method, color in zip(METHODS, METHOD_COLORS):
        data = radius[radius.method == method].sort_values("left_km")
        edges = np.r_[data.left_km.to_numpy(), data.right_km.iloc[-1]]
        axes[0].stairs(data.percent, edges, color=color, label=method, linewidth=2.6)
        data = survival[survival.method == method].sort_values("span_days")
        axes[1].step(
            data.span_days,
            data.percent.where(data.percent > 0),
            where="post",
            color=color,
        )
    axes[0].set(
        xlabel="Radius (km)",
        ylabel="% of eddy detected",
        title="Radius distribution",
        xlim=PAPER_LIMITS["figure7_radius"]["x"],
        ylim=PAPER_LIMITS["figure7_radius"]["y"],
        xticks=[0, 25, 50, 75, 100],
        yticks=[0, 5, 10, 15],
    )
    axes[1].set(
        xlabel="Lifetime (days)",
        ylabel="Cumulative % of\neddy detected",
        title="Lifetime upper-tail distribution",
        yscale="log",
        xlim=PAPER_LIMITS["figure7_span"]["x"],
        ylim=PAPER_LIMITS["figure7_span"]["y"],
        xticks=[0, 50, 100, 150, 200, 250],
    )
    axes[1].yaxis.set_major_locator(FixedLocator([1, 10, 100]))
    axes[1].yaxis.set_major_formatter(StrMethodFormatter("{x:g}"))
    axes[1].yaxis.set_minor_formatter(NullFormatter())
    for ax in axes:
        style_axis(ax)
        ax.set_title(ax.get_title(), loc="center", pad=23, fontsize=23)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(
        handles,
        labels,
        ncol=3,
        loc="center",
        bbox_to_anchor=(0.535, 0.79),
        columnspacing=3,
        handlelength=2.8,
    )
    fig.text(
        0.105,
        0.115,
        "Radius: reliable daily detections, 2 km bins. Lifetimes: all observed track spans.",
        fontsize=14,
        color=MUTED,
    )
    fig.text(
        0.105,
        0.075,
        "Fixed paper axis windows; percentages retain the full-data denominators.",
        fontsize=14,
        color=MUTED,
    )
    fig.text(
        0.105,
        0.03,
        "Axis ranges: Escudier et al. (2016), Fig. 7 · doi:10.1002/2015JC011371",
        fontsize=12,
        color=MUTED,
    )
    assert tuple(axes[0].get_xlim()) == (0, 100)
    assert tuple(axes[0].get_ylim()) == (0, 18)
    assert tuple(axes[1].get_xlim()) == (0, 250)
    assert np.allclose(axes[1].get_ylim(), (0.3, 100))
    save(
        fig,
        output,
        "figure7_comparison_presentation.png",
        dpi,
        "Figure 7 — Eddy size and lifetime distributions",
    )


def figure8(cycles, output, dpi, subtitle, min_count):
    fig, axes = plt.subplots(1, 3, figsize=(16, 9), sharex=True, sharey=True)
    fig.subplots_adjust(left=0.09, right=0.97, bottom=0.35, top=0.715, wspace=0.13)
    header(fig, "Radius evolution by lifespan class", subtitle)
    for ax, method in zip(axes, METHODS):
        for (lo, hi), color in zip(CLASSES, CLASS_COLORS):
            data = cycles[
                (cycles.method == method) & (cycles.lifetime_class == f"{lo}-{hi}")
            ]
            ax.plot(data.age_days, data.radius_km, color=color, label=f"{lo}–{hi} days")
        ax.set(
            title=method,
            xlabel="Life (days)",
            xlim=PAPER_LIMITS["figure8"]["x"],
            ylim=PAPER_LIMITS["figure8"]["y"],
            xticks=[0, 50, 100, 150, 200],
            yticks=[20, 30, 40, 50, 60],
        )
        ax.set_title(method, pad=22, fontsize=26)
        style_axis(ax)
        visible = cycles.loc[
            (cycles.method == method) & cycles.age_days.between(0, 225), "radius_km"
        ].dropna()
        if visible.empty:
            ax.text(
                0.5,
                0.52,
                f"No age bins with\n≥ {min_count} tracks",
                ha="center",
                va="center",
                transform=ax.transAxes,
                color=MUTED,
                fontsize=18,
            )
        elif visible.min() > 65:
            ax.text(
                0.5,
                0.56,
                "All curves above 65 km",
                ha="center",
                va="center",
                transform=ax.transAxes,
                color=MUTED,
                fontsize=18,
                weight="bold",
            )
            ax.text(
                0.5,
                0.40,
                f"Mean radii: {visible.min():.1f}–{visible.max():.1f} km\nOutside the paper axis range",
                ha="center",
                va="center",
                transform=ax.transAxes,
                color=MUTED,
                fontsize=15,
                linespacing=1.6,
            )
        elif visible.max() > 65:
            ax.text(
                0.97,
                0.97,
                "Some values > 65 km",
                ha="right",
                va="top",
                transform=ax.transAxes,
                color=MUTED,
                fontsize=13,
            )
        assert tuple(ax.get_xlim()) == (0, 225)
        assert tuple(ax.get_ylim()) == (17.5, 65)
    axes[0].set_ylabel("Radius (km)")
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(
        handles,
        labels,
        ncol=3,
        loc="center",
        bbox_to_anchor=(0.53, 0.145),
        columnspacing=2.1,
        handlelength=2.6,
        labelspacing=0.8,
        fontsize=17,
    )
    fig.text(
        0.09,
        0.075,
        f"≥ {min_count} tracks per bin · Boundary-censored tracks excluded · Fixed paper axis windows",
        fontsize=14,
        color=MUTED,
    )
    fig.text(
        0.09,
        0.03,
        "Axis ranges: Escudier et al. (2016), Fig. 8 · Life is class-scaled observed age · Radius is absolute",
        fontsize=12,
        color=MUTED,
    )
    save(
        fig,
        output,
        "figure8_comparison_presentation.png",
        dpi,
        "Figure 8 — Radius evolution by lifespan class",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source", type=Path, default=ROOT / "artifacts/osu_assignment_1993_2012"
    )
    parser.add_argument(
        "--output", type=Path, default=ROOT / "artifacts/presentation_comparison"
    )
    parser.add_argument(
        "--dpi", type=int, default=240, help="240 produces 3840 × 2160 PNGs"
    )
    args = parser.parse_args()
    if args.dpi <= 0:
        parser.error("DPI must be positive")
    configuration = json.loads((args.source / "configuration.json").read_text())
    plot_configuration = json.loads(
        (args.source / "plot_configuration.json").read_text()
    )
    min_count = plot_configuration["min_count"]
    if plot_configuration["include_censored_cycles"]:
        parser.error("This export expects boundary-censored cycles to be excluded")
    files = [
        args.source / name
        for name in (
            "figure7_radius_data.csv",
            "figure7_survival_data.csv",
            "figure8_data.csv",
        )
    ]
    radius, survival, cycles = (pd.read_csv(p) for p in files)
    for data in (radius, survival, cycles):
        if set(data.method) != set(METHODS):
            parser.error("Source tables must include Chelton, Nencioli, and Halo")
    if not np.allclose(radius.groupby("method").percent.sum(), 100):
        parser.error("Radius percentages must sum to 100 for each method")
    # Use exactly the saved count mask and means; do not recompute statistics.
    expected = cycles.mean_before_count_mask.where(cycles.contributors >= min_count)
    if not np.allclose(cycles.radius_km, expected, equal_nan=True):
        parser.error(
            "Saved radius curves do not match the recorded contributor threshold"
        )
    start, end = configuration["start"], configuration["end"]
    subtitle = f"OSU blended altimetry · U.S. West Coast · {start[:4]}–{end[:4]}"
    args.output.mkdir(parents=True, exist_ok=True)
    with plt.rc_context(STYLE):
        figure7(radius, survival, args.output, args.dpi, subtitle)
        figure8(cycles, args.output, args.dpi, subtitle, min_count)
    manifest = {
        "source": str(args.source.resolve()),
        "start": start,
        "end": end,
        "min_tracks_per_age_bin": min_count,
        "include_censored_cycles": False,
        "pixels": [16 * args.dpi, 9 * args.dpi],
        "dpi": args.dpi,
        "axis_limits": PAPER_LIMITS,
        "style": STYLE,
        "paper_doi": "10.1002/2015JC011371",
        "paper_pdf_pages": [9, 10],
        "source_sha256": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files
        },
        "figure8_above_65_km": {
            method: int(((cycles.method == method) & (cycles.radius_km > 65)).sum())
            for method in METHODS
        },
    }
    (args.output / "export_configuration.json").write_text(
        json.dumps(manifest, indent=2) + "\n"
    )


if __name__ == "__main__":
    main()
