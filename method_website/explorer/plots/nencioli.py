from matplotlib.figure import Figure
from matplotlib.patches import PathPatch
from matplotlib.path import Path
import numpy as np

import plotly.graph_objects as go
import plotly.express as px
from pandas import DataFrame

from .base import BaseInteractivePlotter, BasePlotter
from eddy_detection.nencioli_method import (
    RotationDirection,
    NencioliCenterDetector,
    NencioliBoundaryDetector,
    extract_local_region,
)


class InteractiveNencioliPlotter(BaseInteractivePlotter):
    def detection(self, longitude, latitude, sla, u, v, candidates) -> go.Figure:
        vmax = float(np.nanmax(np.abs(sla * 100)))
        vmax = 1.0 if vmax == 0 else vmax

        fig = go.Figure(
            go.Heatmap(
                x=longitude,
                y=latitude,
                z=sla * 100,
                colorscale="RdBu_r",
                zmin=-vmax,
                zmax=vmax,
                colorbar={"title": "SLA [cm]"},
                hovertemplate=(
                    "<b>Sea Level Anomaly</b><br>"
                    "Longitude: %{x:.3f}°<br>"
                    "Latitude: %{y:.3f}°<br>"
                    "SLA: %{z:.2f} cm"
                    "<extra></extra>"
                ),
            )
        )
        xx, yy = np.meshgrid(longitude[::2], latitude[::2])
        uu, vv = u[::2, ::2], v[::2, ::2]
        finite = np.isfinite(uu) & np.isfinite(vv) & np.isfinite(sla[::2, ::2])
        arrow_lon, arrow_lat = self.velocity_arrow_segments(
            xx[finite], yy[finite], uu[finite], vv[finite]
        )
        fig.add_trace(
            go.Scatter(
                x=arrow_lon,
                y=arrow_lat,
                mode="lines",
                name="Velocity",
                hoverinfo="skip",
                line={"color": "#142d3a", "width": 1.2},
                showlegend=True,
            )
        )
        for row in candidates:
            if row["status"] != "accepted":
                continue
            contour = row["contour"]
            fig.add_trace(
                go.Scatter(
                    x=np.interp(contour[:, 1], np.arange(len(longitude)), longitude),
                    y=np.interp(contour[:, 0], np.arange(len(latitude)), latitude),
                    mode="lines",
                    line={
                        "color": "#176443",
                        "dash": (
                            "dash"
                            if row.get("source") == "circular_fallback"
                            else "solid"
                        ),
                    },
                    showlegend=False,
                    hoverinfo="skip",
                )
            )
        groups = [
            (
                "Accepted boundary",
                [r for r in candidates if r["status"] == "accepted"],
                "#176443",
                "circle",
                True,
            ),
            (
                "Center without boundary",
                [
                    r
                    for r in candidates
                    if r["perimeter_pass"] and r["status"] == "rejected"
                ],
                "#b86c17",
                "x",
                True,
            ),
            (
                "Rejected before center detection",
                [
                    r
                    for r in candidates
                    if r["status"] == "rejected" and not r["perimeter_pass"]
                ],
                "#b86c17",
                "x",
                "legendonly",
            ),
        ]
        for name, rows, color, symbol, visible in groups:
            fig.add_trace(
                go.Scatter(
                    x=[r["longitude"] for r in rows],
                    y=[r["latitude"] for r in rows],
                    mode="markers",
                    name=name,
                    visible=visible,
                    marker={"color": color, "symbol": symbol, "size": 9},
                    customdata=[
                        [r["id"], r["reason_label"], r["rotation"]] for r in rows
                    ],
                    hovertemplate="Candidate %{customdata[0]}<br>%{customdata[1]}<br>%{customdata[2]}<br>"
                    "%{y:.3f}°N, %{x:.3f}°E<br>Click to inspect<extra></extra>",
                )
            )
        self.set_geographic_axes(
            fig, latitude, title="Centers, boundaries and velocity geometry"
        )
        fig.update_layout(
            template="plotly_white",
            height=620,
            margin={"l": 50, "r": 25, "t": 50, "b": 90},
            legend={"orientation": "h", "y": -0.15},
            clickmode="event",
            dragmode="pan",
        )
        return self.apply_theme(fig)

    def parameter_sensitivity_heatmap(self, summary_df: DataFrame) -> go.Figure:
        heatmap_data = summary_df.pivot(index="b", columns="a", values="n_eddies")
        fig = px.imshow(
            heatmap_data,
            labels={
                "x": "Velocity search radius (a)",
                "y": "minimum search radius (b)",
                "color": "Detected centers",
            },
            color_continuous_scale="Viridis",
            text_auto=True,
            aspect="auto",
            origin="lower",
        )

        fig.update_layout(
            title="Nencioli Parameter Sensitivity", template="plotly_white"
        )

        fig.update_traces(
            hovertemplate="a=%{x}, b=%{y}<br>%{z} centers<br>Click to inspect this configuration<extra></extra>"
        )

        return self.apply_theme(fig)


class NencioliPlotter(BasePlotter):
    def velocity_field(
        self,
        longitude,
        latitude,
        u,
        v,
        sla,
        a,
        eddies: list[tuple[int, int, RotationDirection, np.ndarray]],
        quiver_step: int = 3,
    ) -> Figure:
        if quiver_step < 1:
            raise ValueError("quiver_step must be positive")

        fig = Figure(figsize=(10, 7), constrained_layout=True)
        ax = fig.subplots()

        mesh = ax.pcolormesh(
            longitude,
            latitude,
            sla,
            cmap="RdBu_r",
            shading="auto",
            vmin=-0.3,
            vmax=0.3,
            zorder=0,
        )

        lon_grid, lat_grid = np.meshgrid(longitude, latitude)

        s = slice(None, None, quiver_step)
        quiver_options = {}
        if not np.any(np.hypot(u[s, s], v[s, s]) > 0):
            quiver_options["scale"] = 1
        ax.quiver(
            lon_grid[s, s],
            lat_grid[s, s],
            u[s, s],
            v[s, s],
            color="0.35",
            pivot="mid",
            **quiver_options,
        )

        clockwise = []
        counterclockwise = []

        for i, j, direction, contour in eddies:
            eddy = (longitude[j], latitude[i], contour)

            if direction == RotationDirection.CLOCKWISE:
                clockwise.append(eddy)

            elif direction == RotationDirection.COUNTERCLOCKWISE:
                counterclockwise.append(eddy)

        for eddy_candidate, color, marker, label in (
            (clockwise, "red", "x", "Clockwise"),
            (counterclockwise, "blue", "o", "Counterclockwise"),
        ):
            if not eddy_candidate:
                continue

            for x, y, contour in eddy_candidate:
                # Detector contours contain fractional (latitude, longitude)
                # grid indices; the plot uses geographic coordinates.
                vertices = np.column_stack(
                    (
                        np.interp(contour[:, 1], np.arange(len(longitude)), longitude),
                        np.interp(contour[:, 0], np.arange(len(latitude)), latitude),
                    )
                )
                contour_patch = PathPatch(
                    Path(vertices),
                    facecolor="none",
                    edgecolor=color,
                )
                ax.add_patch(contour_patch)
            ax.scatter(
                [eddy[0] for eddy in eddy_candidate],
                [eddy[1] for eddy in eddy_candidate],
                color=color,
                marker=marker,
                label=label,
            )

        ax.set_xlabel("Longitude [°E]")
        ax.set_ylabel("Latitude [°N]")
        ax.set_title("Nencioli Eddy Detection")

        if clockwise or counterclockwise:
            ax.legend()
        ax.grid(alpha=0.2)

        return fig

    def diagnostics(self, longitude, latitude, u, v, sla, a, eddies, candidates):
        fig = self.velocity_field(longitude, latitude, u, v, sla, a, eddies)
        ax = fig.axes[0]
        for status, color, marker, label in (
            ("accepted", "#176443", "o", "Accepted boundary"),
            ("rejected", "#b86c17", "x", "Rejected candidate"),
        ):
            rows = [c for c in candidates if c["status"] == status]
            ax.scatter(
                [c["longitude"] for c in rows],
                [c["latitude"] for c in rows],
                c=color,
                marker=marker,
                s=18,
                alpha=0.65,
                label=label,
            )
        # Label detected centers only, avoiding hundreds of overlapping labels.
        for row in candidates:
            if row["perimeter_pass"]:
                ax.annotate(
                    str(row["id"]),
                    (row["longitude"], row["latitude"]),
                    xytext=(4, 4),
                    textcoords="offset points",
                    fontsize=7,
                )
        self.set_geographic_axes(
            ax, latitude, "Candidate diagnostics · labels identify detected centers"
        )
        ax.legend(fontsize=8)
        return fig

    def candidate(self, longitude, latitude, u, v, a, b, candidate):
        fig = Figure(figsize=(12, 9), constrained_layout=True)
        axes = fig.subplots(2, 2)
        i, j, pair_j = candidate["i"], candidate["j"], candidate["pair_j"]
        ci, cj = candidate["center_i"], candidate["center_j"]
        mi, mj = (ci, cj) if ci is not None else (i, j)
        radius = a + b + 2
        lo_i, hi_i = max(0, mi - radius), min(len(latitude), mi + radius + 1)
        lo_j, hi_j = max(0, mj - radius), min(len(longitude), mj + radius + 1)
        ax = axes[0, 0]
        speed = np.hypot(u, v)
        mesh = ax.pcolormesh(
            longitude[lo_j:hi_j],
            latitude[lo_i:hi_i],
            speed[lo_i:hi_i, lo_j:hi_j],
            shading="auto",
            cmap="viridis",
        )
        local_speed = speed[lo_i:hi_i, lo_j:hi_j]
        options = {} if np.any(local_speed > 0) else {"scale": 1}
        ax.quiver(
            longitude[lo_j:hi_j],
            latitude[lo_i:hi_i],
            u[lo_i:hi_i, lo_j:hi_j],
            v[lo_i:hi_i, lo_j:hi_j],
            **options,
        )
        ax.plot(longitude[j], latitude[i], "rx", label="Original candidate")
        if ci is not None:
            ax.plot(longitude[cj], latitude[ci], "w+", ms=10, label="Refined minimum")
            for r, style, label in (
                (b, "--", "Minimum-search window"),
                (a - 1, ":", "Rotation perimeter"),
            ):
                ii = np.clip(
                    [ci - r, ci - r, ci + r, ci + r, ci - r], 0, len(latitude) - 1
                )
                jj = np.clip(
                    [cj - r, cj + r, cj + r, cj - r, cj - r], 0, len(longitude) - 1
                )
                ax.plot(longitude[jj], latitude[ii], style, color="white", label=label)
        if candidate.get("contour") is not None:
            contour = candidate["contour"]
            ax.plot(
                np.interp(contour[:, 1], np.arange(len(longitude)), longitude),
                np.interp(contour[:, 0], np.arange(len(latitude)), latitude),
                "r-",
                label="Boundary",
            )
        self.set_geographic_axes(
            ax, latitude, "Velocity field and search neighborhoods"
        )
        ax.legend(fontsize=7)
        fig.colorbar(mesh, ax=ax, label="Speed [m/s]")

        ax = axes[0, 1]
        indices = np.arange(max(0, pair_j - a - 1), min(len(longitude), pair_j + a + 3))
        ax.plot(indices, v[i, indices], "o-")
        for index in (pair_j, pair_j + 1):
            ax.axvline(index, color=".5", ls=":")
        for index in (pair_j - a, pair_j + 1 + a):
            ax.plot(index, v[i, index], "rx", ms=10)
        ax.axhline(0, color=".6", lw=1)
        ax.set(
            title="1 · EW section: opposite signs and outward growth",
            xlabel="Longitude grid index",
            ylabel="Northward velocity v [m/s]",
        )

        ax = axes[1, 0]
        indices = np.arange(max(0, i - a - 1), min(len(latitude), i + a + 2))
        ax.plot(indices, u[indices, j], "o-")
        ax.axvline(i, color=".5", ls=":")
        for index in (i - a, i + a):
            if 0 <= index < len(latitude):
                ax.plot(index, u[index, j], "rx", ms=10)
        ax.axhline(0, color=".6", lw=1)
        ax.set(
            title="2 · NS section through the original candidate",
            xlabel="Latitude grid index",
            ylabel="Eastward velocity u [m/s]",
        )

        ax = axes[1, 1]
        detector = NencioliCenterDetector(latitude, longitude, u, v, a, b)
        r = a - 1
        if (
            ci is not None
            and r <= ci < len(latitude) - r
            and r <= cj < len(longitude) - r
        ):
            angles = detector.extract_perimeter_angles(ci, cj)
            if angles is not None:
                turning = np.r_[angles, angles[0]]
                steps = np.angle(np.exp(1j * np.diff(turning)))
                ax.plot(
                    np.arange(len(steps) + 1),
                    np.r_[0, np.cumsum(np.rad2deg(steps))],
                    "o-",
                )
                ax.axhline(360, color="green", ls="--", label="One full turn")
                ax.legend(fontsize=8)
            else:
                ax.text(
                    0.5,
                    0.5,
                    "Perimeter contains missing or zero vectors",
                    ha="center",
                    transform=ax.transAxes,
                )
        else:
            ax.text(
                0.5,
                0.5,
                "No stable minimum with an in-grid perimeter",
                ha="center",
                transform=ax.transAxes,
            )
        ax.set(
            title="4 · Angular progression along the CCW perimeter",
            xlabel="Perimeter traversal index",
            ylabel="Cumulative direction change [degrees]",
        )
        for ax in axes.flat:
            ax.grid(alpha=0.2)
        fig.suptitle(f"Candidate {candidate['id']} · {candidate['reason_label']}")
        return fig

    def boundary(self, longitude, latitude, u, v, a, candidate):
        radius = candidate.get("region_radius")
        if radius is None:
            return None
        ci, cj = candidate["center_i"], candidate["center_j"]
        lat, lon, ul, vl = extract_local_region(
            latitude, longitude, u, v, ci, cj, radius
        )
        detector = NencioliBoundaryDetector(lat, lon, ul, vl)
        psi = detector.calculate_streamfunction()
        fig = Figure(figsize=(11, 4.5), constrained_layout=True)
        left, right = fig.subplots(1, 2)
        left.contour(lon, lat, psi, levels=20, colors=".55", linewidths=0.6)
        left.quiver(lon, lat, ul, vl)
        left.plot(longitude[cj], latitude[ci], "r+")
        contour = candidate.get("contour")
        rejected_example = False
        local = None
        if contour is None:
            contours = detector.find_closed_contours(radius, radius)
            if contours:
                local = max(contours, key=detector.calculate_contour_area)
                rejected_example = True
        if contour is not None:
            local = contour - np.array([ci - radius, cj - radius])
        if local is not None:
            left.plot(
                np.interp(local[:, 1], np.arange(len(lon)), lon),
                np.interp(local[:, 0], np.arange(len(lat)), lat),
                "r--" if rejected_example else "r-",
                lw=2,
                label=(
                    "Largest rejected closed contour"
                    if rejected_example
                    else "Accepted boundary"
                ),
            )
            left.legend(fontsize=7)
            extrema = detector.get_contour_extrema(local)
            inner, outer, labels = [], [], []
            for name, point in zip(("North", "South", "East", "West"), extrema):
                direction = point - [radius, radius]
                distance = np.linalg.norm(direction)
                if distance <= 1:
                    inner.append(np.nan)
                    outer.append(np.nan)
                    labels.append(name + "\nToo near center")
                    continue
                direction /= distance
                try:
                    inside = detector.interpolate_speed(
                        np.hypot(ul, vl), point - 0.5 * direction
                    )
                    outside = detector.interpolate_speed(
                        np.hypot(ul, vl), point + 0.5 * direction
                    )
                except ValueError:
                    inner.append(np.nan)
                    outer.append(np.nan)
                    labels.append(name + "\nOutside region")
                    continue
                inner.append(inside)
                outer.append(outside)
                labels.append(name + ("\nPass" if outside > inside else "\nFail"))
            x = np.arange(4)
            right.bar(x - 0.18, inner, 0.36, label="Half a cell inside")
            right.bar(x + 0.18, outer, 0.36, label="Half a cell outside")
            right.set_xticks(x, labels)
            right.legend(fontsize=8)
            if candidate.get("source") == "circular_fallback":
                right.set_title("Estimated circle · growth is not required")
            elif rejected_example:
                right.set_title("Largest rejected contour · example of failed growth")
            else:
                right.set_title("Outside speed must exceed inside at all extrema")
            right.set_ylabel("Speed [m/s]")
        else:
            right.text(
                0.5,
                0.5,
                f"{candidate.get('closed_contours', 0)} closed contours\n"
                f"{candidate.get('growing_contours', 0)} pass growth at all four extrema\n\n"
                "No boundary accepted",
                ha="center",
                va="center",
                transform=right.transAxes,
            )
            right.set_axis_off()
        self.set_geographic_axes(left, lat, "Local streamfunction and velocity")
        return fig
