from django.urls import reverse
from typing import Any, cast
from django.http import HttpResponse

from unittest.mock import patch

import numpy as np
import xarray as xr
from django.test import RequestFactory, SimpleTestCase

from eddy_detection.nencioli_method import detect_eddies, RotationDirection
from .views import nencioli_detection_page
from .plots.nencioli import NencioliPlotter
from .forms import NencioliDetectionForm


class TestResponse(HttpResponse):
    """Django's test client adds template context to its HTTP responses."""

    context: Any


class NencioliPlotTests(SimpleTestCase):
    def test_detected_contour_uses_geographic_coordinates(self):
        longitude = np.array([10.0, 12.0, 15.0])
        latitude = np.array([40.0, 43.0, 47.0])
        field = np.ones((3, 3))
        contour = np.array([[0.0, 0.0], [0.0, 1.5], [2.0, 2.0], [0.0, 0.0]])
        for direction in (
            RotationDirection.CLOCKWISE,
            RotationDirection.COUNTERCLOCKWISE,
        ):
            with self.subTest(direction=direction):
                fig = NencioliPlotter().velocity_field(
                    longitude,
                    latitude,
                    field,
                    field,
                    field,
                    a=2,
                    eddies=[(1, 1, direction, contour)],
                )
                np.testing.assert_allclose(
                    np.asarray(fig.axes[0].patches[0].get_path().vertices),
                    [[10.0, 40.0], [13.5, 40.0], [15.0, 47.0], [10.0, 40.0]],
                )
                self.assertTrue(NencioliPlotter().to_base64(fig))


class NencioliEmptyDetectionTests(SimpleTestCase):
    def setUp(self):
        self.coordinates = np.arange(9, dtype=float)
        self.velocity = np.zeros((9, 9), dtype=float)

    def test_no_centers_returns_empty_list(self):
        results = detect_eddies(
            self.velocity,
            self.velocity,
            self.coordinates,
            self.coordinates,
            a=2,
            b=1,
        )
        self.assertEqual(results, [])

    def test_rejected_boundaries_return_empty_list(self):
        with (
            patch(
                "eddy_detection.nencioli_method.NencioliCenterDetector.detect_centers",
                return_value=[(4, 4, RotationDirection.CLOCKWISE)],
            ),
            patch(
                "eddy_detection.nencioli_method.NencioliBoundaryDetector.select_eddy_boundary",
                return_value=None,
            ),
        ):
            results = detect_eddies(
                self.velocity,
                self.velocity,
                self.coordinates,
                self.coordinates,
                a=2,
                b=1,
            )
        self.assertEqual(results, [])

    def test_post_with_no_eddies_renders_plot(self):
        field = xr.DataArray(
            self.velocity,
            dims=("latitude", "longitude"),
            coords={"latitude": self.coordinates, "longitude": self.coordinates},
        )
        with (
            patch("explorer.forms.get_available_years", return_value=["2026"]),
            patch("explorer.forms.get_dates_for_year", return_value=["2026-10-29"]),
            patch("explorer.views.load_sla_day", return_value=field),
            patch("explorer.views.load_velocity_field", return_value=(field, field)),
            patch("explorer.views.render") as render,
        ):
            request = RequestFactory().post(
                reverse("nencioli_detection"),
                {
                    "year": "2026",
                    "day": "2026-10-29",
                    "detection_mode": "single",
                    "a": 2,
                    "b": 1,
                    "a_min": 2,
                    "a_max": 4,
                    "b_min": 1,
                    "b_max": 4,
                },
            )
            nencioli_detection_page(request)

        context = render.call_args.args[2]
        self.assertFalse(context["form"].errors)
        self.assertTrue(context["plot_image"])


class NencioliInvestigationPageTests(SimpleTestCase):
    def setUp(self):
        coordinate = np.arange(41, dtype=float) * 0.01
        x, y = np.meshgrid(np.arange(41) - 20.2, np.arange(41) - 20.2)
        envelope = np.exp(-(x * x + y * y) / 50)

        def field(values):
            return xr.DataArray(
                values,
                dims=("latitude", "longitude"),
                coords={"latitude": coordinate, "longitude": coordinate},
            )

        self.enterContext(
            patch("explorer.forms.get_available_years", return_value=["1993"])
        )
        self.enterContext(
            patch("explorer.forms.get_dates_for_year", return_value=["1993-01-01"])
        )
        self.enterContext(
            patch("explorer.views.load_sla_day", return_value=field(envelope))
        )
        self.enterContext(
            patch(
                "explorer.views.load_velocity_field",
                return_value=(field(-y * envelope), field(x * envelope)),
            )
        )
        self.payload = {
            "year": "1993",
            "day": "1993-01-01",
            "detection_mode": "single",
            "a": 3,
            "b": 2,
        }

    def test_single_mode_does_not_require_hidden_sweep_fields(self):
        form = NencioliDetectionForm(self.payload)
        self.assertTrue(form.is_valid(), form.errors)

    def test_sweep_validates_active_fields_and_rejects_negative_radii(self):
        payload = {
            "year": "1993",
            "day": "1993-01-01",
            "detection_mode": "sweep",
            "a_min": 2,
            "a_max": 3,
            "b_min": 1,
            "b_max": 2,
        }
        self.assertTrue(NencioliDetectionForm(payload).is_valid())
        invalid = NencioliDetectionForm({**payload, "b_min": -1})
        self.assertFalse(invalid.is_valid())
        self.assertIn("b_min", invalid.errors or {})

    def test_overview_contains_candidate_trace_and_comparison(self):
        response = cast(
            TestResponse, self.client.post(reverse("nencioli_detection"), self.payload)
        )
        self.assertEqual(response.status_code, 200)
        summary = response.context["diagnostic_summary"]
        self.assertEqual(summary["centers"], 1)
        self.assertEqual(summary["accepted"], 1)
        self.assertEqual(
            summary["total"],
            summary["accepted"] + summary["rejected"] + summary["duplicates"],
        )
        self.assertContains(response, 'id="candidate-table"')
        self.assertContains(
            response, "They are not the paper's published detection counts."
        )
        self.assertContains(response, 'id="nencioli-candidate-data"')

    def test_candidate_buttons_inspect_accepted_and_rejected_candidates(self):
        overview = cast(
            TestResponse, self.client.post(reverse("nencioli_detection"), self.payload)
        )
        rows = overview.context["diagnostics"]
        for status in ("accepted", "rejected", "duplicate"):
            row = next(row for row in rows if row["status"] == status)
            with self.subTest(status=status):
                response = cast(
                    TestResponse,
                    self.client.post(
                        reverse("nencioli_detection"),
                        {**self.payload, "inspect_candidate": row["id"]},
                    ),
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    response.context["selected_candidate"]["id"], row["id"]
                )
                self.assertTrue(response.context["candidate_image"])
                if status == "accepted":
                    self.assertTrue(response.context["boundary_image"])

    def test_invalid_candidate_retains_results_and_shows_field_error(self):
        response = cast(
            TestResponse,
            self.client.post(
                reverse("nencioli_detection"), {**self.payload, "candidate_id": 99999}
            ),
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("candidate_id", response.context["form"].errors)
        self.assertEqual(response.context["diagnostic_summary"]["accepted"], 1)

    def test_sweep_configuration_drills_down_without_single_fields(self):
        payload = {
            "year": "1993",
            "day": "1993-01-01",
            "detection_mode": "sweep",
            "a_min": 2,
            "a_max": 3,
            "b_min": 1,
            "b_max": 2,
        }
        response = cast(
            TestResponse, self.client.post(reverse("nencioli_detection"), payload)
        )
        self.assertContains(response, 'id="nencioli-sweep"')
        self.assertEqual(len(response.context["sweep_rows"]), 4)
        response = cast(
            TestResponse,
            self.client.post(
                reverse("nencioli_detection"),
                {**payload, "inspect_configuration": "3,2"},
            ),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["run_settings"]["a"], 3)
        self.assertEqual(response.context["diagnostic_summary"]["accepted"], 1)

    def test_get_and_malformed_configuration_render_without_analysis(self):
        response = cast(TestResponse, self.client.get(reverse("nencioli_detection")))
        self.assertContains(response, "Why can results differ from the paper?")
        response = cast(
            TestResponse,
            self.client.post(
                reverse("nencioli_detection"),
                {**self.payload, "inspect_configuration": "bad"},
            ),
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].non_field_errors())


class CheltonInvestigationPageTests(SimpleTestCase):
    def setUp(self):
        x, y = np.meshgrid(np.arange(33), np.arange(33), indexing="ij")
        values = 0.2 * np.exp(-((x - 10) ** 2 + (y - 14) ** 2) / 8) - 0.18 * np.exp(
            -((x - 23) ** 2 + (y - 18) ** 2) / 8
        )
        self.field = xr.DataArray(
            values,
            dims=("longitude", "latitude"),
            coords={
                "latitude": np.linspace(30, 34, 33),
                "longitude": np.linspace(10, 14, 33),
                "time": np.datetime64("1993-01-01"),
            },
        )
        self.enterContext(
            patch("explorer.forms.get_available_years", return_value=["1993"])
        )
        self.enterContext(
            patch("explorer.forms.get_dates_for_year", return_value=["1993-01-01"])
        )
        self.enterContext(patch("explorer.views.load_sla_day", return_value=self.field))
        self.payload = {
            "year": "1993",
            "day": "1993-01-01",
            "filter_mode": "none",
            "detection_mode": "single",
            "threshold_cm": 3,
            "polarity": "maximum",
        }

    def test_page_reports_measures_and_filter_comparison(self):
        response = cast(
            TestResponse, self.client.post(reverse("chelton_detection"), self.payload)
        )
        self.assertEqual(response.status_code, 200)
        self.assertGreater(response.context["diagnostic_summary"]["accepted"], 0)
        self.assertContains(response, "Area radius [km]")
        self.assertContains(response, "They are not the paper's published counts.")
        self.assertContains(response, 'id="chelton-candidate-data"')

    def test_full_scan_can_inspect_by_global_candidate_id(self):
        payload = {**self.payload, "detection_mode": "scan"}
        payload.pop("threshold_cm")
        payload.pop("polarity")
        response = cast(
            TestResponse, self.client.post(reverse("chelton_detection"), payload)
        )
        self.assertEqual(response.status_code, 200)
        accepted = response.context["accepted_patches"][0]
        raw = response.context["patches"]
        self.assertIn(accepted["id"], [p["id"] for p in raw])
        inspected = cast(
            TestResponse,
            self.client.post(
                reverse("chelton_detection"),
                {**payload, "inspect_candidate": accepted["id"]},
            ),
        )
        self.assertEqual(inspected.status_code, 200)
        self.assertEqual(inspected.context["selected_candidate"]["id"], accepted["id"])
        self.assertTrue(inspected.context["candidate_image"])
        self.assertEqual(len(inspected.context["selected_candidate"]["check_rows"]), 7)

    def test_paper_scale_mode_does_not_require_custom_sigma(self):
        response = cast(
            TestResponse,
            self.client.post(
                reverse("chelton_detection"),
                {**self.payload, "filter_mode": "paper_scale"},
            ),
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["form"].errors)
        self.assertAlmostEqual(response.context["filtering"]["cutoff_lon"], 20)
        self.assertAlmostEqual(response.context["filtering"]["cutoff_lat"], 10)

    def test_invalid_id_does_not_hide_results(self):
        response = cast(
            TestResponse,
            self.client.post(
                reverse("chelton_detection"), {**self.payload, "candidate_id": 99999}
            ),
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("candidate_id", response.context["form"].errors)
        self.assertContains(response, "Accepted patches")

    def test_get_and_required_custom_scale_errors(self):
        self.assertContains(
            self.client.get(reverse("chelton_detection")),
            "How does this compare with Chelton et al.?",
        )
        response = cast(
            TestResponse,
            self.client.post(
                reverse("chelton_detection"), {**self.payload, "filter_mode": "custom"}
            ),
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("sigma_cells", response.context["form"].errors)

    def test_threshold_plot_uses_polarity_instead_of_threshold_sign(self):
        from .plots.chelton import CheltonPlotter

        field = self.field - 0.2
        figure = CheltonPlotter().threshold(field, -0.1, [], polarity="maximum")
        np.testing.assert_array_equal(
            figure.axes[0].collections[0].get_array(),
            field.transpose("latitude", "longitude").values > -0.1,
        )
        field = self.field + 0.2
        figure = CheltonPlotter().threshold(field, 0.1, [], polarity="minimum")
        np.testing.assert_array_equal(
            figure.axes[0].collections[0].get_array(),
            field.transpose("latitude", "longitude").values < 0.1,
        )


class HaloExplorerTests(SimpleTestCase):
    def setUp(self):
        c = np.linspace(-1, 1, 31)
        x, y = np.meshgrid(c, c)
        h = 0.3 * np.exp(-(x * x + y * y) / 0.15)
        coords = {"latitude": 30 + c, "longitude": 10 + c}
        self.height = xr.DataArray(h.T, dims=("longitude", "latitude"), coords=coords)
        self.u = xr.DataArray(y * h, dims=("latitude", "longitude"), coords=coords)
        self.v = xr.DataArray(-x * h, dims=("latitude", "longitude"), coords=coords)
        for target, value in (
            ("explorer.forms.get_available_years", ["2020"]),
            ("explorer.forms.get_dates_for_year", ["2020-01-01"]),
            ("explorer.views.load_sla_day", self.height),
            ("explorer.views.load_velocity_field", (self.u, self.v)),
        ):
            mock = patch(target, return_value=value)
            mock.start()
            self.addCleanup(mock.stop)

    def post(self, **overrides):
        from django.urls import reverse

        return self.client.post(
            reverse("halo_detection"),
            {
                "year": "2020",
                "day": "2020-01-01",
                "contour_interval_cm": 2,
                "max_diameter_km": 600,
                "filter_passes": 2,
                **overrides,
            },
        )

    def test_get_routes_render(self):
        from django.urls import reverse

        for name in ("halo_detection", "halo_methodology"):
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "Halo")
        self.assertContains(
            self.client.get(reverse("halo_detection")), 'id="paper-comparison"'
        )

    def test_post_renders_sections_inspection_and_png_downloads(self):
        import base64
        import re

        response = self.post(inspect_candidate=1)
        self.assertEqual(response.status_code, 200)
        for section in (
            "overview",
            "accepted",
            "processing",
            "diagnostics",
            "inspector",
            "paper-comparison",
            "halo-candidates",
            "halo-map",
        ):
            self.assertContains(response, f'id="{section}"')
        self.assertContains(response, "Candidate 1")
        self.assertEqual(response.context["selected_candidate"]["id"], 1)
        images = re.findall(
            r'<img src="data:image/png;base64,([^"]+)"', response.content.decode()
        )
        self.assertEqual(len(images), 4)
        for data in images:
            self.assertTrue(base64.b64decode(data).startswith(b"\x89PNG"))
        candidates = response.context["diagnostics"]
        self.assertAlmostEqual(
            candidates[0]["level_cm"], candidates[0]["level"] * 100.0
        )
        self.assertEqual(
            response.context["paper_comparison"]["selected"],
            response.context["paper_comparison"]["defaults"],
        )

    def test_invalid_id_keeps_detection_visible(self):
        response = self.post(candidate_id=999999)
        self.assertContains(response, "This ID does not exist")
        self.assertContains(response, 'id="candidate-table"')
        self.assertIsNone(response.context["selected_candidate"])

    def test_custom_settings_have_independent_default_comparison(self):
        response = self.post(contour_interval_cm=4, filter_passes=0)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["run_settings"]["filter_passes"], 0)
        self.assertIn("defaults", response.context["paper_comparison"])
        self.assertContains(response, "Paper parameters: 2 cm")

    def test_empty_detection_still_has_inspector_and_diagnostics(self):
        with patch(
            "explorer.views.load_sla_day", return_value=xr.zeros_like(self.height)
        ):
            response = self.post()
        self.assertEqual(response.context["diagnostic_summary"]["total"], 0)
        self.assertContains(response, "No closed loops within the diameter limit")
        self.assertContains(response, 'id="inspector"')

    def test_invalid_parameters_do_not_run_detection(self):
        with patch("eddy_detection.halo_method.HaloDetector.detect_eddies") as detect:
            response = self.post(contour_interval_cm=0)
        detect.assert_not_called()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors)


class WelcomeSlaMapTests(SimpleTestCase):
    def test_intro_reuses_chelton_map_without_candidates(self):
        from django.urls import reverse
        from .plots.sla_map import InteractiveSlaMapPlotter

        field = xr.DataArray(
            np.arange(25).reshape(5, 5) / 100.0,
            dims=("latitude", "longitude"),
            coords={
                "latitude": np.arange(32.0, 33.25, 0.25),
                "longitude": np.arange(225.0, 226.25, 0.25),
            },
        )
        figure = InteractiveSlaMapPlotter().detection(field)
        self.assertEqual(len(figure.data), 2)  # SLA hover points and colourbar only.
        self.assertIn("opentopomap", figure.layout.map.layers[0].source[0])
        with (
            patch(
                "explorer.views.get_available_dates",
                return_value={"1993-01-01": "sample.nc"},
            ),
            patch("explorer.views.load_sla_day", return_value=field),
            patch(
                "explorer.views.InteractiveSlaMapPlotter.detection", return_value=figure
            ) as plot,
        ):
            response = self.client.get(reverse("welcome"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(plot.call_args.args), 1)
        self.assertContains(response, 'id="welcome-sla-map"')
        self.assertContains(response, "1993-01-01")
        self.assertContains(response, "OpenTopoMap")
        html = response.content.decode()
        self.assertLess(
            html.index('id="sla-introduction"'), html.index('class="method-grid"')
        )
        self.assertNotIn("Candidate ID", html)

    def test_no_data_keeps_method_cards_available(self):
        from django.urls import reverse

        with patch("explorer.views.get_available_dates", return_value={}):
            response = self.client.get(reverse("welcome"))
        self.assertContains(response, "No SLA data is currently available")
        self.assertContains(response, "Chelton Method")
        self.assertContains(response, "Nencioli Method")
        self.assertContains(response, "Halo Method")

    def test_reference_map_uses_cm_labels_and_preserves_missing_values(self):
        from .plots.sla_map import InteractiveSlaMapPlotter

        values = np.arange(25, dtype=float).reshape(5, 5) / 100
        values[2, 2] = np.nan
        field = xr.DataArray(
            values,
            dims=("latitude", "longitude"),
            coords={
                "latitude": np.arange(32.0, 33.25, 0.25),
                "longitude": np.arange(225.0, 226.25, 0.25),
            },
        )
        figure = InteractiveSlaMapPlotter().detection(
            field,
            field_label="Mean AVISO SLA · 1993–2012",
            colorbar_title="Mean SLA [cm]",
        )
        self.assertEqual(len(figure.data[0].customdata), 24)
        self.assertAlmostEqual(max(figure.data[0].customdata), 24)
        self.assertIn("Mean AVISO SLA", figure.data[0].hovertemplate)
        self.assertEqual(figure.data[1].marker.colorbar.title.text, "Mean SLA [cm]")
        with (
            patch("explorer.views.get_available_dates", return_value={}),
            patch("explorer.views.load_reference_mean", return_value=field),
        ):
            response = self.client.get(reverse("welcome"))
        self.assertContains(response, 'id="welcome-reference-map"')
        self.assertContains(response, "No SLA data is currently available")

    def test_reference_uses_finer_scale_with_consistent_raster_and_colorbar(self):
        from .plots.sla_map import InteractiveSlaMapPlotter

        daily = xr.DataArray(
            np.ones((5, 5)) * 0.1,
            dims=("latitude", "longitude"),
            coords={
                "latitude": np.arange(32.0, 33.25, 0.25),
                "longitude": np.arange(225.0, 226.25, 0.25),
            },
        )
        reference = daily * -0.1
        plotter = InteractiveSlaMapPlotter()
        for field in (daily, reference):
            figure = plotter.detection(field, vmax_cm=30)
            self.assertEqual(figure.data[1].marker.cmin, -30)
            self.assertEqual(figure.data[1].marker.cmax, 30)
            self.assertEqual(plotter.prepare_sla_overlay(field, vmax_cm=30)[-1], 30)
        with (
            patch(
                "explorer.views.get_available_dates",
                return_value={"1993-01-01": "unused"},
            ),
            patch("explorer.views.load_sla_day", return_value=daily),
            patch("explorer.views.load_reference_mean", return_value=reference),
            patch(
                "explorer.views.InteractiveSlaMapPlotter.detection",
                wraps=plotter.detection,
            ) as plotting,
        ):
            response = self.client.get(reverse("welcome"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(plotting.call_count, 2)
        self.assertAlmostEqual(plotting.call_args_list[0].kwargs["vmax_cm"], 10)
        self.assertAlmostEqual(plotting.call_args_list[1].kwargs["vmin_cm"], -1.01)
        self.assertAlmostEqual(plotting.call_args_list[1].kwargs["vmax_cm"], -0.99)
        self.assertEqual(plotting.call_args_list[1].kwargs["colorscale"], "viridis")

    def test_mean_palette_spans_observed_positive_values_and_matches_raster(self):
        from base64 import b64decode
        from io import BytesIO
        from PIL import Image
        from matplotlib import colormaps
        from .plots.sla_map import InteractiveSlaMapPlotter

        values = np.tile(np.linspace(2.3, 3.0, 5), (5, 1))
        field = xr.DataArray(
            values / 100,
            dims=("latitude", "longitude"),
            coords={
                "latitude": np.arange(32.0, 33.25, 0.25),
                "longitude": np.arange(225.0, 226.25, 0.25),
            },
        )
        plotter = InteractiveSlaMapPlotter()
        figure = plotter.detection(
            field, vmin_cm=2.3, vmax_cm=3.0, colorscale="viridis"
        )
        self.assertEqual(figure.data[1].marker.cmin, 2.3)
        self.assertEqual(figure.data[1].marker.cmax, 3.0)
        np.testing.assert_allclose(figure.data[0].customdata, values.ravel())
        uri, *_ = plotter.prepare_sla_overlay(
            field,
            coastal_buffer_cells=0,
            vmin_cm=2.3,
            vmax_cm=3.0,
            colorscale="viridis",
        )
        rgba = np.array(Image.open(BytesIO(b64decode(uri.split(",")[1]))))
        pixels = rgba[rgba[..., 3] > 0, :3]
        for position in (0.0, 0.5, 1.0):
            expected = np.rint(
                np.array(colormaps["viridis"](position)[:3]) * 255
            ).astype(int)
            self.assertTrue(np.any(np.all(pixels == expected, axis=1)))
        with (
            patch("explorer.views.get_available_dates", return_value={}),
            patch("explorer.views.load_reference_mean", return_value=field),
            patch(
                "explorer.views.InteractiveSlaMapPlotter.detection",
                wraps=plotter.detection,
            ) as plotting,
        ):
            self.client.get(reverse("welcome"))
        self.assertAlmostEqual(plotting.call_args.kwargs["vmin_cm"], 2.3)
        self.assertAlmostEqual(plotting.call_args.kwargs["vmax_cm"], 3.0)

    def test_velocity_vectors_use_aligned_coordinates_and_skip_missing_values(self):
        from .plots.sla_map import InteractiveSlaMapPlotter

        field = xr.DataArray(
            np.ones((5, 5)),
            dims=("latitude", "longitude"),
            coords={
                "latitude": np.arange(32.0, 33.25, 0.25),
                "longitude": np.arange(225.0, 226.25, 0.25),
            },
        )
        u, v = xr.ones_like(field) * 0.2, xr.zeros_like(field)
        u.values[0, 0] = np.nan
        plotter = InteractiveSlaMapPlotter()
        figure = plotter.add_velocity(plotter.detection(field), field, u, v, stride=1)
        lines, points = figure.data[-2:]
        self.assertEqual(len(points.lon), 24)
        self.assertGreater(lines.lon[1], lines.lon[0])
        self.assertEqual(lines.lat[1], lines.lat[0])
        self.assertAlmostEqual(points.customdata[0][2], 0.2)
        with self.assertRaises(ValueError):
            plotter.add_velocity(
                figure, field, u.assign_coords(longitude=u.longitude + 0.1), v
            )
        with (
            patch(
                "explorer.views.get_available_dates",
                return_value={"1993-01-01": "unused"},
            ),
            patch("explorer.views.load_sla_day", return_value=field),
            patch("explorer.views.load_reference_mean", return_value=field),
            patch("explorer.views.load_velocity_field", return_value=(u, v)) as loader,
        ):
            response = self.client.get(reverse("welcome"))
        loader.assert_called_once()
        self.assertTrue(response.context["velocity_shown"])
        self.assertContains(response, "daily geostrophic velocity")

    def test_missing_reference_does_not_hide_daily_map(self):
        field = xr.DataArray(
            np.ones((5, 5)) / 100,
            dims=("latitude", "longitude"),
            coords={
                "latitude": np.arange(32.0, 33.25, 0.25),
                "longitude": np.arange(225.0, 226.25, 0.25),
            },
        )
        with (
            patch(
                "explorer.views.get_available_dates",
                return_value={"1993-01-01": "unused"},
            ),
            patch("explorer.views.load_sla_day", return_value=field),
            patch("explorer.views.load_reference_mean", side_effect=OSError("missing")),
        ):
            response = self.client.get(reverse("welcome"))
        self.assertContains(response, 'id="welcome-sla-map"')
        self.assertContains(response, "reference mean field is currently unavailable")


class SharedSidebarTests(SimpleTestCase):
    def test_all_explorers_include_the_shared_resize_control(self):
        from django.urls import reverse

        with (
            patch("explorer.forms.get_available_years", return_value=["1993"]),
            patch("explorer.forms.get_dates_for_year", return_value=["1993-01-01"]),
        ):
            for name in (
                "chelton_detection",
                "nencioli_detection",
                "halo_detection",
                "chelton_tracker",
                "nencioli_tracker",
                "halo_tracker",
                "comparison",
            ):
                with self.subTest(page=name):
                    response = self.client.get(reverse(name))
                    self.assertEqual(response.status_code, 200)
                    self.assertContains(response, 'class="sidebar-resizer"', count=1)
                    self.assertContains(response, 'role="separator"')
                    self.assertContains(response, 'aria-controls="explorer-sidebar"')
                    self.assertContains(response, "explorer/sidebar.js", count=1)


class ComparisonTrackingTests(SimpleTestCase):
    def payload(self, duration=10):
        return dict(
            year="2000",
            day="2000-01-01",
            comparison_mode="tracking",
            duration_days=duration,
            min_count=1,
            filter_mode="none",
            a=2,
            b=2,
            contour_interval_cm=2,
            max_diameter_km=600,
            filter_passes=2,
        )

    def test_period_limits_and_missing_days(self):
        from datetime import date, timedelta
        from .forms import ComparisonTrackingForm

        dates = [(date(2000, 1, 1) + timedelta(days=i)).isoformat() for i in range(365)]
        with (
            patch("explorer.forms.get_available_years", return_value=["2000"]),
            patch("explorer.forms.get_dates_for_year", return_value=dates),
            patch(
                "explorer.datasets.get_available_dates",
                return_value=dict.fromkeys(dates),
            ),
        ):
            self.assertTrue(ComparisonTrackingForm(self.payload(365)).is_valid())
            self.assertIn(
                "duration_days", ComparisonTrackingForm(self.payload(366)).errors
            )
        with (
            patch("explorer.forms.get_available_years", return_value=["2000"]),
            patch("explorer.forms.get_dates_for_year", return_value=dates),
            patch(
                "explorer.datasets.get_available_dates", return_value={dates[0]: None}
            ),
        ):
            self.assertIn(
                "duration_days", ComparisonTrackingForm(self.payload()).errors
            )

    def test_distributions_and_censored_cycles(self):
        from datetime import date, timedelta
        from types import SimpleNamespace
        from .comparison_tracking import tracking_figures

        start = date(2000, 1, 1)

        def track(identifier, offset):
            detections = [
                SimpleNamespace(
                    date=start + timedelta(days=offset + i),
                    radius_km=20.0,
                    has_reliable_radius=True,
                )
                for i in range(10)
            ]
            return SimpleNamespace(
                id=identifier,
                start_date=detections[0].date,
                end_date=detections[-1].date,
                detections=detections,
            )

        result = {"tracks": [track(1, 0), track(2, 1)], "missing_days": []}
        f7, f8, summary = tracking_figures([result] * 3, start, 20, min_count=2)
        self.assertEqual(f7.data[0].y[10], 100.0)
        self.assertEqual(f7.data[1].y[0], 100.0)
        self.assertEqual(tuple(f7.layout.xaxis2.range), (0, 10))
        self.assertTrue(all(value is None for value in f8.data[0].y))
        _, included, _ = tracking_figures(
            [result] * 3, start, 20, min_count=2, include_censored=True
        )
        self.assertTrue(any(value == 20 for value in included.data[0].y))
        self.assertEqual(tuple(included.layout.xaxis.range), (0, 25))
        self.assertEqual(summary[0]["tracks"], 2)
        self.assertEqual(summary[0]["censored"], 1)
        self.assertEqual(summary[0]["complete"], 1)
        self.assertTrue(
            any(
                "No age bins" in annotation.text for annotation in f8.layout.annotations
            )
        )
        tracking_figures([{"tracks": [], "missing_days": []}] * 3, start, 20)

    def test_tracking_post_queues_without_running_science(self):
        from datetime import date, timedelta

        dates = [(date(2000, 1, 1) + timedelta(days=i)).isoformat() for i in range(10)]
        with (
            patch("explorer.forms.get_available_years", return_value=["2000"]),
            patch("explorer.forms.get_dates_for_year", return_value=dates),
            patch(
                "explorer.datasets.get_available_dates",
                return_value=dict.fromkeys(dates),
            ),
            patch(
                "explorer.comparison_jobs.enqueue",
                return_value={"id": "a" * 32, "status": "queued"},
            ) as enqueue,
            patch("explorer.comparison_jobs.ensure_worker"),
            patch("explorer.comparison_tracking.run_tracking_comparison") as runner,
            patch("explorer.comparison.run_comparison") as daily,
        ):
            response = self.client.post(reverse("comparison"), self.payload())
            self.assertEqual(response.status_code, 302)
            self.assertIn("job=" + "a" * 32, response.url)
            enqueue.assert_called_once()
            runner.assert_not_called()
            daily.assert_not_called()

    def test_enqueue_failure_displays_retry_message(self):
        from datetime import date, timedelta

        dates = [(date(2000, 1, 1) + timedelta(days=i)).isoformat() for i in range(10)]
        with (
            patch("explorer.forms.get_available_years", return_value=["2000"]),
            patch("explorer.forms.get_dates_for_year", return_value=dates),
            patch(
                "explorer.datasets.get_available_dates",
                return_value=dict.fromkeys(dates),
            ),
            patch(
                "explorer.comparison_jobs.enqueue",
                side_effect=OSError("disk unavailable"),
            ),
            self.assertLogs("explorer.views", level="ERROR"),
        ):
            response = self.client.post(reverse("comparison"), self.payload())
        self.assertContains(
            response, "The comparison could not be queued. Please try again."
        )

    def test_existing_runners_receive_selected_period_and_detection_settings(self):
        from datetime import date
        from .comparison_tracking import run_tracking_comparison

        settings = dict(
            day=date(2000, 1, 1),
            duration_days=365,
            a=2,
            b=2,
            filter_mode="none",
            sigma_cells=None,
            contour_interval_cm=3,
            max_diameter_km=500,
            filter_passes=1,
        )
        with (
            patch(
                "explorer.comparison_tracking.run_chelton_tracking", return_value={}
            ) as chelton,
            patch(
                "explorer.comparison_tracking.run_tracking", return_value={}
            ) as nencioli,
            patch(
                "explorer.comparison_tracking.run_halo_tracking", return_value={}
            ) as halo,
        ):
            self.assertEqual(len(run_tracking_comparison(settings)), 3)
            for runner in (chelton, nencioli, halo):
                parameters = runner.call_args.args[0]
                self.assertEqual(parameters["duration_days"], 365)
                self.assertEqual(parameters["day"], settings["day"])
                self.assertEqual(parameters["min_lifetime_days"], 1)
            self.assertEqual(chelton.call_args.args[0]["west_km"], 50)
            self.assertEqual(nencioli.call_args.args[0]["a"], 2)
            self.assertEqual(halo.call_args.args[0]["contour_interval_cm"], 3)
