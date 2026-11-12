# constants.py
import numpy as np
from enum import Enum
from dataclasses import dataclass
from datetime import date
from numpy.typing import NDArray

# Four-neighbour connectivity: north, south, east and west
# diagonals are excluded
CONNECTIVITY = np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]], dtype=bool)


class RotationDirection(Enum):
    CLOCKWISE = -1
    NONE = 0
    COUNTERCLOCKWISE = 1


def haversine(lon1, lon2, lat1, lat2):
    dphi = lat2 - lat1
    dlambda = lon2 - lon1

    a = np.sin(dphi / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlambda / 2) ** 2

    return 2 * 6371.0 * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def _validate_grid(latitude, longitude, u, v):
    """Validate the northward/eastward rectilinear grid assumed by the paper."""
    if u.ndim != 2 or v.ndim != 2 or u.shape != v.shape:
        raise ValueError("Velocity fields must be matching two-dimensional arrays")
    for coordinate in (latitude, longitude):
        if coordinate.ndim != 1 or coordinate.size < 2:
            raise ValueError(
                "Coordinates must be one-dimensional with at least two points"
            )
        if not np.all(np.isfinite(coordinate)) or not np.all(np.diff(coordinate) > 0):
            raise ValueError("Coordinates must be finite and strictly increasing")
    if u.shape != (len(latitude), len(longitude)):
        raise ValueError("Velocity dimensions do not match coordinates")


def _validate_sla(sla_field, latitude, longitude):
    """Validate the shape of sla_field"""
    if sla_field.shape != (len(latitude), len(longitude)):
        raise ValueError(
            f"The shape of the sla {sla_field.shape} does not match with thr grid shape ({len(latitude)}, {len(latitude)})"
        )


def calculate_grid_spacing(latitude, longitude):
    R = 6_371_000.0

    lat = np.deg2rad(latitude)
    lon = np.deg2rad(longitude)

    dy = R * np.diff(lat)
    dx = R * np.cos(lat[:, None]) * np.diff(lon)

    return dx, dy


@dataclass
class EddyDetection:
    """Common regional snapshot geometry.

    ``contour`` is a closed (N, 2) array of (latitude, longitude) in degrees;
    longitude is normalized to [-180, 180). Location is the spherical mean of
    boundary vertices, not a detector-specific dynamical center. ``area_km2``
    uses great-circle polygon edges on a 6371 km sphere, and ``radius_km`` is
    sqrt(area/pi) for every method. Polarity is cyclonic/anticyclonic/unknown.
    For Nencioli, boundary_source distinguishes streamfunction contours from
    circular_fallback geometry. A fallback radius is not a physical size;
    missing provenance stays unknown and is ineligible for radius analysis.
    Amplitude is optional: only Chelton currently supplies its native amplitude.
    IDs are local to a method and date; they are not cross-method match IDs.
    """

    id: int
    method: str
    date: date
    latitude: float
    longitude: float
    polarity: str
    radius_km: float
    contour: NDArray[np.float64]
    amplitude_cm: float | None = None
    area_km2: float | None = None
    native_center_latitude: float | None = None
    native_center_longitude: float | None = None
    boundary_source: str | None = None

    @property
    def has_reliable_radius(self) -> bool:
        """Fallback/unknown Nencioli geometry is not a physical size estimate."""
        return self.method != "nencioli" or self.boundary_source == "streamfunction"


def _standard_grid(latitude, longitude):
    if latitude is None or longitude is None:
        raise ValueError("latitude and longitude are required for grid-index contours")
    lat, lon = (np.asarray(c, dtype=float) for c in (latitude, longitude))
    for c in (lat, lon):
        if (
            c.ndim != 1
            or c.size < 2
            or not np.isfinite(c).all()
            or not (np.diff(c) > 0).all()
        ):
            raise ValueError(
                "Coordinates must be finite, one-dimensional and increasing"
            )
    if (np.abs(lat) > 90).any():
        raise ValueError("Latitude must be between -90 and 90 degrees")
    return lat, lon


def _geographic_contour(contour, latitude, longitude):
    """Convert fractional (row, column) indices to closed (latitude, longitude)."""
    lat, lon = _standard_grid(latitude, longitude)
    c = np.asarray(contour, dtype=float)
    if c.ndim != 2 or c.shape[1] != 2 or len(c) < 4 or not np.isfinite(c).all():
        raise ValueError(
            "A contour must be a finite (N, 2) array with at least four vertices"
        )
    if not np.allclose(c[0], c[-1], rtol=0, atol=1e-6):
        raise ValueError("Only closed contours can be standardized")
    if (
        (c < 0).any()
        or (c[:, 0] > len(lat) - 1).any()
        or (c[:, 1] > len(lon) - 1).any()
    ):
        raise ValueError("Contour indices fall outside the coordinate grid")
    coordinates = np.column_stack(
        (
            np.interp(c[:, 0], np.arange(len(lat)), lat),
            (np.interp(c[:, 1], np.arange(len(lon)), lon) + 180) % 360 - 180,
        )
    )
    coordinates[-1] = coordinates[0]
    return coordinates


def _contour_geometry(contour):
    """Spherical vertex-mean location and great-circle polygon area in km².

    Signed spherical triangles allow concave regional polygons. All adapters
    use the same area definition, independent of their native radius estimates.
    """
    lat, lon = np.deg2rad(contour[:-1]).T
    vertices = np.column_stack(
        (np.cos(lat) * np.cos(lon), np.cos(lat) * np.sin(lon), np.sin(lat))
    )
    mean = vertices.mean(axis=0)
    if np.linalg.norm(mean) < 1e-12:
        raise ValueError("Contour has no well-defined regional mean location")
    latitude = float(np.rad2deg(np.arctan2(mean[2], np.hypot(mean[0], mean[1]))))
    longitude = float((np.rad2deg(np.arctan2(mean[1], mean[0])) + 180) % 360 - 180)
    anchor, b, c = vertices[0], vertices[1:-1], vertices[2:]
    numerator = np.einsum("j,ij->i", anchor, np.cross(b, c))
    denominator = 1 + b @ anchor + np.einsum("ij,ij->i", b, c) + c @ anchor
    area = float(abs(np.sum(2 * np.arctan2(numerator, denominator))) * 6371.0**2)
    if not np.isfinite(area) or area <= 0:
        raise ValueError("Contour must enclose a positive finite area")
    return latitude, longitude, area


def _standard_detection(
    identifier,
    method,
    day,
    contour,
    polarity,
    amplitude_cm=None,
    native_center_latitude=None,
    native_center_longitude=None,
    boundary_source=None,
):
    from datetime import datetime

    if isinstance(day, datetime):
        day = day.date()
    elif isinstance(day, str):
        day = date.fromisoformat(day)
    if not isinstance(day, date):
        raise ValueError("date must be a date, datetime, or ISO date string")
    latitude, longitude, area = _contour_geometry(contour)
    return EddyDetection(
        id=int(identifier),
        method=method,
        date=day,
        latitude=latitude,
        longitude=longitude,
        polarity=polarity,
        radius_km=float(np.sqrt(area / np.pi)),
        contour=contour,
        amplitude_cm=amplitude_cm,
        area_km2=area,
        native_center_latitude=native_center_latitude,
        native_center_longitude=native_center_longitude,
        boundary_source=boundary_source,
    )


def standardize_chelton(results, date) -> list[EddyDetection]:
    """Adapt accepted Chelton patches to the common contour-based schema.

    Coordinates and mask dimension order come from each patch's ``sla`` DataArray.
    IDs are preserved. Native amplitude is converted from metres to centimetres;
    native pixel area/radius are replaced by the shared spherical polygon metric.
    Pass the results list, not the (results, diagnostics) return pair.
    """
    from skimage.measure import find_contours

    standardized = []
    for index, patch in enumerate(results, 1):
        if not patch.get("accepted", True):
            continue
        field = patch["sla"]
        mask = np.asarray(patch["region"], dtype=bool)
        if mask.shape != field.shape:
            raise ValueError("Chelton region and SLA shapes must match")
        mask = field.copy(data=mask).transpose("latitude", "longitude").values
        contours = find_contours(mask.astype(float), 0.5)
        if len(contours) != 1:
            raise ValueError("An accepted Chelton patch must have one closed perimeter")
        contour = _geographic_contour(
            contours[0], field.latitude.values, field.longitude.values
        )
        polarity = {"maximum": "anticyclonic", "minimum": "cyclonic"}.get(
            patch["polarity"]
        )
        if polarity is None:
            raise ValueError("Chelton polarity must be maximum or minimum")
        amplitude = patch.get("amplitude_m")
        standardized.append(
            _standard_detection(
                patch.get("id", index),
                "chelton",
                date,
                contour,
                polarity,
                None if amplitude is None else float(amplitude) * 100.0,
            )
        )
    return standardized


def standardize_nencioli(
    results, date, latitude=None, longitude=None, *, diagnostics=None
) -> list[EddyDetection]:
    """Adapt accepted Nencioli tuples to the common schema.

    The standardized location is calculated from the boundary vertices,
    while the original velocity-based center is preserved separately.
    The native radius is replaced by the area-equivalent geometric radius.
    Pass detector diagnostics to retain boundary provenance. Missing provenance
    stays unknown; circular fallback geometry has no physical size interpretation.
    """
    sources = {}
    if diagnostics is not None:
        sources = {
            (row["center_i"], row["center_j"]): row["source"]
            for row in diagnostics["boundaries"]
            if row["accepted"]
        }
    standardized = []
    for index, result in enumerate(results, 1):
        i, j, direction, indices, *_ = result
        lat, lon = _standard_grid(latitude, longitude)
        if (
            not isinstance(i, (int, np.integer))
            or not isinstance(j, (int, np.integer))
            or not (0 <= i < len(lat) and 0 <= j < len(lon))
        ):
            raise ValueError("Nencioli center indices must be integers within the grid")
        if not isinstance(direction, RotationDirection):
            raise ValueError("Nencioli direction must be a RotationDirection")
        contour = _geographic_contour(indices, lat, lon)
        polarity = "unknown"
        if lat[i] != 0 and direction != RotationDirection.NONE:
            polarity = "cyclonic" if direction.value * lat[i] > 0 else "anticyclonic"
        standardized.append(
            _standard_detection(
                index,
                "nencioli",
                date,
                contour,
                polarity,
                native_center_latitude=float(lat[i]),
                native_center_longitude=float((lon[j] + 180) % 360 - 180),
                boundary_source=sources.get((i, j)),
            )
        )
    return standardized


def standardize_okubo_weiss(
    results, date, latitude=None, longitude=None, *, vorticity_by_id=None
) -> list[EddyDetection]:
    """Adapt accepted Halo/Okubo–Weiss dictionaries using the full height grid.

    This repository's OW-based detector is HaloDetector. Its contours are
    fractional height-grid indices, not indices of the smaller interior W grid.
    Diameter/2 is not used as a radius, and ``area_cells`` is not treated as km².
    W has no rotation sign. Optional native-ID signed contour-mean vorticities
    classify rotation relative to the hemisphere. Missing/nonfinite/zero means
    and contours touching or crossing the equator retain unknown polarity.
    No SSH amplitude is inferred from a contour level. Rejected rows are excluded.
    """
    standardized = []
    for index, candidate in enumerate(results, 1):
        if not candidate.get("accepted", True):
            continue
        contour = _geographic_contour(candidate["contour"], latitude, longitude)
        identifier = candidate.get("id", index)
        polarity = "unknown"
        mean = vorticity_by_id.get(identifier) if vorticity_by_id is not None else None
        single_hemisphere = np.all(contour[:, 0] > 0) or np.all(contour[:, 0] < 0)
        if mean is not None and np.isfinite(mean) and mean != 0 and single_hemisphere:
            polarity = "cyclonic" if mean * contour[0, 0] > 0 else "anticyclonic"
        standardized.append(
            _standard_detection(
                identifier,
                "okubo_weiss",
                date,
                contour,
                polarity,
            )
        )
    return standardized
