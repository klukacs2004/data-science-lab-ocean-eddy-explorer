"""OpenTopoMap introduction for the welcome page only."""

import math
import numpy as np
import plotly.graph_objects as go
from .base import BaseInteractivePlotter


class InteractiveSlaMapPlotter(BaseInteractivePlotter):
    def add_velocity(self, fig, sla_day, u, v, stride=2):
        """Draw sampled local east/north vectors; length represents 72 h at that velocity."""
        fig.add_traces(
            self.velocity_traces(sla_day, u, v, stride, map_coordinates=True)
        )
        fig.update_layout(
            legend={
                "groupclick": "togglegroup",
                "orientation": "h",
                "y": 0.02,
                "x": 0.01,
            }
        )
        return fig

    def detection(
        self,
        sla_day,
        *,
        field_label="Sea Level Anomaly",
        colorbar_title="SLA [cm]",
        vmax_cm=None,
        vmin_cm=None,
        colorscale="RdBu_r",
    ):
        uri, corners, _, center_lat, vmax = self.prepare_sla_overlay(
            sla_day, vmax_cm=vmax_cm, vmin_cm=vmin_cm, colorscale=colorscale
        )
        field = sla_day.transpose("latitude", "longitude")
        lon = ((np.asarray(field.longitude.values, dtype=float) + 180) % 360) - 180
        lat = np.asarray(field.latitude.values, dtype=float)

        map_width = 1220
        right_margin, extra_east = 95, 1.0
        west, east = corners[0][0], corners[1][0]
        visible_lon = east - west + extra_east
        zoom = math.log2(360 * (map_width - right_margin) / (512 * visible_lon))
        map_center_lon = west + visible_lon / 2

        fig = go.Figure()
        lon_grid, lat_grid = np.meshgrid(lon, lat)
        sla_values = field.values * 100.0  # meters to centimeters
        valid = np.isfinite(sla_values)

        # Transparent markers provide hover values over the raster overlay.
        fig.add_trace(
            go.Scattermap(
                lon=lon_grid[valid],
                lat=lat_grid[valid],
                mode="markers",
                marker=dict(size=12, color="rgba(0,0,0,0.001)"),
                customdata=sla_values[valid],
                hovertemplate=(
                    f"<b>{field_label}</b><br>"
                    "Longitude: %{lon:.3f}°<br>"
                    "Latitude: %{lat:.3f}°<br>"
                    "Value: %{customdata:.2f} cm<extra></extra>"
                ),
                showlegend=False,
            )
        )

        # Use the same sampled palette and limits as the raster overlay.
        from matplotlib import colormaps
        from matplotlib.colors import to_hex

        palette = [
            [i / 255, to_hex(colormaps[colorscale](i / 255))] for i in range(256)
        ]
        minimum = -vmax if vmin_cm is None else float(vmin_cm)
        # A separate marker supplies the SLA colorbar for the raster overlay.
        fig.add_trace(
            go.Scattermap(
                lon=[map_center_lon],
                lat=[center_lat],
                mode="markers",
                marker=dict(
                    size=1,
                    color=[minimum],
                    colorscale=palette,
                    cmin=minimum,
                    cmax=vmax,
                    showscale=True,
                    colorbar=dict(
                        title=colorbar_title,
                        thickness=18,
                        len=0.75,
                        x=1.02,
                        xanchor="left",
                        tickformat=".1f",
                    ),
                ),
                hoverinfo="skip",
                showlegend=False,
            )
        )

        fig.update_layout(
            title="",
            map=dict(
                style=self.MAP_STYLE,
                center=dict(lat=center_lat + 0.5, lon=map_center_lon + 1.0),
                zoom=zoom,
                layers=[
                    dict(
                        sourcetype="raster",
                        source=["https://a.tile.opentopomap.org/{z}/{x}/{y}.png"],
                        below="traces",
                        opacity=0.5,
                    ),
                    dict(
                        sourcetype="image",
                        source=uri,
                        coordinates=corners,
                        below="traces",
                    ),
                ],
            ),
            autosize=True,
            height=620,
            margin=dict(l=0, r=right_margin, t=20, b=35),
            legend=dict(orientation="h", y=-0.03),
            hovermode="closest",
        )
        return self.apply_theme(fig)
