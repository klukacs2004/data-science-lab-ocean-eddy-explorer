from datetime import date, datetime
import unittest

import numpy as np
import xarray as xr
from skimage.measure import find_contours

from .method_utils import (
    EddyDetection,
    RotationDirection,
    standardize_chelton,
    standardize_nencioli,
    standardize_okubo_weiss,
)


class StandardizationTests(unittest.TestCase):
    def setUp(self):
        self.lat = np.linspace(30, 32, 9)
        self.lon = np.linspace(225, 227, 9)
        self.mask = np.zeros((9, 9), dtype=bool)
        self.mask[2:7, 2:7] = True
        self.contour = find_contours(self.mask.astype(float), 0.5)[0]
        self.field = xr.DataArray(
            np.zeros((9, 9)),
            dims=("latitude", "longitude"),
            coords={"latitude": self.lat, "longitude": self.lon},
        )
        self.patch = {
            "id": 17,
            "sla": self.field.transpose("longitude", "latitude"),
            "region": self.mask.T,
            "polarity": "maximum",
            "amplitude_m": 0.12,
        }
        self.ow = {
            "id": 42,
            "contour": self.contour.copy(),
            "diameter_km": 900,
            "area_cells": 999,
            "accepted": True,
        }
        self.nencioli = (
            4,
            4,
            RotationDirection.CLOCKWISE,
            self.contour.copy(),
            999.0,
            False,
            False,
        )
        self.day = date(1993, 1, 1)

    def test_identical_geometry_has_identical_common_measurements(self):
        c = standardize_chelton([self.patch], self.day)[0]
        n = standardize_nencioli([self.nencioli], self.day, self.lat, self.lon)[0]
        w = standardize_okubo_weiss([self.ow], self.day, self.lat, self.lon)[0]
        for eddy in (c, n, w):
            self.assertIsInstance(eddy, EddyDetection)
            self.assertEqual(eddy.date, self.day)
            np.testing.assert_allclose(eddy.contour, c.contour)
            np.testing.assert_allclose(eddy.contour[0], eddy.contour[-1])
            self.assertAlmostEqual(eddy.latitude, c.latitude)
            self.assertAlmostEqual(eddy.longitude, c.longitude)
            self.assertAlmostEqual(eddy.area_km2, c.area_km2)
            self.assertAlmostEqual(eddy.radius_km, np.sqrt(c.area_km2 / np.pi))
            self.assertTrue(np.all(eddy.contour[:, 1] < 0))
        self.assertEqual((c.id, n.id, w.id), (17, 1, 42))
        self.assertEqual(
            (c.method, n.method, w.method), ("chelton", "nencioli", "okubo_weiss")
        )
        self.assertEqual(
            (c.polarity, n.polarity, w.polarity),
            ("anticyclonic", "anticyclonic", "unknown"),
        )
        self.assertEqual(c.amplitude_cm, 12.0)
        self.assertIsNone(n.amplitude_cm)
        self.assertIsNone(w.amplitude_cm)
        self.assertNotEqual(n.radius_km, 999.0)
        self.assertNotEqual(w.radius_km, 450.0)

    def test_chelton_handles_either_dimension_order_without_mutation(self):
        original = self.patch["region"].copy()
        expected = standardize_chelton([self.patch], self.day)[0]
        patch = {**self.patch, "sla": self.field, "region": self.mask}
        actual = standardize_chelton([patch], self.day)[0]
        np.testing.assert_allclose(expected.contour, actual.contour)
        np.testing.assert_array_equal(original, self.patch["region"])

    def test_nencioli_boundary_provenance_is_matched_by_center(self):
        raw = self.nencioli
        for source in ("streamfunction", "circular_fallback", None):
            diagnostics = {
                "boundaries": [
                    {"center_i": 0, "center_j": 0, "accepted": False, "source": None},
                    {"center_i": 4, "center_j": 4, "accepted": True, "source": source},
                ]
            }
            detection = standardize_nencioli(
                [raw], self.day, self.lat, self.lon, diagnostics=diagnostics
            )[0]
            self.assertEqual(detection.boundary_source, source)
            self.assertEqual(detection.has_reliable_radius, source == "streamfunction")
            self.assertEqual(len(raw), 7)
            np.testing.assert_array_equal(raw[3], self.contour)
        unknown = standardize_nencioli([raw], self.day, self.lat, self.lon)[0]
        self.assertIsNone(unknown.boundary_source)
        self.assertFalse(unknown.has_reliable_radius)

    def test_nencioli_rotation_uses_hemisphere(self):
        for lat, direction, expected in (
            (self.lat, RotationDirection.COUNTERCLOCKWISE, "cyclonic"),
            (-self.lat[::-1], RotationDirection.CLOCKWISE, "cyclonic"),
            (-self.lat[::-1], RotationDirection.COUNTERCLOCKWISE, "anticyclonic"),
            (np.linspace(-1, 1, 9), RotationDirection.CLOCKWISE, "unknown"),
        ):
            result = (4, 4, direction, self.contour, 1.0, False, False)
            actual = standardize_nencioli([result], self.day, lat, self.lon)[0]
            self.assertEqual(actual.polarity, expected)
        minimum = {**self.patch, "polarity": "minimum"}
        self.assertEqual(
            standardize_chelton([minimum], self.day)[0].polarity, "cyclonic"
        )

    def test_spherical_area_known_rectangle(self):
        # 90-degree spherical triangle with vertices at (0,0), (0,90), (90,0)
        # has area pi/2 * R^2. Exercise the shared geometry independently.
        from .method_utils import _contour_geometry

        contour = np.array([[0, 0], [0, 90], [90, 0], [0, 0]], dtype=float)
        _, _, area = _contour_geometry(contour)
        self.assertAlmostEqual(area / (6371.0**2), np.pi / 2)
        self.assertAlmostEqual(_contour_geometry(contour[::-1])[2], area)

    def test_halo_vorticity_sign_uses_hemisphere_without_changing_geometry(self):
        for latitude, mean, expected in (
            (self.lat, 1e-5, "cyclonic"),
            (self.lat, -1e-5, "anticyclonic"),
            (-self.lat[::-1], -1e-5, "cyclonic"),
            (-self.lat[::-1], 1e-5, "anticyclonic"),
        ):
            with self.subTest(latitude=latitude[0], mean=mean):
                original = standardize_okubo_weiss(
                    [self.ow], self.day, latitude, self.lon
                )[0]
                actual = standardize_okubo_weiss(
                    [self.ow],
                    self.day,
                    latitude,
                    self.lon,
                    vorticity_by_id={42: mean},
                )[0]
                self.assertEqual(actual.polarity, expected)
                self.assertEqual(actual.id, 42)
                self.assertEqual(actual.area_km2, original.area_km2)
                np.testing.assert_array_equal(actual.contour, original.contour)

    def test_halo_unavailable_or_equatorial_polarity_is_not_invented(self):
        for means in (None, {}, {42: 0.0}, {42: np.nan}, {42: np.inf}):
            with self.subTest(means=means):
                actual = standardize_okubo_weiss(
                    [self.ow],
                    self.day,
                    self.lat,
                    self.lon,
                    vorticity_by_id=means,
                )
                self.assertEqual(len(actual), 1)
                self.assertEqual(actual[0].polarity, "unknown")
        equatorial = standardize_okubo_weiss(
            [self.ow],
            self.day,
            np.linspace(-1, 1, 9),
            self.lon,
            vorticity_by_id={42: 1e-5},
        )[0]
        self.assertEqual(equatorial.polarity, "unknown")

    def test_longitude_wrap_does_not_make_large_polygon(self):
        from .method_utils import _contour_geometry

        contour = np.array([[30, 179], [30, -179], [31, -179], [31, 179], [30, 179.0]])
        _, lon, area = _contour_geometry(contour)
        self.assertLess(abs(abs(lon) - 180), 1e-6)
        self.assertTrue(15000 < area < 25000)

    def test_missing_coordinates_open_and_out_of_grid_contours_raise(self):
        with self.assertRaises(ValueError):
            standardize_nencioli([self.nencioli], self.day)
        for contour in (self.contour[:-1], self.contour + 100, np.full((5, 2), np.nan)):
            with self.subTest(contour=contour), self.assertRaises(ValueError):
                standardize_okubo_weiss(
                    [{**self.ow, "contour": contour}], self.day, self.lat, self.lon
                )

    def test_empty_and_rejected_outputs(self):
        for adapter in (
            standardize_chelton,
            standardize_nencioli,
            standardize_okubo_weiss,
        ):
            self.assertEqual(adapter([], self.day), [])
        self.assertEqual(
            standardize_okubo_weiss([{**self.ow, "accepted": False}], self.day), []
        )
        self.assertEqual(
            standardize_chelton([{**self.patch, "accepted": False}], self.day), []
        )

    def test_dates_are_normalized(self):
        for day in ("1993-01-01", datetime(1993, 1, 1, 12)):
            self.assertEqual(standardize_chelton([self.patch], day)[0].date, self.day)

    def test_actual_detector_results_are_supported(self):
        from .chelton_method import detect_at_threshold
        from .halo_method import HaloDetector
        from .nencioli_method import detect_eddies

        c = np.linspace(-1, 1, 41)
        x, y = np.meshgrid(c, c)
        # Off-grid center avoids exact zero-component ties in Nencioli's sign checks.
        x, y = x - 0.017, y - 0.013
        h = 0.3 * np.exp(-(x * x + y * y) / 0.15)
        lat, lon = 30 + c, 225 + c
        field = xr.DataArray(
            h.T,
            dims=("longitude", "latitude"),
            coords={"latitude": lat, "longitude": lon},
        )
        chelton = detect_at_threshold(field, 0.05, "maximum")
        nencioli = detect_eddies(y * h, -x * h, lat, lon, 2, 2)
        ow = HaloDetector(h, lat, lon, y * h, -x * h).detect_eddies()
        for raw, adapted in (
            (chelton, standardize_chelton(chelton, self.day)),
            (nencioli, standardize_nencioli(nencioli, self.day, lat, lon)),
            (ow, standardize_okubo_weiss(ow, self.day, lat, lon)),
        ):
            self.assertGreater(len(raw), 0)
            self.assertEqual(len(raw), len(adapted))
            self.assertTrue(all(e.radius_km > 0 for e in adapted))
