"""Trajectories using the same geographic axes as the Nencioli explorer."""

from collections import Counter
import math

import plotly.graph_objects as go
from plotly.colors import qualitative
from .base import BaseInteractivePlotter


def track_center(eddy):
    if (
        eddy.native_center_latitude is not None
        and eddy.native_center_longitude is not None
    ):
        return eddy.native_center_latitude, eddy.native_center_longitude
    return eddy.latitude, eddy.longitude


class NencioliTrackingPlotter(BaseInteractivePlotter):
    def trajectories(
        self,
        tracks,
        dataset_grid=None,
        method_label="Nencioli",
        vorticity_by_detection=None,
    ):
        fig = go.Figure()
        if dataset_grid:
            grid_lon, grid_lat = [], []
            for i, latitude in enumerate(dataset_grid["latitude"]):
                for j, longitude in enumerate(dataset_grid["longitude"]):
                    if dataset_grid["valid_sla"][i][j]:
                        grid_lon.append((longitude + 180) % 360 - 180)
                        grid_lat.append(latitude)
            fig.add_trace(
                go.Scattermap(
                    lon=grid_lon,
                    lat=grid_lat,
                    mode="markers",
                    name="Dataset grid",
                    marker={"color": "rgba(30,60,80,0.65)", "size": 5},
                    hovertemplate="Dataset grid point<br>Longitude: %{lon:.3f}°<br>Latitude: %{lat:.3f}°<extra></extra>",
                    meta={"kind": "dataset_grid"},
                    legendgroup="dataset_grid",
                )
            )
        latitudes = []
        for index, track in enumerate(tracks):
            if track.id == 3:
                for eddy in track.detections:
                    print(eddy.date, track_center(eddy))
            color = qualitative.Dark24[index % len(qualitative.Dark24)]
            centers = [track_center(e) for e in track.detections]
            counts = Counter(centers)
            latitudes.extend(lat for lat, _ in centers)
            for gap in (False, True):
                x, y = [], []
                for i in range(1, len(centers)):
                    if (
                        (track.detections[i].date - track.detections[i - 1].date).days
                        > 1
                    ) != gap:
                        continue
                    x.extend([centers[i - 1][1], centers[i][1], None])
                    y.extend([centers[i - 1][0], centers[i][0], None])
                if x:
                    # Map traces do not support dashed strokes; draw separated gap segments.
                    if gap:
                        gap_x, gap_y = [], []
                        for start in range(0, len(x), 3):
                            for step in range(0, 12, 2):
                                for fraction in (step / 12, (step + 1) / 12):
                                    gap_x.append(
                                        x[start] + fraction * (x[start + 1] - x[start])
                                    )
                                    gap_y.append(
                                        y[start] + fraction * (y[start + 1] - y[start])
                                    )
                                gap_x.append(None)
                                gap_y.append(None)
                        x, y = gap_x, gap_y
                    fig.add_trace(
                        go.Scattermap(
                            lon=x,
                            lat=y,
                            mode="lines",
                            line={"color": color, "width": 6},
                            legendgroup=str(track.id),
                            showlegend=False,
                            hoverinfo="skip",
                            meta={"track_id": track.id},
                        )
                    )
            vorticity_hover = ""
            if vorticity_by_detection is not None:
                vorticity_hover = (
                    "<br>Mean relative vorticity: %{customdata[5]:.3e} s⁻¹"
                )
            fig.add_trace(
                go.Scattermap(
                    lon=[lon for _, lon in centers],
                    lat=[lat for lat, _ in centers],
                    mode="markers+text",
                    name=f"Track {track.id}",
                    legendgroup=str(track.id),
                    meta={"track_id": track.id},
                    marker={"color": color, "size": 5},
                    text=[
                        {"cyclonic": "●", "anticyclonic": "◆"}.get(e.polarity, "■")
                        for e in track.detections
                    ],
                    textposition="top center",
                    textfont={"color": color, "size": 17},
                    customdata=[
                        [
                            track.id,
                            e.date.isoformat(),
                            e.radius_km,
                            e.polarity,
                            counts[center],
                        ]
                        + (
                            [vorticity_by_detection[(e.date, e.id)]]
                            if vorticity_by_detection is not None
                            else []
                        )
                        for e, center in zip(track.detections, centers)
                    ],
                    hovertemplate="Track %{customdata[0]} · %{customdata[1]}<br>%{lat:.3f}°N, %{lon:.3f}°E<br>"
                    "Geometric radius: %{customdata[2]:.2f} km<br>%{customdata[3]}<br>"
                    "Observations at this exact center in this track: %{customdata[4]}"
                    + vorticity_hover
                    + "<extra></extra>",
                )
            )
        longitudes = [track_center(e)[1] for track in tracks for e in track.detections]
        west, east = (min(longitudes), max(longitudes)) if longitudes else (-135, -120)
        south, north = (min(latitudes), max(latitudes)) if latitudes else (25, 45)
        span = max(east - west, (north - south) * 1.4, 0.1)
        zoom = max(0, min(12, math.log2(360 * 800 / (512 * span * 1.3))))
        fig.update_layout(
            title=f"{method_label} eddy trajectories",
            height=620,
            map={
                "style": self.MAP_STYLE,
                "center": {"lon": (west + east) / 2, "lat": (south + north) / 2},
                "zoom": zoom,
                "layers": [
                    {
                        "sourcetype": "raster",
                        "opacity": 0.5,
                        "source": ["https://a.tile.opentopomap.org/{z}/{x}/{y}.png"],
                        "below": "traces",
                    }
                ],
            },
            legend={"groupclick": "togglegroup"},
            margin={"l": 0, "r": 0, "t": 50, "b": 35},
        )
        return self.apply_theme(fig)
