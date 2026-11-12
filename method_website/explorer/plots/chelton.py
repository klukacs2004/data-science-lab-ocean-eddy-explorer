from matplotlib.figure import Figure

import numpy as np
from skimage.measure import find_contours

import plotly.graph_objects as go

from .base import BaseInteractivePlotter, BasePlotter


class InteractiveCheltonPlotter(BaseInteractivePlotter):
    def detection(self, sla_day, patches, diagnostics=None) -> go.Figure:
        field = sla_day.transpose("latitude", "longitude")
        lon = ((np.asarray(field.longitude.values, dtype=float) + 180) % 360) - 180
        lat = np.asarray(field.latitude.values, dtype=float)
        sla_cm = np.asarray(field.values, dtype=float) * 100.0
        finite = np.abs(sla_cm[np.isfinite(sla_cm)])
        vmax = float(finite.max()) if finite.size and finite.max() > 0 else 1.0
        fig = go.Figure(
            go.Heatmap(
                x=lon,
                y=lat,
                z=sla_cm,
                colorscale="RdBu_r",
                zmin=-vmax,
                zmax=vmax,
                colorbar={"title": "SLA [cm]"},
                hoverongaps=False,
                hovertemplate=(
                    "<b>Sea Level Anomaly</b><br>Longitude: %{x:.3f}°<br>"
                    "Latitude: %{y:.3f}°<br>SLA: %{z:.2f} cm<extra></extra>"
                ),
            )
        )
        for patch in patches:
            mask = sla_day.copy(data=np.asarray(patch["region"], dtype=bool))
            mask = mask.transpose("latitude", "longitude").values

            for contour in find_contours(mask.astype(float), 0.5):
                fig.add_trace(
                    go.Scatter(
                        x=np.interp(contour[:, 1], np.arange(len(lon)), lon),
                        y=np.interp(contour[:, 0], np.arange(len(lat)), lat),
                        mode="lines",
                        line=dict(color="green", width=2),
                        hoverinfo="skip",
                        showlegend=False,
                    )
                )

            iy, ix = np.nonzero(mask)
            if iy.size == 0:
                continue

            center_lon = float(lon[ix].mean())
            center_lat_patch = float(lat[iy].mean())
            properties = [
                f"<b>Candidate ID: {patch['id']}</b>",
                f"Center longitude: {center_lon:.3f}°",
                f"Center latitude: {center_lat_patch:.3f}°",
            ]
            properties.extend(
                [
                    f"Polarity: {patch['polarity']}",
                    f"Threshold: {patch['threshold_m']*100:.1f} cm",
                    f"Amplitude: {patch['amplitude_m']*100:.2f} cm",
                    f"Maximum pair distance: {patch['diameter_km']:.1f} km",
                    f"Area-equivalent radius: {patch['effective_radius_km']:.1f} km",
                    f"Connected pixels: {patch['size']}",
                ]
            )

            fig.add_trace(
                go.Scatter(
                    x=[center_lon],
                    y=[center_lat_patch],
                    mode="markers+text",
                    text=[str(patch["id"])],
                    textposition="middle center",
                    textfont=dict(size=10, color="black"),
                    marker=dict(size=10, color="#18744c", opacity=0.85),
                    customdata=[[patch["id"], "<br>".join(properties)]],
                    hovertemplate="%{customdata[1]}<br>Click to inspect<extra></extra>",
                    showlegend=False,
                )
            )

        rejected = [row for row in (diagnostics or []) if not row["accepted"]]
        if rejected:
            fig.add_trace(
                go.Scatter(
                    x=[((row["longitude"] + 180) % 360) - 180 for row in rejected],
                    y=[row["latitude"] for row in rejected],
                    mode="markers",
                    marker={"size": 8, "color": "#b86c17"},
                    name="Rejected candidates",
                    visible="legendonly",
                    customdata=[
                        [row["id"], row["reason"], row["threshold_m"] * 100]
                        for row in rejected
                    ],
                    hovertemplate="Candidate %{customdata[0]}<br>%{customdata[1]}<br>Threshold %{customdata[2]:.0f} cm<br>Click to inspect<extra></extra>",
                )
            )

        self.set_geographic_axes(fig, lat, title="SLA contours and candidate decisions")
        fig.update_layout(
            template="plotly_white",
            autosize=True,
            height=620,
            margin={"l": 55, "r": 30, "t": 50, "b": 90},
            legend={"orientation": "h", "y": -0.15},
            hovermode="closest",
            clickmode="event",
            dragmode="pan",
        )
        return self.apply_theme(fig)


class CheltonPlotter(BasePlotter):

    def detection(self, sla_day, patches) -> Figure:
        field = sla_day.transpose("latitude", "longitude")

        lon = field.longitude.values
        lat = field.latitude.values
        sla_cm = field.values * 100.0

        vmax = float(np.nanmax(np.abs(sla_cm)))
        vmax = 1.0 if vmax == 0 else vmax

        fig = Figure(figsize=(10, 6), constrained_layout=True)
        ax = fig.subplots()

        image = ax.pcolormesh(
            lon,
            lat,
            sla_cm,
            shading="auto",
            cmap="RdBu_r",
            vmin=-vmax,
            vmax=vmax,
        )

        fig.colorbar(image, ax=ax, label="SLA [cm]")

        for index, patch in enumerate(patches, start=1):
            index = patch["id"]

            mask = (
                sla_day.copy(data=np.asarray(patch["region"], dtype=bool))
                .transpose("latitude", "longitude")
                .values
            )

            ax.contour(
                lon,
                lat,
                mask.astype(float),
                levels=[0.5],
                colors="black",
                linewidths=1.2,
            )

            iy, ix = np.nonzero(mask)
            if iy.size:
                ax.text(
                    lon[ix].mean(),
                    lat[iy].mean(),
                    str(index),
                    ha="center",
                    va="center",
                    fontsize=8,
                    bbox={
                        "facecolor": "#c2e0e7",
                        "edgecolor": "none",
                        "alpha": 0.1,
                    },
                )

        date = np.datetime_as_string(sla_day.time.values, unit="D")

        self.set_geographic_axes(
            ax=ax,
            latitude=lat,
            title=f"Chelton Detection overview — {date} ({len(patches)} accepted)",
        )

        return fig

    def filtering(self, sla_day, filtered_day) -> Figure:
        background_day = sla_day - filtered_day

        fields = [
            sla_day,
            background_day,
            filtered_day,
        ]
        titles = ["Original SLA", "Estimated background", "Processed SLA"]

        vmax = max(float(np.nanmax(np.abs(field.values * 100.0))) for field in fields)
        vmax = 1.0 if vmax == 0 else vmax

        fig = Figure(figsize=(15, 5), constrained_layout=True)
        axes = fig.subplots(1, 3, sharex=True, sharey=True)

        image = None
        for ax, field, title in zip(axes, fields, titles):
            field = field.transpose("latitude", "longitude")

            image = ax.pcolormesh(
                field.longitude.values,
                field.latitude.values,
                field.values * 100.0,
                shading="auto",
                cmap="RdBu_r",
                vmin=-vmax,
                vmax=vmax,
            )
            self.set_geographic_axes(
                ax=ax, latitude=field.latitude.values, title=title, set_y_title=False
            )

        axes[0].set_ylabel("Latitude [°]")

        if image is not None:
            fig.colorbar(image, ax=list(axes), label="SLA [cm]", shrink=0.85)

        return fig

    def threshold(
        self, filtered_day, threshold_m, patches, polarity="maximum"
    ) -> Figure:
        field = filtered_day.transpose("latitude", "longitude")

        if polarity == "maximum":
            candidates = field.values > threshold_m
        elif polarity == "minimum":
            candidates = field.values < threshold_m
        else:
            raise ValueError("Polarity must be 'maximum' or 'minimum'.")

        accepted = np.zeros(field.shape, dtype=bool)
        valid = np.isfinite(field.values)

        for patch in patches:
            region = filtered_day.copy(
                data=np.asarray(patch["region"], dtype=bool)
            ).transpose("latitude", "longitude")
            accepted |= region.values

        fig = Figure(figsize=(12, 5), constrained_layout=True)
        axes = fig.subplots(1, 2, sharex=True, sharey=True)

        for ax, mask, title in zip(
            axes, [candidates, accepted], ["Threshold candidates", "Accepted patches"]
        ):
            values = np.ma.array(mask.astype(float), mask=~valid)

            ax.pcolormesh(
                field.longitude.values,
                field.latitude.values,
                values,
                shading="auto",
                cmap="Blues",
                vmin=0,
                vmax=1,
            )

            self.set_geographic_axes(
                ax=ax, latitude=field.latitude.values, title=title, set_y_title=False
            )
            ax.set_facecolor("lightgray")

        axes[0].set_ylabel("Latitude [°]")

        fig.suptitle(f"SLA threshold: {threshold_m * 100:g} cm · {polarity}")

        return fig

    def diagnostics(self, filtered_day, diagnostics) -> Figure:
        from matplotlib.lines import Line2D

        field = filtered_day.transpose("latitude", "longitude")
        lon = field.longitude.values
        lat = field.latitude.values
        sla_cm = field.values * 100.0

        vmax = float(np.nanmax(np.abs(sla_cm)))
        vmax = 1.0 if vmax == 0 else vmax

        fig = Figure(figsize=(10, 6), layout="tight")
        ax = fig.subplots()

        image = ax.pcolormesh(
            lon, lat, sla_cm, shading="auto", cmap="RdBu_r", vmin=-vmax, vmax=vmax
        )
        fig.colorbar(image, ax=ax, label="Processed SLA [cm]")

        # A scan can have hundreds of rejected regions at overlapping levels.
        # The complete record stays in the table; label accepted regions on maps.
        scan = any("scan_candidate_id" in item for item in diagnostics)
        for candidate in diagnostics:
            if scan and not candidate["accepted"]:
                continue
            mask = (
                filtered_day.copy(data=candidate["region"])
                .transpose("latitude", "longitude")
                .values
            )

            color = "green" if candidate["accepted"] else "red"

            # Padding also outlines candidates touching the map edges.
            padded = np.pad(mask.astype(float), 1)
            padded_lon = np.pad(lon, 1, mode="reflect", reflect_type="odd")
            padded_lat = np.pad(lat, 1, mode="reflect", reflect_type="odd")

            ax.contour(
                padded_lon,
                padded_lat,
                padded,
                levels=[0.5],
                colors=color,
                linewidths=1.2,
            )

            iy, ix = np.nonzero(mask)

            if iy.size:
                # Put the label on a candidate cell near its centre.
                distance = (ix - ix.mean()) ** 2 + (iy - iy.mean()) ** 2
                centre = np.argmin(distance)

                ax.text(
                    lon[ix[centre]],
                    lat[iy[centre]],
                    str(candidate["id"]),
                    ha="center",
                    va="center",
                    fontsize=8,
                    bbox={
                        "facecolor": "#c2e0e7",
                        "edgecolor": "none",
                        "alpha": 0.1,
                    },
                )

        handles = [Line2D([0], [0], color="green", label="Accepted")]
        if not scan:
            handles.append(Line2D([0], [0], color="red", label="Rejected"))
        ax.legend(handles=handles)

        self.set_geographic_axes(
            ax=ax,
            latitude=lat,
            title=(
                "Accepted scan candidates · all decisions in table"
                if scan
                else "Candidate acceptance diagnostics"
            ),
        )
        ax.set(
            xlim=(lon.min(), lon.max()),
            ylim=(lat.min(), lat.max()),
        )

        return fig

    def scan_summary(self, diagnostics) -> Figure:
        from collections import Counter

        fig = Figure(figsize=(12, 4), constrained_layout=True)
        axes = fig.subplots(1, 2, sharey=True)
        for ax, polarity in zip(axes, ("maximum", "minimum")):
            rows = [row for row in diagnostics if row["polarity"] == polarity]
            totals = Counter(round(row["threshold_m"] * 100) for row in rows)
            accepted = Counter(
                round(row["threshold_m"] * 100) for row in rows if row["accepted"]
            )
            thresholds = sorted(totals)
            ax.plot(
                thresholds,
                [totals[t] for t in thresholds],
                color="#7e92a9",
                label="Candidate regions",
            )
            ax.bar(
                thresholds,
                [accepted[t] for t in thresholds],
                color="#18744c",
                label="Accepted patches",
            )
            ax.set(title=polarity.capitalize(), xlabel="Threshold [cm]", ylabel="Count")
            ax.legend(fontsize=8)
            ax.grid(alpha=0.2)
        return fig

    def candidate(self, filtered_day, candidate, padding=5) -> Figure:
        field = filtered_day.transpose("latitude", "longitude")

        mask = (
            filtered_day.copy(data=np.asarray(candidate["region"], dtype=bool))
            .transpose("latitude", "longitude")
            .values
        )

        iy, ix = np.nonzero(mask)

        if iy.size == 0:
            raise ValueError("The selected candidate has an empty region.")

        y_slice = slice(
            max(0, int(iy.min()) - padding),
            min(field.sizes["latitude"], int(iy.max()) + padding + 1),
        )
        x_slice = slice(
            max(0, int(ix.min()) - padding),
            min(field.sizes["longitude"], int(ix.max()) + padding + 1),
        )

        cropped = field.isel(
            latitude=y_slice,
            longitude=x_slice,
        )
        cropped_mask = mask[y_slice, x_slice]

        lon = cropped.longitude.values
        lat = cropped.latitude.values
        sla_cm = cropped.values * 100.0

        vmax = float(np.nanmax(np.abs(sla_cm)))
        vmax = 1.0 if vmax == 0 else vmax

        fig = Figure(figsize=(12, 5), constrained_layout=True)
        ax, profile = fig.subplots(1, 2)

        image = ax.pcolormesh(
            lon, lat, sla_cm, shading="auto", cmap="RdBu_r", vmin=-vmax, vmax=vmax
        )
        fig.colorbar(image, ax=ax, label="Processed SLA [cm]")

        color = "green" if candidate["accepted"] else "darkorange"

        ax.contour(
            np.pad(lon, 1, mode="reflect", reflect_type="odd"),
            np.pad(lat, 1, mode="reflect", reflect_type="odd"),
            np.pad(cropped_mask.astype(float), 1),
            levels=[0.5],
            colors=color,
            linewidths=2,
        )

        extrema = candidate.get("extrema_indices")

        if extrema is not None and len(extrema) > 0:
            ax.scatter(
                filtered_day.longitude.values[extrema[:, 0]],
                filtered_day.latitude.values[extrema[:, 1]],
                marker="x",
                s=80,
                color="black",
                linewidths=2,
                zorder=5,
                label="Local extrema",
            )

            ax.legend()

        from scipy.ndimage import binary_erosion
        from eddy_detection.method_utils import CONNECTIVITY

        interior = binary_erosion(mask, structure=CONNECTIVITY, border_value=0)
        perimeter = mask & np.logical_not(interior)
        all_values = field.values[mask] * 100
        perimeter_values = field.values[perimeter] * 100
        bins = np.histogram_bin_edges(all_values, bins=16)
        profile.hist(
            all_values, bins=bins, color="#cbdce8", label="All candidate pixels"
        )
        profile.hist(
            perimeter_values,
            bins=bins,
            histtype="step",
            color="#064273",
            label="Perimeter pixels",
            linewidth=2,
        )
        basal = float(np.mean(perimeter_values))
        extremum = float(
            np.max(all_values)
            if candidate["polarity"] == "maximum"
            else np.min(all_values)
        )
        profile.axvline(basal, color="#b86c17", label=f"Perimeter mean: {basal:.2f} cm")
        profile.axvline(
            extremum, color="#176443", label=f"Extreme SSH: {extremum:.2f} cm"
        )
        profile.set(
            title=f"Amplitude from perimeter mean: {abs(extremum-basal):.2f} cm",
            xlabel="Processed SLA [cm]",
            ylabel="Pixels",
        )
        profile.legend(fontsize=8)
        self.set_geographic_axes(
            ax, lat, f"Candidate {candidate['id']} · {candidate['reason']}"
        )
        fig.suptitle(
            f"{candidate['polarity'].capitalize()} · threshold {candidate['threshold_m']*100:g} cm"
        )
        return fig
