"""Representative signed vorticity sampled inside native Halo contours."""

import numpy as np
from matplotlib.path import Path


def representative_vorticity(
    results, vorticity, latitude, longitude, minimum_abs_vorticity_s=0.0
):
    """Return native-ID means and exclusions using interior grid-center samples.

    Native contours use full-grid (row, column) indices. The derivative field
    omits the outer row/column, so its sample indices start at (1, 1).
    Means use approximate spherical cell-area weights cos(lat) dlat dlon.
    Empty, incomplete, or zero-mean samples are excluded rather than filled.
    """
    if not np.isfinite(minimum_abs_vorticity_s) or minimum_abs_vorticity_s < 0:
        raise ValueError("Vorticity quality floor must be nonnegative and finite")
    if not results:
        return {}, {}
    lat, lon = np.asarray(latitude, dtype=float), np.asarray(longitude, dtype=float)
    zeta = np.asarray(vorticity, dtype=float)
    if zeta.shape != (len(lat) - 2, len(lon) - 2):
        raise ValueError("Relative-vorticity field must use the interior velocity grid")
    rows, cols = np.indices(zeta.shape)
    points = np.column_stack(((rows + 1).ravel(), (cols + 1).ravel()))
    weights = (np.cos(np.deg2rad(lat[1:-1])) * np.gradient(np.deg2rad(lat))[1:-1])[
        :, None
    ] * np.gradient(np.deg2rad(lon))[None, 1:-1]
    means, exclusions = {}, {}
    for index, candidate in enumerate(results, 1):
        if not candidate.get("accepted", True):
            continue
        identifier = candidate.get("id", index)
        polygon = Path(np.asarray(candidate["contour"]))
        # Exclude boundary samples consistently for either vertex orientation.
        inside = (
            polygon.contains_points(points, radius=1e-9)
            & polygon.contains_points(points, radius=-1e-9)
        ).reshape(zeta.shape)
        if not inside.any():
            exclusions[identifier] = "No interior vorticity samples"
        elif not np.isfinite(zeta[inside]).all():
            exclusions[identifier] = "Missing vorticity within contour"
        else:
            mean = float(np.average(zeta[inside], weights=weights[inside]))
            if not np.isfinite(mean) or mean == 0:
                exclusions[identifier] = "Nonfinite or zero mean vorticity"
            elif abs(mean) <= minimum_abs_vorticity_s:
                exclusions[identifier] = "Weak mean vorticity"
            else:
                means[identifier] = mean
    return means, exclusions


def velocity_vorticity(u, v, latitude, longitude, smoothing_passes=0):
    """Interior local-Cartesian curl, optionally smoothing velocities first.

    Uses the detector's NaN-preserving Hanning kernel, not a smoothing of curl
    or W. Detector contours are unaffected. This is a separate sensitivity.
    """
    from eddy_detection.halo_method import HaloDetector
    from eddy_detection.method_utils import _validate_grid

    if type(smoothing_passes) is not int or not 0 <= smoothing_passes <= 20:
        raise ValueError("Velocity smoothing passes must be an integer from 0 to 20")
    lat, lon = np.asarray(latitude, dtype=float), np.asarray(longitude, dtype=float)
    u, v = np.asarray(u, dtype=float), np.asarray(v, dtype=float)
    _validate_grid(lat, lon, u, v)
    if min(len(lat), len(lon)) < 3:
        raise ValueError("At least three grid points per axis are required")
    for _ in range(smoothing_passes):
        u, v = HaloDetector.apply_hanning_filter(u), HaloDetector.apply_hanning_filter(
            v
        )
    dvdx = np.gradient(v, np.deg2rad(lon), axis=1) / (
        6371000.0 * np.cos(np.deg2rad(lat))[:, None]
    )
    dudy = np.gradient(u, np.deg2rad(lat), axis=0) / 6371000.0
    return (dvdx - dudy)[1:-1, 1:-1]
