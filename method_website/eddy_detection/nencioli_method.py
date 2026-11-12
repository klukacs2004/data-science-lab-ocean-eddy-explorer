from typing import Any, Literal, overload

import numpy as np
from numpy.typing import NDArray
import pandas as pd

from skimage.measure import find_contours
from matplotlib.path import Path

from .method_utils import (
    haversine,
    _validate_grid,
    calculate_grid_spacing,
    RotationDirection,
)


class NencioliCenterDetector:
    """Nencioli et al. (2010) eddy-center detector.

    Arrays are indexed [latitude, longitude]; both coordinates must increase
    northward/eastward respectively. u is eastward, v northward velocity.
    """

    def __init__(
        self,
        latitude: NDArray[np.floating],
        longitude: NDArray[np.floating],
        u: NDArray[np.floating],
        v: NDArray[np.floating],
        a: int | None = None,
        b: int | None = None,
        a_range: range | None = None,
        b_range: range | None = None,
    ) -> None:
        _validate_grid(latitude, longitude, u, v)
        if u.ndim != 2 or v.ndim != 2:
            raise ValueError("Velocity arrays must be two-dimensional")
        if u.shape != v.shape:
            raise ValueError("Velocity arrays must have identical shapes")
        if not np.issubdtype(u.dtype, np.floating) or not np.issubdtype(
            v.dtype, np.floating
        ):
            raise ValueError("Velocity fields must contain floating-point numbers")
        if (a is None) != (b is None):
            raise ValueError("Both a and b must be provided together")
        if (a_range is None) != (b_range is None):
            raise ValueError("Both a_range and b_range must be provided together")

        single_mode = a is not None and b is not None
        sweep_mode = a_range is not None and b_range is not None
        if single_mode == sweep_mode:
            raise ValueError(
                "Choose either single detection or parameter sweep, but not both."
            )
        if single_mode:
            assert a is not None and b is not None
            if type(a) is not int or a < 2:
                raise ValueError(
                    "The neighboring parameter 'a' must be an integer >= 2"
                )
            if type(b) is not int or b < 1:
                raise ValueError(
                    "The local-minimum parameter 'b' must be a positive integer"
                )
            if min(u.shape) < 2 * max(a, b) + 1:
                raise ValueError("Grid is too small for the selected neighborhood")

        self.nlat, self.nlon = v.shape
        self.u: NDArray[np.floating] = u
        self.v: NDArray[np.floating] = v
        self.speed: NDArray[np.floating] = np.hypot(u, v)
        self.a: int | None = a
        self.b: int | None = b
        self.a_range: range | None = a_range
        self.b_range: range | None = b_range
        self.latitude: NDArray[np.floating] = latitude
        self.longitude: NDArray[np.floating] = longitude

    def check_meridional_velocity(self, i: int, j: int) -> RotationDirection:
        assert self.a is not None and self.b is not None
        # The candidate is the adjacent west/east pair (i,j), (i,j+1).
        if i < 0 or i >= self.nlat or j - self.a < 0 or j + 1 + self.a >= self.nlon:
            return RotationDirection.NONE

        west_inner = self.v[i, j]
        east_inner = self.v[i, j + 1]
        west_outer = self.v[i, j - self.a]
        east_outer = self.v[i, j + 1 + self.a]

        if not np.all(np.isfinite((west_inner, east_inner, west_outer, east_outer))):
            return RotationDirection.NONE

        clockwise = west_inner > 0 and east_inner < 0
        counterclockwise = west_inner < 0 and east_inner > 0

        west_growth = west_outer * west_inner > 0 and abs(west_outer) > abs(west_inner)
        east_growth = east_outer * east_inner > 0 and abs(east_outer) > abs(east_inner)

        if not (west_growth and east_growth):
            return RotationDirection.NONE

        if clockwise:
            return RotationDirection.CLOCKWISE
        if counterclockwise:
            return RotationDirection.COUNTERCLOCKWISE
        return RotationDirection.NONE

    def check_zonal_velocity(self, i: int, j: int) -> RotationDirection:
        assert self.a is not None and self.b is not None
        # Apply criterion 2 to ONE point selected by criterion 1.
        if j < 0 or j >= self.nlon or i - self.a < 0 or i + self.a >= self.nlat:
            return RotationDirection.NONE

        u_center = self.u[i, j]
        u_south = self.u[i - self.a, j]
        u_north = self.u[i + self.a, j]

        if not np.all(np.isfinite((u_center, u_south, u_north))):
            return RotationDirection.NONE

        clockwise = u_south < 0 and u_north > 0
        counterclockwise = u_south > 0 and u_north < 0

        south_growth = abs(u_south) > abs(u_center)
        north_growth = abs(u_north) > abs(u_center)

        if not (south_growth and north_growth):
            return RotationDirection.NONE

        if clockwise:
            return RotationDirection.CLOCKWISE
        if counterclockwise:
            return RotationDirection.COUNTERCLOCKWISE
        return RotationDirection.NONE

    def check_rotation_consistency(self, i: int, j: int) -> RotationDirection:
        """Test the WEST member of a v-sign-change pair as an individual candidate."""
        d_v = self.check_meridional_velocity(i, j)

        if d_v == RotationDirection.NONE:
            return RotationDirection.NONE

        return d_v if self.check_zonal_velocity(i, j) == d_v else RotationDirection.NONE

    def extract_perimeter_vectors(self, i: int, j: int) -> NDArray[np.floating] | None:
        assert self.a is not None and self.b is not None
        r = self.a - 1
        if not (r <= i < self.nlat - r and r <= j < self.nlon - r):
            raise ValueError("The perimeter extends outside the velocity grid")

        # CCW: south W->E, east S->N, north E->W, west N->S.
        perimeter_u = np.concatenate(
            (
                self.u[i - r, j - r : j + r],
                self.u[i - r : i + r, j + r],
                self.u[i + r, j - r + 1 : j + r + 1][::-1],
                self.u[i - r + 1 : i + r + 1, j - r][::-1],
            )
        )
        perimeter_v = np.concatenate(
            (
                self.v[i - r, j - r : j + r],
                self.v[i - r : i + r, j + r],
                self.v[i + r, j - r + 1 : j + r + 1][::-1],
                self.v[i - r + 1 : i + r + 1, j - r][::-1],
            )
        )
        perimeter = np.column_stack((perimeter_u, perimeter_v))
        return perimeter if np.all(np.isfinite(perimeter)) else None

    def extract_perimeter_angles(self, i: int, j: int) -> NDArray[np.floating] | None:
        perimeter = self.extract_perimeter_vectors(i, j)
        if perimeter is None or np.any(np.linalg.norm(perimeter, axis=1) == 0):
            return None
        return np.arctan2(perimeter[:, 1], perimeter[:, 0])

    def check_perimeter_rotation(self, i: int, j: int) -> bool:
        angles = self.extract_perimeter_angles(i, j)
        if angles is None:
            return False

        delta = np.angle(np.exp(1j * (np.roll(angles, -1) - angles)))
        negative_steps = np.count_nonzero(delta < -1e-10)

        if negative_steps > 0:
            return False

        angles_positive = np.mod(angles, 2 * np.pi)
        quadrants = np.floor(angles_positive / (np.pi / 2)).astype(int)
        next_quadrants = np.roll(quadrants, -1)
        quadrant_steps = (next_quadrants - quadrants) % 4
        if not np.all(quadrant_steps <= 1):
            return False

        # A uniform flow has zero turning and must not count as circulation.
        return bool(np.isclose(np.sum(delta), 2 * np.pi, atol=1e-5))

    def find_velocity_minimum(self, i: int, j: int) -> tuple[int, int] | None:
        assert self.a is not None and self.b is not None
        if not (self.b <= i < self.nlat - self.b and self.b <= j < self.nlon - self.b):
            return None
        window: NDArray[np.floating] = self.speed[
            i - self.b : i + self.b + 1, j - self.b : j + self.b + 1
        ]
        if not np.all(np.isfinite(window)):
            return None
        min_i, min_j = np.unravel_index(np.argmin(window), window.shape)
        return int(i - self.b + min_i), int(j - self.b + min_j)

    def check_local_velocity_minimum(self, i: int, j: int) -> tuple[int, int] | None:
        first = self.find_velocity_minimum(i, j)
        if first is None:
            return None
        second = self.find_velocity_minimum(*first)
        return first if second == first else None

    def detect_centers(self) -> list[tuple[int, int, RotationDirection]]:
        assert self.a is not None and self.b is not None

        centers: list[tuple[int, int, RotationDirection]] = []
        detected_positions: set[tuple[int, int]] = set()
        candidates = []

        stats = {
            "meridional_pass": 0,
            "zonal_pass": 0,
            "minimum_pass": 0,
            "perimeter_pass": 0,
            "boundary_pass": 0,
            "duplicate_centers": 0,
        }

        # Criterion 1: scan adjacent EW pairs. Criterion 2: each qualifying
        # pair member is an independent candidate for the minimum search.
        for i in range(self.nlat):
            for j in range(self.nlon - 1):
                d_v = self.check_meridional_velocity(i, j)
                if d_v == RotationDirection.NONE:
                    continue
                stats["meridional_pass"] += 1

                for candidate_j in (j, j + 1):
                    candidate = {
                        "id": len(candidates) + 1,
                        "i": i,
                        "j": candidate_j,
                        "pair_j": j,
                        "direction": d_v,
                        "center_i": None,
                        "center_j": None,
                        "minimum_first": None,
                        "minimum_second": None,
                        "zonal_pass": False,
                        "minimum_pass": None,
                        "perimeter_pass": None,
                        "status": "rejected",
                        "reason": "zonal_velocity",
                    }
                    candidates.append(candidate)
                    if self.check_zonal_velocity(i, candidate_j) != d_v:
                        continue
                    stats["zonal_pass"] += 1
                    candidate["zonal_pass"] = True

                    first = self.find_velocity_minimum(i, candidate_j)
                    second = (
                        self.find_velocity_minimum(*first)
                        if first is not None
                        else None
                    )
                    candidate["minimum_first"] = first
                    candidate["minimum_second"] = second
                    center = first if first is not None and second == first else None
                    candidate["minimum_pass"] = center is not None
                    if center is None:
                        candidate["reason"] = "local_minimum"
                        continue
                    stats["minimum_pass"] += 1
                    candidate["center_i"], candidate["center_j"] = center

                    if center in detected_positions:
                        stats["duplicate_centers"] += 1
                        candidate.update(status="duplicate", reason="duplicate_center")
                        continue

                    ci, cj = center
                    r = self.a - 1
                    if not (r <= ci < self.nlat - r and r <= cj < self.nlon - r):
                        candidate["reason"] = "perimeter_domain"
                        continue
                    stats["boundary_pass"] += 1
                    candidate["perimeter_pass"] = self.check_perimeter_rotation(ci, cj)
                    if not candidate["perimeter_pass"]:
                        candidate["reason"] = "perimeter_rotation"
                        continue

                    stats["perimeter_pass"] += 1

                    detected_positions.add(center)
                    centers.append((ci, cj, d_v))
                    candidate.update(status="center", reason="center_detected")
        self.diagnostics = stats
        self.candidates = candidates
        return centers

    def sweep_parameters(self) -> tuple[pd.DataFrame, pd.DataFrame]:
        assert self.a_range is not None and self.b_range is not None
        summary = []
        detections = []

        for a in self.a_range:
            for b in self.b_range:
                detector = NencioliCenterDetector(
                    latitude=self.latitude,
                    longitude=self.longitude,
                    u=self.u,
                    v=self.v,
                    a=a,
                    b=b,
                )
                centers = detector.detect_centers()

                summary.append({"a": a, "b": b, "n_eddies": len(centers)})

                for i, j, direction in centers:
                    detections.append(
                        {
                            "a": a,
                            "b": b,
                            "center_i": i,
                            "center_j": j,
                            "direction": direction.name,
                        }
                    )

        summary_df = pd.DataFrame(summary, columns=["a", "b", "n_eddies"])
        detections_df = pd.DataFrame(
            detections, columns=["a", "b", "center_i", "center_j", "direction"]
        )

        return summary_df, detections_df


class NencioliBoundaryDetector:
    def __init__(
        self,
        latitude: NDArray[np.floating],
        longitude: NDArray[np.floating],
        u: NDArray[np.floating],
        v: NDArray[np.floating],
        *,
        contour_levels=100,
    ) -> None:
        _validate_grid(latitude, longitude, u, v)
        if type(contour_levels) is not int or contour_levels < 3:
            raise ValueError("At least three contour levels are required")
        self.contour_levels = contour_levels
        if u.ndim != 2 or v.ndim != 2:
            raise ValueError("Velocity fields must be two-dimensional")
        if u.shape != v.shape:
            raise ValueError("Velocity fields must have identical shapes")
        if u.shape != (len(latitude), len(longitude)):
            raise ValueError("Velocity dimensions do not match coordinates")

        self.u = u
        self.v = v
        self.latitude = latitude
        self.longitude = longitude

    def calculate_streamfunction(self):
        dx, dy = calculate_grid_spacing(self.latitude, self.longitude)

        southward = np.concatenate(
            ([0.0], np.cumsum(-0.5 * (self.v[0, :-1] + self.v[0, 1:]) * dx[0, :]))
        )

        northward = np.vstack(
            (
                np.zeros((1, self.u.shape[1])),
                np.cumsum(0.5 * (self.u[:-1, :] + self.u[1:, :]) * dy[:, None], axis=0),
            )
        )

        westward = np.concatenate(
            ([0.0], np.cumsum(0.5 * (self.u[:-1, 0] + self.u[1:, 0]) * dy))
        )

        eastward = np.hstack(
            (
                np.zeros((self.v.shape[0], 1)),
                np.cumsum(-0.5 * (self.v[:, :-1] + self.v[:, 1:]) * dx, axis=1),
            )
        )

        psi_xy = southward[None, :] + northward
        psi_yx = westward[:, None] + eastward

        psi = 0.5 * (psi_xy + psi_yx)

        return psi

    def find_closed_contours(self, center_i, center_j):
        psi = self.calculate_streamfunction()

        levels = np.linspace(np.nanmin(psi), np.nanmax(psi), self.contour_levels)
        closed_contours = []

        for level in levels:
            contours = find_contours(psi, level)

            for contour in contours:
                if np.linalg.norm(contour[0] - contour[-1]) > 1e-6:
                    continue

                polygon = Path(contour[:, ::-1])
                if not polygon.contains_point((center_j, center_i)):
                    continue

                closed_contours.append(contour)

        return closed_contours

    def get_contour_extrema(self, contour):
        north = contour[np.argmax(contour[:, 0])]
        south = contour[np.argmin(contour[:, 0])]
        east = contour[np.argmax(contour[:, 1])]
        west = contour[np.argmin(contour[:, 1])]

        return north, south, east, west

    def interpolate_speed(self, speed, point):
        x, y = point
        nlat, nlon = speed.shape

        if not (0 <= x <= nlat - 1 and 0 <= y <= nlon - 1):
            raise ValueError("Point is outside the interpolation domain")

        i = min(int(np.floor(x)), nlat - 2)
        j = min(int(np.floor(y)), nlon - 2)

        frac_i = x - i
        frac_j = y - j

        return (
            (1 - frac_i) * (1 - frac_j) * speed[i, j]
            + frac_i * (1 - frac_j) * speed[i + 1, j]
            + frac_i * frac_j * speed[i + 1, j + 1]
            + (1 - frac_i) * frac_j * speed[i, j + 1]
        )

    def check_radial_velocity_growth(self, contour, speed, center_i, center_j):
        center = np.array([center_i, center_j], dtype=float)
        extrema = self.get_contour_extrema(contour)

        for point in extrema:
            direction = np.asarray(point, dtype=float) - center
            distance = np.linalg.norm(direction)

            if distance <= 1.0:
                return False

            direction /= distance

            # Test ACROSS the contour (section 3a), rather than only inside it.
            inner_point = point - 0.5 * direction
            outer_point = point + 0.5 * direction
            if np.any(outer_point < 0) or np.any(
                outer_point > np.array(speed.shape) - 1
            ):
                return False

            speed_inner = self.interpolate_speed(speed, inner_point)
            speed_outer = self.interpolate_speed(speed, outer_point)

            if not np.isfinite(speed_inner) or not np.isfinite(speed_outer):
                return False

            if speed_outer <= speed_inner:
                return False

        return True

    def calculate_contour_area(self, contour):
        # Fractional vertices matter when ranking small, nested contours.
        x, y = np.asarray(contour, dtype=float).T
        return 0.5 * abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))

    def circular_fallback(self, center_i: int, center_j: int, a: int):
        angle = np.linspace(0, 2 * np.pi, 101)
        r = a - 1

        circular_i = center_i + r * np.sin(angle)
        circular_j = center_j + r * np.cos(angle)

        circle_contour = np.column_stack((circular_i, circular_j))

        return circle_contour

    def CloseToBoundry(self, contour):
        nlat = len(self.latitude)
        nlon = len(self.longitude)

        min_distance = min(
            np.min(contour[:, 0]),
            np.min(nlat - 1 - contour[:, 0]),
            np.min(contour[:, 1]),
            np.min(nlon - 1 - contour[:, 1]),
        )

        return min_distance < 1.5

    def select_eddy_boundary(self, center_i: int, center_j: int, a: int):
        self.boundary_source = None
        self.growing_contours = 0
        contours = self.find_closed_contours(center_i, center_j)
        self.closed_contours = len(contours)

        if not contours:
            self.boundary_source = "circular_fallback"
            return self.circular_fallback(center_i, center_j, a)

        speed = np.hypot(self.u, self.v)

        valid_contours = []

        for contour in contours:
            if not self.check_radial_velocity_growth(
                contour, speed, center_i, center_j
            ):
                continue

            area = self.calculate_contour_area(contour)

            valid_contours.append((area, contour))

        if not valid_contours:
            return None

        self.growing_contours = len(valid_contours)
        self.boundary_source = "streamfunction"
        return max(valid_contours, key=lambda item: item[0])[1]

    def calculate_eddy_radius(self, contour, center_i, center_j):
        """Mean center-to-contour great-circle distance in kilometres (section 3a)."""
        if np.allclose(contour[0], contour[-1]):
            contour = contour[:-1]
        lat = np.interp(contour[:, 0], np.arange(len(self.latitude)), self.latitude)
        lon = np.interp(contour[:, 1], np.arange(len(self.longitude)), self.longitude)

        lat_center = np.deg2rad(self.latitude[center_i])
        lon_center = np.deg2rad(self.longitude[center_j])

        lat = np.deg2rad(lat)
        lon = np.deg2rad(lon)

        return float(np.mean(haversine(lon_center, lon, lat_center, lat)))


def extract_local_region(
    latitude: NDArray[np.floating],
    longitude: NDArray[np.floating],
    u: NDArray[np.floating],
    v: NDArray[np.floating],
    center_i: int,
    center_j: int,
    r: int,
):
    if (
        center_i - r < 0
        or center_i + r >= u.shape[0]
        or center_j - r < 0
        or center_j + r >= u.shape[1]
    ):
        raise ValueError("Local region extends outside the velocity grid")

    lat_local = latitude[center_i - r : center_i + r + 1]
    lon_local = longitude[center_j - r : center_j + r + 1]

    u_local = u[center_i - r : center_i + r + 1, center_j - r : center_j + r + 1]
    v_local = v[center_i - r : center_i + r + 1, center_j - r : center_j + r + 1]

    return lat_local, lon_local, u_local, v_local


Eddy = tuple[int, int, RotationDirection, NDArray, float, bool, bool]


@overload
def detect_eddies(
    u,
    v,
    latitude,
    longitude,
    a,
    b,
    *,
    return_diagnostics: Literal[False] = False,
    contour_levels=100,
) -> list[Eddy]: ...


@overload
def detect_eddies(
    u,
    v,
    latitude,
    longitude,
    a,
    b,
    *,
    return_diagnostics: Literal[True],
    contour_levels=100,
) -> tuple[list[Eddy], dict[str, Any]]: ...


def detect_eddies(
    u, v, latitude, longitude, a, b, *, return_diagnostics=False, contour_levels=100
):
    """Detect eddies following Nencioli et al. (2010), section 3a and appendix.

    Results are (i, j, rotation, contour, radius_km, land_limited,
    boundary_limited) tuples. Contours use fractional (row, column) indices.
    Optional diagnostics distinguish detected centers from accepted boundaries
    and the paper's estimated circular boundaries from streamfunction contours.
    contour_levels controls numerical contour sampling, which the paper does
    not prescribe; it is separate from the method's a and b parameters.
    """
    center_detector = NencioliCenterDetector(
        latitude=latitude, longitude=longitude, u=u, v=v, a=a, b=b
    )
    centers = center_detector.detect_centers()

    results = []
    boundary_diagnostics = []
    for center_i, center_j, direction in centers:
        r = 2 * a
        local_center_i = r
        local_center_j = r

        contour = None
        boundary_limited = False
        land_limited = False
        boundary_detector = None
        while True:
            if (
                center_i - r < 0
                or center_i + r >= u.shape[0]
                or center_j - r < 0
                or center_j + r >= u.shape[1]
            ):
                boundary_limited = True
                r -= 1
                if r < a:
                    break
                continue

            lat_local, lon_local, u_local, v_local = extract_local_region(
                latitude=latitude,
                longitude=longitude,
                u=u,
                v=v,
                center_i=center_i,
                center_j=center_j,
                r=r,
            )

            valid_region = np.all(np.isfinite(u_local) & np.isfinite(v_local))
            if not valid_region:
                land_limited = True
                r -= 1
                if r < a:
                    break
                continue

            boundary_detector = NencioliBoundaryDetector(
                latitude=lat_local,
                longitude=lon_local,
                u=u_local,
                v=v_local,
                contour_levels=contour_levels,
            )
            local_center_i = r
            local_center_j = r
            contour = boundary_detector.select_eddy_boundary(
                center_i=local_center_i, center_j=local_center_j, a=a
            )

            if contour is None:
                break

            if (
                not boundary_detector.CloseToBoundry(contour=contour)
                or land_limited
                or boundary_limited
            ):
                break

            r += a

        if contour is None or boundary_detector is None:
            boundary_diagnostics.append(
                {
                    "center_i": center_i,
                    "center_j": center_j,
                    "accepted": False,
                    "reason": (
                        "no_ocean_region"
                        if boundary_detector is None
                        else "no_growing_contour"
                    ),
                    "source": None,
                    "land_limited": land_limited,
                    "boundary_limited": boundary_limited,
                    "region_radius": (
                        local_center_i if boundary_detector is not None else None
                    ),
                    "closed_contours": getattr(boundary_detector, "closed_contours", 0),
                    "growing_contours": 0,
                }
            )
            continue

        contour_radius = boundary_detector.calculate_eddy_radius(
            contour=contour, center_i=local_center_i, center_j=local_center_j
        )

        contour = contour + np.array(
            [center_i - local_center_i, center_j - local_center_j]
        )
        results.append(
            (
                center_i,
                center_j,
                direction,
                contour,
                contour_radius,
                land_limited,
                boundary_limited,
            )
        )
        boundary_diagnostics.append(
            {
                "center_i": center_i,
                "center_j": center_j,
                "accepted": True,
                "reason": "accepted",
                "source": boundary_detector.boundary_source,
                "land_limited": land_limited,
                "boundary_limited": boundary_limited,
                "region_radius": local_center_i,
                "closed_contours": getattr(boundary_detector, "closed_contours", 0),
                "growing_contours": getattr(boundary_detector, "growing_contours", 0),
            }
        )

    if return_diagnostics:
        outcomes = {
            (item["center_i"], item["center_j"]): item for item in boundary_diagnostics
        }
        for candidate in center_detector.candidates:
            if candidate["status"] == "center":
                outcome = outcomes[candidate["center_i"], candidate["center_j"]]
                candidate.update(
                    {
                        k: value
                        for k, value in outcome.items()
                        if k not in ("center_i", "center_j")
                    }
                )
                candidate["status"] = "accepted" if outcome["accepted"] else "rejected"
        return results, {
            "center_counts": center_detector.diagnostics,
            "centers": centers,
            "boundaries": boundary_diagnostics,
            "candidates": center_detector.candidates,
        }
    return results
