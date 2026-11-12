"""Combined standardized boundaries on an axis-based SLA heatmap."""

import plotly.graph_objects as go
from plotly.subplots import make_subplots
from .chelton import InteractiveCheltonPlotter
from .base import BaseInteractivePlotter
from ..comparison import METHODS


class ComparisonPlotter(BaseInteractivePlotter):
    def detection(self, height, detections, u, v):
        fig = InteractiveCheltonPlotter().detection(height, patches=[])
        fig.add_traces(self.velocity_traces(height, u, v))
        for key, label, color in METHODS:
            selected = [e for e in detections if e.method == key]
            lon, lat = [], []
            for e in selected:
                lon.extend(e.contour[:, 1].tolist() + [None])
                lat.extend(e.contour[:, 0].tolist() + [None])
            fig.add_trace(
                go.Scatter(
                    x=lon,
                    y=lat,
                    mode="lines",
                    line={"color": color, "width": 2.5},
                    name=f"{label} ({len(selected)})",
                    legendgroup=key,
                    hoverinfo="skip",
                )
            )
            fig.add_trace(
                go.Scatter(
                    x=[e.longitude for e in selected],
                    y=[e.latitude for e in selected],
                    mode="markers",
                    marker={"color": color, "size": 10},
                    legendgroup=key,
                    showlegend=False,
                    customdata=[
                        [e.method, e.id, e.polarity, e.radius_km, e.area_km2, label]
                        for e in selected
                    ],
                    hovertemplate=(
                        "<b>%{customdata[5]} · %{customdata[1]}</b><br>"
                        "%{customdata[2]}<br>Area radius: %{customdata[3]:.2f} km<br>"
                        "Area: %{customdata[4]:.1f} km²<br>Click to find in the table<extra></extra>"
                    ),
                )
            )
        fig.update_layout(
            legend={"orientation": "h", "y": -0.15, "groupclick": "togglegroup"},
            margin={"l": 55, "r": 30, "t": 50, "b": 90},
            title="Standardized detections on the same SLA field",
        )
        return self.apply_theme(fig)

    def statistics(self, detections, summary):
        fig = make_subplots(
            rows=1,
            cols=2,
            subplot_titles=("Accepted detections", "Area-equivalent radius [km]"),
        )
        fig.add_trace(
            go.Bar(
                x=[s["label"] for s in summary],
                y=[s["count"] for s in summary],
                marker_color=[s["color"] for s in summary],
                text=[s["count"] for s in summary],
                textposition="auto",
                showlegend=False,
                hovertemplate="%{x}: %{y}<extra></extra>",
            ),
            row=1,
            col=1,
        )
        for key, label, color in METHODS:
            radii = [e.radius_km for e in detections if e.method == key]
            fig.add_trace(
                go.Box(
                    y=radii,
                    name=label,
                    marker_color=color,
                    boxpoints="all",
                    jitter=0.2,
                    pointpos=0,
                    showlegend=False,
                ),
                row=1,
                col=2,
            )
        fig.update_yaxes(
            title_text="Detections", rangemode="tozero", tickformat=",d", row=1, col=1
        )
        fig.update_yaxes(title_text="Radius [km]", rangemode="tozero", row=1, col=2)
        fig.update_layout(
            template="plotly_white",
            height=360,
            margin={"l": 55, "r": 20, "t": 45, "b": 80},
        )
        return self.apply_theme(fig)
