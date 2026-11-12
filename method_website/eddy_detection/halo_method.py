from typing import Any, Literal, overload

import numpy as np
from scipy.ndimage import convolve, label
from skimage.measure import find_contours
from matplotlib.path import Path

from .method_utils import _validate_grid, _validate_sla, haversine


class HaloDetector:
    def __init__(
        self,
        sla_field,
        latitude,
        longitude,
        u,
        v,
        contour_interval=0.02,
        max_diameter_km=600.0,
        filter_passes=2,
    ) -> None:
        """Single-frame Halo et al. (2014), section 2.3, inspired detector.

        Height is in metres, velocity in m/s. Supply absolute SSH/ADT to
        match the paper; the historical sla_field argument also accepts SLA.
        Core connectivity and outermost single-core selection are explicit
        reconstruction choices, not fully specified by the article.
        """
        sla_field, latitude, longitude, u, v = (
            np.asarray(a, dtype=float) for a in (sla_field, latitude, longitude, u, v)
        )
        if min(latitude.size, longitude.size) < 3:
            raise ValueError("At least three grid points per axis are required")
        if not np.isfinite(contour_interval) or contour_interval <= 0:
            raise ValueError("Contour interval must be finite and positive")
        if not np.isfinite(max_diameter_km) or max_diameter_km <= 0:
            raise ValueError("Maximum diameter must be finite and positive")
        if (
            not isinstance(filter_passes, (int, np.integer))
            or not 0 <= filter_passes <= 20
        ):
            raise ValueError("Filter passes must be an integer from 0 to 20")
        self.contour_interval = contour_interval
        self.max_diameter_km = max_diameter_km
        self.filter_passes = filter_passes
        _validate_grid(latitude, longitude, u, v)
        _validate_sla(sla_field, latitude, longitude)

        self.latitude = latitude
        self.longitude = longitude
        self.u = u
        self.v = v
        self.sla_field = sla_field
        self.relative_vorticity = None

    def okubo_weiss_field(self):
        # Coordinate-aware central differences also handle nonuniform spacing.
        # As in the original implementation, use local Cartesian derivatives
        # and retain only the interior, where centred stencils are available.
        phi = np.deg2rad(self.latitude)
        lam = np.deg2rad(self.longitude)
        radius = 6_371_000.0
        scale_x = radius * np.cos(phi[:, None])
        dudx = (np.gradient(self.u, lam, axis=1) / scale_x)[1:-1, 1:-1]
        dvdx = (np.gradient(self.v, lam, axis=1) / scale_x)[1:-1, 1:-1]
        dudy = (np.gradient(self.u, phi, axis=0) / radius)[1:-1, 1:-1]
        dvdy = (np.gradient(self.v, phi, axis=0) / radius)[1:-1, 1:-1]

        Sn = dudx - dvdy
        Ss = dvdx + dudy
        zeta = dvdx - dudy
        # Retain the unsmoothed signed field on the interior grid for tracking.
        self.relative_vorticity = zeta

        return Sn**2 + Ss**2 - zeta**2

    @staticmethod
    def apply_hanning_filter(field):
        H = np.array([[1, 2, 1], [2, 4, 2], [1, 2, 1]], dtype=float) / 16

        valid = np.isfinite(field)
        values = np.where(valid, field, 0.0)

        numerator = convolve(values, H, mode="reflect")
        denominator = convolve(valid.astype(float), H, mode="reflect")

        filtered = np.full_like(field, np.nan, dtype=float)

        np.divide(numerator, denominator, out=filtered, where=denominator > 0)

        filtered[~valid] = np.nan

        return filtered

    @staticmethod
    def extract_rotating_regions(field):
        negative_field_mask = field < 0

        labels = np.empty(negative_field_mask.shape, dtype=np.int32)
        num_regions = label(
            negative_field_mask, structure=np.ones((3, 3), dtype=int), output=labels
        )

        return labels, num_regions

    def calculate_contour_diameter(self, contour):
        lat = np.interp(contour[:, 0], np.arange(len(self.latitude)), self.latitude)

        lon = np.interp(contour[:, 1], np.arange(len(self.longitude)), self.longitude)

        lat = np.deg2rad(lat)
        lon = np.deg2rad(lon)

        distances = haversine(
            lon1=lon[:, None], lon2=lon[None, :], lat1=lat[:, None], lat2=lat[None, :]
        )

        return float(np.max(distances))

    def extract_closed_contours(self):
        interval = self.contour_interval
        if not np.isfinite(self.sla_field).any():
            return []

        minimum = np.nanmin(self.sla_field)
        maximum = np.nanmax(self.sla_field)

        levels = np.arange(
            np.floor(minimum / interval) * interval,
            np.ceil(maximum / interval) * interval + interval / 2,
            interval,
        )

        closed_contours = []

        for level in levels:
            contours = find_contours(self.sla_field, level=level)

            for contour in contours:
                # Reject open contours
                if np.linalg.norm(contour[0] - contour[-1]) > 1e-6:
                    continue

                # Reject contours larger than 600 km
                if self.calculate_contour_diameter(contour) > self.max_diameter_km:
                    continue

                closed_contours.append((float(level), contour))

        return closed_contours

    @overload
    def combine_regions_and_contours(
        self,
        labels,
        closed_contours,
        return_diagnostics: Literal[False] = False,
        core_field=None,
    ) -> list[dict[str, Any]]: ...

    @overload
    def combine_regions_and_contours(
        self,
        labels,
        closed_contours,
        return_diagnostics: Literal[True],
        core_field=None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]: ...

    def combine_regions_and_contours(
        self, labels, closed_contours, return_diagnostics=False, core_field=None
    ):
        """Select one outermost single-core loop per connected negative-W core.

        A core representative must be enclosed, not merely grazed. Multiple enclosed
        cores and loops crossing missing height/velocity support are rejected.
        These conservative rules resolve the article's underspecified merge step.
        """
        rows, cols = np.indices(labels.shape)
        points = np.column_stack(((rows + 1).ravel(), (cols + 1).ravel()))
        full_rows, full_cols = np.indices(self.sla_field.shape)
        full_points = np.column_stack((full_rows.ravel(), full_cols.ravel()))
        support = (
            np.isfinite(self.sla_field) & np.isfinite(self.u) & np.isfinite(self.v)
        )
        representatives = {}
        for core in np.unique(labels[labels > 0]):
            locations = np.argwhere(labels == core)
            if core_field is not None:
                index = np.argmin(core_field[labels == core])
            else:
                index = np.argmin(
                    np.sum((locations - locations.mean(axis=0)) ** 2, axis=1)
                )
            representatives[int(core)] = tuple(locations[index])
        diagnostics = []
        for level, contour in closed_contours:
            polygon = Path(contour)
            inside = polygon.contains_points(points).reshape(labels.shape)
            full_inside = polygon.contains_points(full_points).reshape(
                self.sla_field.shape
            )
            region_ids = np.unique(labels[inside])
            region_ids = region_ids[region_ids > 0]
            reason = "eligible"
            if not support[full_inside].all():
                reason = "missing_data"
            elif not region_ids.size:
                reason = "no_rotating_core"
            enclosed = [
                int(core) for core in region_ids if inside[representatives[int(core)]]
            ]
            if reason == "eligible":
                if len(enclosed) > 1:
                    reason = "multiple_cores"
                elif not enclosed:
                    reason = "partial_core"
            region_ids = np.asarray(enclosed, dtype=int)
            area = (
                abs(
                    np.dot(contour[:-1, 0], contour[1:, 1])
                    - np.dot(contour[1:, 0], contour[:-1, 1])
                )
                / 2
            )
            diagnostics.append(
                {
                    "id": len(diagnostics) + 1,
                    "level": level,
                    "contour": contour,
                    "diameter_km": self.calculate_contour_diameter(contour),
                    "region_ids": region_ids.tolist(),
                    "area_cells": float(area),
                    "reason": reason,
                    "accepted": False,
                }
            )
        eligible = sorted(
            (d for d in diagnostics if d["reason"] == "eligible"),
            key=lambda d: (-d["area_cells"], d["id"]),
        )
        used = set()
        for candidate in eligible:
            core = candidate["region_ids"][0]
            if core in used:
                candidate["reason"] = "nested_duplicate"
            else:
                used.add(core)
                candidate.update(accepted=True, reason="accepted")
        results = [d for d in diagnostics if d["accepted"]]
        return (results, diagnostics) if return_diagnostics else results

    @overload
    def detect_eddies(
        self, return_diagnostics: Literal[False] = False
    ) -> list[dict[str, Any]]: ...

    @overload
    def detect_eddies(
        self, return_diagnostics: Literal[True]
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]: ...

    def detect_eddies(self, return_diagnostics=False):
        raw = self.okubo_weiss_field()
        W = raw.copy()
        for _ in range(self.filter_passes):
            W = self.apply_hanning_filter(W)
        labels, count = self.extract_rotating_regions(W)
        results, candidates = self.combine_regions_and_contours(
            labels,
            self.extract_closed_contours(),
            return_diagnostics=True,
            core_field=W,
        )
        if return_diagnostics:
            return results, {
                "raw_w": raw,
                "filtered_w": W,
                "labels": labels,
                "core_count": count,
                "candidates": candidates,
            }
        return results
