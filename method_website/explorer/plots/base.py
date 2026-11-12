import base64
from io import BytesIO
import numpy as np
import rasterio
from PIL import Image
from matplotlib import colormaps
from scipy.ndimage import binary_erosion
from rasterio.transform import from_origin
from rasterio.warp import (
    calculate_default_transform,
    reproject,
    Resampling,
    transform as transform_coords,
)

import plotly.graph_objects as go
from matplotlib.figure import Figure


class BasePlotter:

    @staticmethod
    def to_base64(fig: Figure, dpi: int = 140) -> str:
        # Embedded diagnostics and downloaded PNGs share the explorer palette.
        from matplotlib.colors import to_rgba
        from matplotlib.text import Text

        for ax in fig.axes:
            ax.set_facecolor("none")
            ax.tick_params(colors="#183747")
            for spine in ax.spines.values():
                spine.set_edgecolor("#6f98a9")
            for line in (*ax.get_xgridlines(), *ax.get_ygridlines()):
                line.set_color("#6f98a9")
            legend = ax.get_legend()
            if legend is not None:
                legend.get_frame().set_facecolor("#c2e0e7")
                legend.get_frame().set_edgecolor("#abcbd5")
                legend.get_frame().set_alpha(0.95)
        for label in fig.findobj(Text):
            if to_rgba(label.get_color())[:3] == (0.0, 0.0, 0.0):
                label.set_color("#183747")
        with BytesIO() as buffer:
            fig.savefig(buffer, format="png", dpi=dpi, transparent=True)

            return base64.b64encode(buffer.getvalue()).decode("ascii")

    @staticmethod
    def set_geographic_axes(ax, latitude, title: str = "", set_y_title: bool = True):
        import numpy as np

        mean_lat = float(np.mean(latitude))

        ax.set_xlabel("Longitude [°]")
        if set_y_title:
            ax.set_ylabel("Latitude [°]")
        ax.set_aspect(1.0 / np.cos(np.deg2rad(mean_lat)))
        ax.grid(alpha=0.2)
        ax.set_title(title)


class BaseInteractivePlotter:

    # Match the card while keeping the existing raster basemap and its opacity.
    MAP_STYLE = {
        "version": 8,
        "sources": {},
        "layers": [
            {
                "id": "ocean-background",
                "type": "background",
                "paint": {"background-color": "#a1c9d5"},
            }
        ],
    }

    @staticmethod
    def velocity_arrow_segments(lon, lat, east, north):
        """Shared geographic arrow geometry: 72-hour visual scale, no origin dots."""
        line_lon, line_lat = [], []
        for x, y, ue, vn in zip(lon, lat, east, north):
            # Convert a fixed-time displacement to local geographic coordinates.
            dx, dy = ue * 259.2, vn * 259.2  # km over 72 hours; visual scaling only
            speed = np.hypot(dx, dy)
            if speed == 0:
                continue
            cosine = max(np.cos(np.deg2rad(y)), 1e-6)

            def point(e, n):
                return x + np.rad2deg(e / (6371 * cosine)), y + np.rad2deg(n / 6371)

            tip = point(dx, dy)
            left = point(0.72 * dx - 0.14 * dy, 0.72 * dy + 0.14 * dx)
            right = point(0.72 * dx + 0.14 * dy, 0.72 * dy - 0.14 * dx)
            line_lon.extend([x, tip[0], None, left[0], tip[0], right[0], None])
            line_lat.extend([y, tip[1], None, left[1], tip[1], right[1], None])
        return line_lon, line_lat

    @classmethod
    def velocity_traces(cls, sla_day, u, v, stride=2, *, map_coordinates=False):
        """Shared arrow style, sampling and hover data for map and Cartesian plots."""
        import xarray as xr

        field, u, v = xr.align(sla_day, u, v, join="exact")
        field, u, v = (
            array.transpose("latitude", "longitude").isel(
                latitude=slice(None, None, stride), longitude=slice(None, None, stride)
            )
            for array in (field, u, v)
        )
        lon, lat = np.meshgrid(
            ((u.longitude.values + 180) % 360) - 180, u.latitude.values
        )
        valid = (
            np.isfinite(u.values) & np.isfinite(v.values) & np.isfinite(field.values)
        )
        lon, lat, east, north = lon[valid], lat[valid], u.values[valid], v.values[valid]
        line_lon, line_lat = cls.velocity_arrow_segments(lon, lat, east, north)
        trace_type = go.Scattermap if map_coordinates else go.Scatter
        x, y = ("lon", "lat") if map_coordinates else ("x", "y")
        return [
            trace_type(
                **{x: line_lon, y: line_lat},
                mode="lines",
                line={"color": "#142d3a", "width": 1.2},
                name="Geostrophic velocity",
                legendgroup="velocity",
                hoverinfo="skip",
            ),
            trace_type(
                **{x: lon, y: lat},
                mode="markers",
                marker={"size": 6, "color": "rgba(0,0,0,0)"},
                customdata=np.column_stack((east, north, np.hypot(east, north))),
                legendgroup="velocity",
                showlegend=False,
                hovertemplate=(
                    f"<b>Geostrophic velocity</b><br>Longitude: %{{{x}:.3f}}°<br>"
                    f"Latitude: %{{{y}:.3f}}°<br>"
                    "Eastward u: %{customdata[0]:.3f} m/s<br>Northward v: %{customdata[1]:.3f} m/s<br>"
                    "Speed: %{customdata[2]:.3f} m/s<extra></extra>"
                ),
            ),
        ]

    @staticmethod
    def apply_theme(fig: go.Figure):
        """Let the containing ocean-coloured card show through every plot."""
        fig.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font={"color": "#183747"},
            legend={"bgcolor": "rgba(0,0,0,0)", "font": {"color": "#183747"}},
            hoverlabel={
                "bgcolor": "#173f54",
                "bordercolor": "#6f98a9",
                "font": {"color": "#edf8fb"},
            },
        )
        fig.update_xaxes(gridcolor="rgba(49,78,95,0.18)", zerolinecolor="#7d9daa")
        fig.update_yaxes(gridcolor="rgba(49,78,95,0.18)", zerolinecolor="#7d9daa")
        return fig

    @staticmethod
    def set_geographic_axes(
        fig: go.Figure,
        latitude,
        title: str = "",
        set_y_title: bool = True,
    ):
        mean_lat = float(np.mean(latitude))

        fig.update_layout(
            title=title,
            xaxis_title="Longitude [°]",
            yaxis_title="Latitude [°]" if set_y_title else None,
        )

        fig.update_yaxes(
            scaleanchor="x",
            scaleratio=1.0 / np.cos(np.deg2rad(mean_lat)),
            showgrid=True,
        )

    @staticmethod
    def prepare_sla_overlay(
        sla_day,
        coastal_buffer_cells=1,
        upscale=2,
        vmax_cm=None,
        vmin_cm=None,
        colorscale="RdBu_r",
    ):
        if not isinstance(upscale, int) or upscale < 1:
            raise ValueError("upscale must be a positive integer")

        field = sla_day.transpose("latitude", "longitude")
        lon = ((np.asarray(field.longitude.values, dtype=float) + 180) % 360) - 180
        lat = np.asarray(field.latitude.values, dtype=float)
        z = np.asarray(field.values, dtype=float) * 100.0

        lon_order, lat_order = np.argsort(lon), np.argsort(lat)[::-1]
        lon, lat = lon[lon_order], lat[lat_order]
        z = z[np.ix_(lat_order, lon_order)]

        if lon.size < 2 or lat.size < 2:
            raise ValueError("Need at least two grid centers along each dimension")

        dx, dy = float(np.median(np.diff(lon))), float(np.median(-np.diff(lat)))
        if (
            dx <= 0
            or dy <= 0
            or not np.allclose(np.diff(lon), dx)
            or not np.allclose(np.diff(lat), -dy)
        ):
            raise ValueError("Expected a regular longitude/latitude grid")

        finite = np.isfinite(z)
        if not finite.any():
            raise ValueError("No finite SLA values found")

        vmax = (
            (float(np.nanmax(np.abs(z))) or 1.0) if vmax_cm is None else float(vmax_cm)
        )
        if not np.isfinite(vmax) or (vmin_cm is None and vmax <= 0):
            raise ValueError("Colour scale limit must be positive and finite")
        vmin = -vmax if vmin_cm is None else float(vmin_cm)
        if not np.isfinite(vmin) or vmin >= vmax:
            raise ValueError(
                "Colour scale minimum must be finite and below its maximum"
            )
        valid = (
            binary_erosion(finite, iterations=coastal_buffer_cells, border_value=1)
            if coastal_buffer_cells
            else finite
        )
        rgba = colormaps[colorscale](
            np.clip((np.nan_to_num(z, nan=vmin) - vmin) / (vmax - vmin), 0, 1)
        )
        rgba[..., 3] = np.where(valid, 0.92, 0.0)
        src_rgba = np.rint(rgba * 255).astype(np.uint8)

        west, east = float(lon[0] - dx / 2), float(lon[-1] + dx / 2)
        north, south = float(lat[0] + dy / 2), float(lat[-1] - dy / 2)
        src_transform = from_origin(west, north, dx, dy)

        dst_transform, width, height = calculate_default_transform(
            "EPSG:4326", "EPSG:3857", lon.size, lat.size, west, south, east, north
        )
        dst_transform *= rasterio.Affine.scale(1 / upscale, 1 / upscale)
        if width is None or height is None:
            raise ValueError("Could not determine destination raster dimensions")
        width, height = width * upscale, height * upscale
        dst_rgba = np.zeros((height, width, 4), dtype=np.uint8)

        for channel in range(4):
            reproject(
                source=src_rgba[..., channel],
                destination=dst_rgba[..., channel],
                src_transform=src_transform,
                src_crs="EPSG:4326",
                dst_transform=dst_transform,
                dst_crs="EPSG:3857",
                resampling=Resampling.nearest,
            )

        x0, y0 = dst_transform * (0, 0)
        x1, y1 = dst_transform * (width, height)
        corner_lon, corner_lat = transform_coords(
            "EPSG:3857",
            "EPSG:4326",
            [x0, x1, x1, x0],
            [y0, y0, y1, y1],
        )[:2]
        corners = [[float(x), float(y)] for x, y in zip(corner_lon, corner_lat)]

        buf = BytesIO()
        Image.fromarray(dst_rgba, "RGBA").save(buf, format="PNG")
        uri = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode(
            "ascii"
        )

        return uri, corners, (west + east) / 2, (south + north) / 2, vmax
