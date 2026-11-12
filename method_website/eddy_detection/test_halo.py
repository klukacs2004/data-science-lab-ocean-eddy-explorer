"""Regression checks for the single-frame Halo reconstruction."""

import unittest
import numpy as np
from .halo_method import HaloDetector


class HaloTests(unittest.TestCase):
    def detector(self, height=None):
        coords = np.linspace(30, 31, 11)
        zero = np.zeros((11, 11))
        return HaloDetector(
            zero if height is None else height, coords, coords, zero, zero
        )

    @staticmethod
    def square(lo, hi):
        return np.array([[lo, lo], [lo, hi], [hi, hi], [hi, lo], [lo, lo]])

    def test_solid_rotation_has_negative_w(self):
        lat = np.linspace(30, 30.1, 21)
        lon = np.linspace(10, 10.1, 21)
        earth = 6371000.0
        y = earth * np.deg2rad(lat - lat[10])[:, None]
        x = earth * np.cos(np.deg2rad(lat))[:, None] * np.deg2rad(lon - lon[10])
        omega = 1e-5
        d = HaloDetector(
            np.zeros_like(x), lat, lon, np.broadcast_to(-omega * y, x.shape), omega * x
        )
        np.testing.assert_allclose(d.okubo_weiss_field(), -4 * omega**2, rtol=1e-5)

    def test_only_outermost_single_core_loop_survives(self):
        d = self.detector()
        labels = np.zeros((9, 9), dtype=int)
        labels[4, 4] = 1
        results, rows = d.combine_regions_and_contours(
            labels, [(0.0, self.square(3, 7)), (0.02, self.square(2, 8))], True
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["level"], 0.02)
        self.assertEqual(rows[0]["reason"], "nested_duplicate")

    def test_multiple_partial_and_missing_cores_rejected(self):
        d = self.detector()
        labels = np.zeros((9, 9), dtype=int)
        labels[3, 3], labels[5, 5] = 1, 2
        self.assertEqual(
            d.combine_regions_and_contours(labels, [(0.0, self.square(2, 8))], True)[1][
                0
            ]["reason"],
            "multiple_cores",
        )
        labels[5, 5] = 0
        labels[0, 0] = 1
        w = np.zeros_like(labels, dtype=float)
        w[0, 0] = -1
        self.assertEqual(
            d.combine_regions_and_contours(
                labels, [(0.0, self.square(2, 8))], True, core_field=w
            )[1][0]["reason"],
            "partial_core",
        )
        d.sla_field[5, 5] = np.nan
        self.assertEqual(
            d.combine_regions_and_contours(labels, [(0.0, self.square(2, 8))], True)[1][
                0
            ]["reason"],
            "missing_data",
        )

    def test_missing_filter_cells_stay_missing(self):
        field = np.ones((7, 7))
        field[3, 3] = np.nan
        filtered = HaloDetector.apply_hanning_filter(field)
        self.assertTrue(np.isnan(filtered[3, 3]))
        np.testing.assert_allclose(filtered[np.isfinite(filtered)], 1.0)

    def test_all_missing_and_constant_fields_are_empty(self):
        for field in (np.full((11, 11), np.nan), np.zeros((11, 11))):
            self.assertEqual(self.detector(field).detect_eddies(), [])

    def test_gaussian_vortex_is_one_detection(self):
        c = np.linspace(-1, 1, 81)
        x, y = np.meshgrid(c, c)
        h = 0.3 * np.exp(-(x * x + y * y) / 0.15)
        lat, lon = 30 + c, 10 + c
        # Northern-hemisphere geostrophic height maximum rotates clockwise.
        d = HaloDetector(h, lat, lon, y * h, -x * h)
        results = d.detect_eddies()
        self.assertEqual(len(results), 1)
        self.assertLess(results[0]["diameter_km"], 600)
