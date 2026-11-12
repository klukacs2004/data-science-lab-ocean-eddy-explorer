"""Rotation evidence and cross-method matching on a shared daily field."""

from dataclasses import replace
from datetime import date
from unittest.mock import patch

import numpy as np
import xarray as xr
from django.test import SimpleTestCase

from eddy_detection.method_utils import EddyDetection
from .comparison import pair_metrics, run_comparison


class ComparisonPolarityTests(SimpleTestCase):
    def run_vortex(self):
        coords = np.linspace(-1, 1, 41)
        x, y = np.meshgrid(coords - 0.017, coords - 0.013)
        height = 0.3 * np.exp(-(x * x + y * y) / 0.15)

        def field(values):
            return xr.DataArray(
                values,
                dims=("latitude", "longitude"),
                coords={"latitude": 30 + coords, "longitude": 225 + coords},
            )

        return run_comparison(
            field(height),
            field(y * height),
            field(-x * height),
            date(1993, 1, 1),
            {
                "contour_interval_cm": 2,
                "max_diameter_km": 600,
                "filter_passes": 2,
                "filter_mode": "none",
                "a": 2,
                "b": 2,
            },
        )

    def test_actual_clockwise_vortex_has_resolved_halo_polarity_and_exports(self):
        result = self.run_vortex()
        halo = [e for e in result["detections"] if e.method == "okubo_weiss"]
        self.assertGreater(len(halo), 0)
        self.assertTrue(all(e.polarity == "anticyclonic" for e in halo))
        rows = [
            row for row in result["detection_rows"] if row["method"] == "okubo_weiss"
        ]
        for row in rows:
            self.assertLess(row["mean_relative_vorticity_s"], 0)
            self.assertEqual(row["polarity_source"], "Signed contour-mean vorticity")
        summary = next(row for row in result["summary"] if row["key"] == "okubo_weiss")
        self.assertEqual(summary["anticyclonic"], len(halo))
        self.assertEqual(summary["unknown"], 0)
        halo_pairs = [
            row for row in result["match_rows"] if row["method_b"] == "okubo_weiss"
        ]
        self.assertTrue(halo_pairs)
        self.assertTrue(all(row["polarity_b"] == "anticyclonic" for row in halo_pairs))

    def test_missing_vorticity_preserves_detections_and_explains_unknown(self):
        with patch(
            "explorer.comparison.representative_vorticity",
            return_value=({}, {1: "Missing vorticity within contour"}),
        ):
            result = self.run_vortex()
        halo = [
            row for row in result["detection_rows"] if row["method"] == "okubo_weiss"
        ]
        self.assertTrue(halo)
        self.assertTrue(all(row["polarity"] == "unknown" for row in halo))
        self.assertIn("Missing vorticity", halo[0]["polarity_source"])
        self.assertIsNone(halo[0]["mean_relative_vorticity_s"])
        self.assertTrue(
            any(row["polarity_check"] == "unresolved" for row in result["match_rows"])
        )

    def test_pairs_are_same_day_cross_method_candidates_with_explicit_polarity_check(
        self,
    ):
        contour = np.array(
            [
                [30.0, -130.0],
                [30.0, -129.0],
                [31.0, -129.0],
                [31.0, -130.0],
                [30.0, -130.0],
            ]
        )
        first = EddyDetection(
            1, "chelton", date(1993, 1, 1), 30.5, -129.5, "cyclonic", 50.0, contour
        )
        detections = [
            first,
            replace(first, id=2),
            replace(first, method="nencioli", polarity="anticyclonic"),
            replace(first, method="okubo_weiss", polarity="unknown"),
        ]
        pairs = pair_metrics(detections)
        self.assertEqual(len(pairs), 5)  # Same-method Chelton pair is excluded.
        self.assertEqual(sum(row["polarity_check"] == "opposite" for row in pairs), 2)
        self.assertEqual(sum(row["polarity_check"] == "unresolved" for row in pairs), 3)
        self.assertTrue(all(row["iou"] > 0.999999 for row in pairs))
        agreeing = pair_metrics([first, replace(first, method="nencioli")])
        self.assertEqual(agreeing[0]["polarity_check"], "agrees")


class ComparisonVelocityPlotTests(SimpleTestCase):
    def test_comparison_reuses_welcome_arrows_and_excludes_missing_samples(self):
        from plotly.graph_objects import Figure
        from .plots.comparison import ComparisonPlotter
        from .plots.sla_map import InteractiveSlaMapPlotter

        field = xr.DataArray(
            np.ones((5, 5)),
            dims=("latitude", "longitude"),
            coords={
                "latitude": np.arange(32.0, 33.25, 0.25),
                "longitude": np.arange(225.0, 226.25, 0.25),
            },
        )
        u, v = xr.ones_like(field) * 0.2, xr.ones_like(field) * 0.1
        u.values[0, 0] = np.nan
        v.values[2, 2] = np.nan
        field.values[4, 4] = np.nan
        comparison = ComparisonPlotter().detection(
            field.transpose(), [], u, v.transpose()
        )
        welcome = InteractiveSlaMapPlotter().add_velocity(Figure(), field, u, v)
        arrows, points = [
            trace for trace in comparison.data if trace.legendgroup == "velocity"
        ]
        original_arrows, original_points = welcome.data
        self.assertEqual(arrows.type, "scatter")
        self.assertEqual(tuple(arrows.x), tuple(original_arrows.lon))
        self.assertEqual(tuple(arrows.y), tuple(original_arrows.lat))
        self.assertEqual(
            arrows.line.to_plotly_json(), original_arrows.line.to_plotly_json()
        )
        self.assertEqual(
            points.marker.to_plotly_json(), original_points.marker.to_plotly_json()
        )
        np.testing.assert_array_equal(points.customdata, original_points.customdata)
        self.assertEqual(
            len(points.x), 6
        )  # 3×3 samples minus one missing SLA/u/v each.
        self.assertTrue(all(longitude < 0 for longitude in points.x))
        self.assertIn("Longitude: %{x:.3f}", points.hovertemplate)
        self.assertIn("Speed:", points.hovertemplate)
        self.assertEqual(comparison.layout.legend.groupclick, "togglegroup")
        with self.assertRaises(ValueError):
            ComparisonPlotter().detection(
                field, [], u.assign_coords(longitude=u.longitude + 0.1), v
            )
