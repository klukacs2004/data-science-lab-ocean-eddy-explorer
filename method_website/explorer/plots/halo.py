"""Static and interactive Halo evidence, using the explorer plotter interfaces."""

import numpy as np
import plotly.graph_objects as go
from matplotlib.figure import Figure
from .base import BaseInteractivePlotter, BasePlotter


def geographic_contour(detector, candidate):
    c = candidate["contour"]
    return (
        np.interp(c[:, 1], np.arange(len(detector.longitude)), detector.longitude),
        np.interp(c[:, 0], np.arange(len(detector.latitude)), detector.latitude),
    )


def color_limit(field):
    finite = np.abs(field[np.isfinite(field)])
    return float(finite.max()) if finite.size and finite.max() > 0 else 1.0


class InteractiveHaloPlotter(BaseInteractivePlotter):
    def detection(self, detector, diagnostics, selected=None):
        lon, lat = detector.longitude, detector.latitude
        height = detector.sla_field * 100.0
        limit = color_limit(height)
        fig = go.Figure(
            go.Heatmap(
                x=lon,
                y=lat,
                z=height,
                zmin=-limit,
                zmax=limit,
                colorscale="RdBu_r",
                colorbar={"title": "SLA [cm]"},
                hovertemplate="Longitude: %{x:.3f}°<br>Latitude: %{y:.3f}°<br>SLA: %{z:.2f} cm<extra></extra>",
            )
        )
        fig.add_trace(
            go.Heatmap(
                x=lon[1:-1],
                y=lat[1:-1],
                z=np.where(diagnostics["filtered_w"] < 0, 1.0, np.nan),
                colorscale=[[0, "#111827"], [1, "#111827"]],
                showscale=False,
                opacity=0.25,
                hoverinfo="skip",
            )
        )
        for accepted, color in ((False, "#94a3b8"), (True, "#176443")):
            candidates = [
                c for c in diagnostics["candidates"] if c["accepted"] == accepted
            ]
            x, y = [], []
            for c in candidates:
                cx, cy = geographic_contour(detector, c)
                x.extend(cx.tolist() + [None])
                y.extend(cy.tolist() + [None])
            group = "accepted" if accepted else "rejected"
            visible = True if accepted else "legendonly"
            fig.add_trace(
                go.Scatter(
                    x=x,
                    y=y,
                    mode="lines",
                    line={"color": color, "width": 2 if accepted else 1},
                    name=group.capitalize(),
                    legendgroup=group,
                    visible=visible,
                    hoverinfo="skip",
                )
            )
            fig.add_trace(
                go.Scatter(
                    x=[c["longitude"] for c in candidates],
                    y=[c["latitude"] for c in candidates],
                    mode="markers",
                    marker={"color": color, "size": 8},
                    legendgroup=group,
                    showlegend=False,
                    visible=visible,
                    customdata=[
                        [c["id"], c["reason_label"], c["level_cm"], c["diameter_km"]]
                        for c in candidates
                    ],
                    hovertemplate="Candidate %{customdata[0]}<br>%{customdata[1]}<br>Level: %{customdata[2]:.2f} cm<br>Diameter: %{customdata[3]:.1f} km<extra></extra>",
                )
            )
        if selected:
            x, y = geographic_contour(detector, selected)
            fig.add_trace(
                go.Scatter(
                    x=x,
                    y=y,
                    mode="lines",
                    line={"color": "#f59e0b", "width": 4},
                    name=f"Candidate {selected['id']}",
                    hoverinfo="skip",
                )
            )
        fig.update_layout(
            height=600,
            template="plotly_white",
            margin={"l": 55, "r": 30, "t": 30, "b": 55},
            legend={"orientation": "h", "groupclick": "togglegroup"},
        )
        self.set_geographic_axes(fig, lat)
        return self.apply_theme(fig)


class HaloPlotter(BasePlotter):
    def _height(self, ax, detector):
        height = detector.sla_field * 100.0
        limit = color_limit(height)
        return ax.pcolormesh(
            detector.longitude,
            detector.latitude,
            height,
            shading="auto",
            cmap="RdBu_r",
            vmin=-limit,
            vmax=limit,
        )

    def _cores(self, ax, detector, diagnostics):
        ax.pcolormesh(
            detector.longitude[1:-1],
            detector.latitude[1:-1],
            np.ma.masked_where(
                ~(diagnostics["filtered_w"] < 0),
                np.ones_like(diagnostics["filtered_w"]),
            ),
            shading="auto",
            cmap="Greys",
            vmin=0,
            vmax=1,
            alpha=0.25,
        )

    def detection(self, detector, diagnostics, selected=None, annotate=False):
        fig = Figure(figsize=(10, 7), constrained_layout=True)
        ax = fig.subplots()
        fig.colorbar(self._height(ax, detector), ax=ax, label="SLA [cm]")
        self._cores(ax, detector, diagnostics)
        for c in sorted(diagnostics["candidates"], key=lambda c: c["accepted"]):
            x, y = geographic_contour(detector, c)
            ax.plot(
                x,
                y,
                color="#176443" if c["accepted"] else "#94a3b8",
                lw=2 if c["accepted"] else 0.7,
                label="Accepted" if c["accepted"] else "Rejected",
            )
            if annotate and c["accepted"]:
                ax.text(c["longitude"], c["latitude"], str(c["id"]), fontsize=8)
        if selected:
            x, y = geographic_contour(detector, selected)
            ax.plot(x, y, color="#f59e0b", lw=3, label=f"Candidate {selected['id']}")
            padx = max(np.ptp(x) * 0.25, 0.15)
            pady = max(np.ptp(y) * 0.25, 0.15)
            ax.set_xlim(
                max(detector.longitude[0], min(x) - padx),
                min(detector.longitude[-1], max(x) + padx),
            )
            ax.set_ylim(
                max(detector.latitude[0], min(y) - pady),
                min(detector.latitude[-1], max(y) + pady),
            )
        self.set_geographic_axes(
            ax,
            detector.latitude,
            "Halo candidate inspection" if selected else "Halo detection",
        )
        handles, labels = ax.get_legend_handles_labels()
        if handles:
            unique = dict(zip(labels, handles))
            ax.legend(unique.values(), unique.keys())
        return fig

    def OW_field(self, detector, diagnostics):
        fig = Figure(figsize=(12, 5), constrained_layout=True)
        axes = fig.subplots(1, 2)
        limit = max(
            color_limit(diagnostics["raw_w"]), color_limit(diagnostics["filtered_w"])
        )
        for ax, key, title in zip(
            axes,
            ("raw_w", "filtered_w"),
            ("Raw W", f"Smoothed W · {detector.filter_passes} passes"),
        ):
            image = ax.pcolormesh(
                detector.longitude[1:-1],
                detector.latitude[1:-1],
                diagnostics[key],
                shading="auto",
                cmap="RdBu_r",
                vmin=-limit,
                vmax=limit,
            )
            self.set_geographic_axes(ax, detector.latitude, title)
        fig.colorbar(image, ax=list(axes), label="W [s⁻²]")
        return fig

    def rotating_regions(self, detector, diagnostics):
        fig = Figure(figsize=(10, 6), constrained_layout=True)
        ax = fig.subplots()
        labels = np.ma.masked_equal(diagnostics["labels"], 0)
        ax.pcolormesh(
            detector.longitude[1:-1],
            detector.latitude[1:-1],
            labels,
            shading="auto",
            cmap="tab20",
        )
        for core in range(1, diagnostics["core_count"] + 1):
            locations = np.argwhere(diagnostics["labels"] == core)
            values = diagnostics["filtered_w"][diagnostics["labels"] == core]
            i, j = locations[np.argmin(values)]
            ax.plot(detector.longitude[j + 1], detector.latitude[i + 1], "k+", ms=7)
            ax.annotate(
                str(core),
                (detector.longitude[j + 1], detector.latitude[i + 1]),
                xytext=(4, 4),
                textcoords="offset points",
                fontsize=8,
            )
        self.set_geographic_axes(
            ax,
            detector.latitude,
            "Connected negative-W regions and minimum-W representatives",
        )
        return fig
