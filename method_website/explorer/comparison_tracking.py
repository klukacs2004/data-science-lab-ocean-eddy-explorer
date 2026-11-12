"""Compare existing tracking runners without changing their association rules."""

from datetime import timedelta

import numpy as np
import pandas as pd
from plotly.subplots import make_subplots
import plotly.graph_objects as go

from .comparison import METHODS
from .forms import CheltonTrackingForm, NencioliTrackingForm, HaloTrackingForm
from .chelton_tracking import run_chelton_tracking
from .tracking import run_tracking
from .halo_tracking import run_halo_tracking
from .plots.base import BaseInteractivePlotter

CLASSES = ((7, 25), (25, 50), (50, 100), (100, 150), (150, 200), (200, 250))
COLORS = ("#b51624", "#ef8200", "#708820", "#24205a", "#c00070", "#21898c")


def run_tracking_comparison(settings, *, progress=None, daily_cache=None):
    results = []
    for form, runner in (
        (CheltonTrackingForm, run_chelton_tracking),
        (NencioliTrackingForm, run_tracking),
        (HaloTrackingForm, run_halo_tracking),
    ):
        parameters = {key: field.initial for key, field in form.base_fields.items()}
        parameters.update(
            {key: value for key, value in settings.items() if key in parameters}
        )
        # Keep the complete span population, including single-day tracks.
        parameters["min_lifetime_days"] = 1

        def report(phase, completed, cached):
            if progress:
                progress(len(results), phase, completed, cached)

        result = (
            runner(parameters, progress=report, daily_cache=daily_cache)
            if progress or daily_cache
            else runner(parameters)
        )
        # Report precisely the settings passed to each existing runner.
        result["comparison_parameters"] = [
            {"label": form.base_fields[key].label, "value": value}
            for key, value in parameters.items()
            if key not in settings and key not in ("year", "min_lifetime_days")
        ]
        results.append(result)
    return results


def tracking_figures(results, start, duration, min_count=20, include_censored=False):
    end = start + timedelta(days=duration - 1)
    distribution = make_subplots(
        rows=2,
        cols=1,
        subplot_titles=("Size distribution", "Empirical upper-tail distribution"),
        vertical_spacing=0.16,
    )
    evolution = make_subplots(
        rows=1,
        cols=3,
        shared_xaxes=True,
        shared_yaxes=True,
        subplot_titles=[label for _, label, _ in METHODS],
    )
    all_radii, visible_spans, visible_ages = [], [], []
    summaries = []
    for column, ((key, label, color), result) in enumerate(zip(METHODS, results), 1):
        tracks = result["tracks"]
        radii = [
            e.radius_km
            for t in tracks
            for e in t.detections
            if e.has_reliable_radius and np.isfinite(e.radius_km) and e.radius_km > 0
        ]
        all_radii.extend(radii)
        censored = sum(t.start_date == start or t.end_date == end for t in tracks)
        summaries.append(
            {
                "label": label,
                "color": color,
                "tracks": len(tracks),
                "observations": len(radii),
                "censored": censored,
                "complete": len(tracks) - censored,
                "parameters": result.get("comparison_parameters", []),
                "missing": len(result["missing_days"]),
            }
        )
        edges = np.arange(0, max(100, np.ceil(max(radii, default=0) / 2) * 2) + 2, 2.0)
        counts, _ = np.histogram(radii, edges)
        percentages = 100 * counts / len(radii) if radii else counts.astype(float)
        distribution.add_trace(
            go.Scatter(
                x=edges.tolist(),
                y=np.r_[percentages, 0].tolist(),
                mode="lines",
                line={"color": color, "shape": "hv"},
                name=label,
                legendgroup=key,
                hovertemplate="Radius: %{x} km<br>%{y:.3f}% of detections<extra>%{fullData.name}</extra>",
            ),
            row=1,
            col=1,
        )
        spans = np.sort([(t.end_date - t.start_date).days + 1 for t in tracks])
        thresholds = np.arange(1, max(spans, default=1) + 1)
        tail = (
            100 * (len(spans) - np.searchsorted(spans, thresholds)) / len(spans)
            if len(spans)
            else np.zeros(len(thresholds))
        )
        visible_spans.extend(thresholds[tail >= 0.3].tolist())
        distribution.add_trace(
            go.Scatter(
                x=thresholds.tolist(),
                y=[float(p) if p > 0 else None for p in tail],
                mode="lines",
                line={"color": color, "shape": "hv"},
                name=label,
                legendgroup=key,
                showlegend=False,
                hovertemplate="Observed span: %{x} days<br>%{y:.3f}% of tracks<extra>%{fullData.name}</extra>",
            ),
            row=2,
            col=1,
        )
        visible_bins = 0
        for (lo, hi), cycle_color in zip(CLASSES, COLORS):
            reference = (lo + hi) / 2
            samples = []
            for t in tracks:
                span = (t.end_date - t.start_date).days + 1
                if not (lo <= span and (span <= hi if hi == 250 else span < hi)):
                    continue
                if not include_censored and (
                    t.start_date == start or t.end_date == end
                ):
                    continue
                for e in t.detections:
                    if (
                        e.has_reliable_radius
                        and np.isfinite(e.radius_km)
                        and e.radius_km > 0
                    ):
                        samples.append(
                            (
                                t.id,
                                int(
                                    np.floor(
                                        (e.date - t.start_date).days / span * reference
                                    )
                                ),
                                e.radius_km,
                            )
                        )
            stats = (
                pd.DataFrame(samples, columns=["track", "bin", "radius"])
                .groupby(["track", "bin"])
                .radius.mean()
                .groupby("bin")
                .agg(["mean", "count"])
            )
            bins = range(int(np.ceil(reference)))
            n = [int(stats.loc[b, "count"]) if b in stats.index else 0 for b in bins]
            values = [
                float(stats.loc[b, "mean"]) if count >= min_count else None
                for b, count in zip(bins, n)
            ]
            visible_bins += sum(value is not None for value in values)
            visible_ages.extend(
                b + 0.5 for b, value in zip(bins, values) if value is not None
            )
            evolution.add_trace(
                go.Scatter(
                    x=[b + 0.5 for b in bins],
                    y=values,
                    customdata=n,
                    mode="lines",
                    connectgaps=False,
                    line={"color": cycle_color},
                    name=f"{lo}–{hi} days",
                    legendgroup=f"{lo}-{hi}",
                    showlegend=column == 1,
                    hovertemplate="Class-scaled age: %{x:.1f} days<br>Radius: %{y:.2f} km<br>Tracks: %{customdata}<extra>%{fullData.name}</extra>",
                ),
                row=1,
                col=column,
            )
        if not visible_bins:
            evolution.add_annotation(
                text=f"No age bins with ≥ {min_count} tracks",
                x=0.5,
                y=0.5,
                xref="x domain" if column == 1 else f"x{column} domain",
                yref="y domain" if column == 1 else f"y{column} domain",
                showarrow=False,
            )
    distribution.update_xaxes(
        title_text="Radius [km]",
        range=[0, max(100, np.ceil(max(all_radii, default=0) / 25) * 25)],
        row=1,
        col=1,
    )
    distribution.update_yaxes(
        title_text="Detections [%]", rangemode="tozero", row=1, col=1
    )
    max_visible_span = max(visible_spans, default=1)
    span_step = 5 if max_visible_span <= 25 else 25
    span_upper = max(span_step, np.ceil(max_visible_span / span_step) * span_step)
    distribution.update_xaxes(
        title_text="Observed span [days]", range=[0, span_upper], row=2, col=1
    )
    distribution.update_yaxes(
        title_text="Tracks remaining [%]",
        type="log",
        range=[np.log10(0.3), 2],
        tickvals=[1, 10, 100],
        ticktext=["1", "10", "100"],
        row=2,
        col=1,
    )
    age_upper = max(25, np.ceil(max(visible_ages, default=25) / 25) * 25)
    evolution.update_xaxes(title_text="Class-scaled age [days]", range=[0, age_upper])
    evolution.update_yaxes(rangemode="tozero")
    evolution.update_yaxes(title_text="Radius [km]", row=1, col=1)
    for fig, height in ((distribution, 720), (evolution, 440)):
        fig.update_layout(
            template="plotly_white",
            height=height,
            margin={"l": 65, "r": 25, "t": 50, "b": 85},
            legend={"orientation": "h", "y": -0.18, "groupclick": "togglegroup"},
        )
        BaseInteractivePlotter.apply_theme(fig)
    return distribution, evolution, summaries
