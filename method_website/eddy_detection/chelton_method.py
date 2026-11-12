import numpy as np
import numpy.typing as npt
import matplotlib.pyplot as plt
from scipy.ndimage import (
    gaussian_filter,
    label,
    binary_dilation,
    binary_erosion,
    binary_fill_holes,
)

from .method_utils import CONNECTIVITY, haversine

from typing import Any, Literal, cast, overload


def high_pass_filter(sla_day, sigma=(4.0, 4.0)):
    """Subtract a mask-normalized Gaussian background (not a unique paper kernel)."""
    if np.any(np.asarray(sigma) <= 0) or not np.all(np.isfinite(sigma)):
        raise ValueError("Gaussian scales must be finite and positive")
    sla = sla_day.values
    valid = np.isfinite(sla)
    filled = np.where(valid, sla, 0.0)

    nominator = gaussian_filter(filled, sigma=sigma, mode="constant", cval=0.0)
    denominator = gaussian_filter(
        valid.astype(float), sigma=sigma, mode="constant", cval=0.0
    )

    background = np.full(sla.shape, np.nan)
    np.divide(
        nominator, denominator, out=background, where=valid & (denominator > 1e-12)
    )

    background_day = sla_day.copy(data=background)

    filtered_day = sla_day - background_day

    return filtered_day


def paper_scale_sigma(sla_day):
    """Gaussian approximation to the paper's 20° zonal / 10° meridional cutoffs.

    Calibrate the high-pass POWER response to 1/2 at each axial wavelength.
    The paper specifies the cutoffs, not this Gaussian transfer function.
    Returned scales follow the DataArray's actual dimension order.
    """
    factor = np.sqrt(-2 * np.log(1 - 1 / np.sqrt(2))) / (2 * np.pi)
    scales = {}
    for dimension, wavelength in (("longitude", 20.0), ("latitude", 10.0)):
        differences = np.diff(sla_day[dimension].values.astype(float))
        if (
            not differences.size
            or not np.all(differences > 0)
            or not np.allclose(differences, differences[0])
        ):
            raise ValueError(
                "Paper-scale filtering requires increasing, regularly spaced coordinates"
            )
        scales[dimension] = factor * wavelength / differences[0]
    return tuple(scales[dimension] for dimension in sla_day.dims)


def gaussian_cutoff_degrees(sigma_cells, spacing_degrees):
    factor = np.sqrt(-2 * np.log(1 - 1 / np.sqrt(2))) / (2 * np.pi)
    return float(sigma_cells * spacing_degrees / factor)


def scan_thresholds(filtered_day, return_diagnostics=False):
    detected_patches = []
    scan_diagnostics = []

    scans: tuple[tuple[Polarity, range], ...] = (
        ("maximum", range(-100, 101)),
        ("minimum", range(100, -101, -1)),
    )

    for polarity, thresholds_cm in scans:
        available = np.isfinite(filtered_day.values)

        for threshold_cm in thresholds_cm:
            patches, diagnostics = detect_at_threshold(
                filtered_day,
                threshold=threshold_cm / 100.0,
                polarity=polarity,
                available=available,
                return_diagnostics=True,
            )

            for candidate in diagnostics:
                candidate["local_id"] = candidate["id"]
                candidate["scan_candidate_id"] = len(scan_diagnostics) + 1
                candidate["id"] = candidate["scan_candidate_id"]
                candidate["threshold_m"] = threshold_cm / 100.0
                candidate["polarity"] = polarity

                scan_diagnostics.append(candidate)

            for patch in patches:
                candidate = next(c for c in diagnostics if c["local_id"] == patch["id"])
                patch["id"] = candidate["id"]
                patch["candidate_id"] = candidate["id"]
                patch["detection_id"] = len(detected_patches) + 1
                patch["polarity"] = polarity
                detected_patches.append(patch)

                interior = np.asarray(
                    binary_erosion(
                        patch["region"],
                        structure=CONNECTIVITY,
                        border_value=0,
                    ),
                    dtype=bool,
                )
                available[interior] = False

    if return_diagnostics:
        return detected_patches, scan_diagnostics

    return detected_patches


def touches_edges(region):
    return (
        region[0, :].any()
        or region[-1, :].any()
        or region[:, 0].any()
        or region[:, -1].any()
    )


def has_missing_point(region, missing):
    expanded = binary_dilation(region, structure=CONNECTIVITY)
    return (expanded & missing).any()


def has_extrema(region_sla):
    for i in range(1, region_sla.shape[0] - 1):
        for j in range(1, region_sla.shape[1] - 1):
            is_maximum = (
                region_sla[i, j] > region_sla[i - 1, j]
                and region_sla[i, j] > region_sla[i + 1, j]
                and region_sla[i, j] > region_sla[i, j - 1]
                and region_sla[i, j] > region_sla[i, j + 1]
            )

            if is_maximum:
                return True

    return False


def find_extrema(field, region):
    """Find strict four-neighbour maxima inside a candidate."""
    centres = field[1:-1, 1:-1]

    maxima = (
        np.isfinite(centres)
        & binary_erosion(region, structure=CONNECTIVITY, border_value=0)[1:-1, 1:-1]
        & (centres > field[:-2, 1:-1])
        & (centres > field[2:, 1:-1])
        & (centres > field[1:-1, :-2])
        & (centres > field[1:-1, 2:])
    )

    # Restore indices relative to the complete field.
    return np.argwhere(maxima) + 1


def calc_amplitude(region, field, polarity):
    interior = np.asarray(
        binary_erosion(region, structure=CONNECTIVITY, border_value=0), dtype=bool
    )
    boundary = region & ~interior
    boundary_mean = field[boundary].mean()

    if polarity == "maximum":
        return float(field[region].max() - boundary_mean)

    if polarity == "minimum":
        return float(boundary_mean - field[region].min())

    raise ValueError("Polarity must be 'maximum' or 'minimum'.")


def calc_diameter_km(filtered_day, region):
    lon_indices, lat_indices = np.where(region)
    patch_lon = filtered_day.longitude.values[lon_indices]
    patch_lat = filtered_day.latitude.values[lat_indices]

    lon_rad = np.deg2rad(patch_lon)
    lat_rad = np.deg2rad(patch_lat)

    diameter_km = 0.0

    # All pairs, in bounded vectorized blocks; do not replace with a bounding box.
    for start in range(0, len(lon_rad), 64):
        distances = haversine(
            lon_rad[start : start + 64, None],
            lon_rad[None, :],
            lat_rad[start : start + 64, None],
            lat_rad[None, :],
        )
        diameter_km = max(diameter_km, float(np.max(distances)))

    return diameter_km


def diameter_limit_km(latitude):
    """Appendix B.2: 400 km poleward of 25°, increasing to 1200 km at 0°."""
    return float(400 + 800 * (1 - min(abs(latitude) / 25, 1)))


def pixel_areas_km2(filtered_day):
    def edges(coordinates):
        coordinates = np.asarray(coordinates, dtype=float)
        if len(coordinates) < 2 or not np.all(np.diff(coordinates) > 0):
            raise ValueError(
                "Coordinates must have at least two increasing grid centers"
            )
        return np.r_[
            coordinates[0] - (coordinates[1] - coordinates[0]) / 2,
            (coordinates[:-1] + coordinates[1:]) / 2,
            coordinates[-1] + (coordinates[-1] - coordinates[-2]) / 2,
        ]

    lon_edges = np.deg2rad(edges(filtered_day.longitude.values))
    lat_edges = np.deg2rad(np.clip(edges(filtered_day.latitude.values), -90, 90))
    return 6371.0**2 * np.diff(lon_edges)[:, None] * np.diff(np.sin(lat_edges))[None, :]


def create_default_diagnostic(
    region_id: int,
    current_patch_size: int,
    region: npt.NDArray[np.bool],
) -> dict[str, Any]:
    return {
        "id": int(region_id),
        "accepted": False,
        "reason": "",
        "size": current_patch_size,
        "amplitude_m": None,
        "diameter_km": None,
        "threshold_m": None,
        "checks": {
            key: None
            for key in (
                "domain",
                "missing",
                "size",
                "holes",
                "extrema",
                "amplitude",
                "diameter",
            )
        },
        "region": region.copy(),
    }


def create_patch(region_id, region, amplitude, diameter_km, sla, threshold):
    patch = dict(
        {
            "id": region_id,
            "size": int(region.sum()),
            "amplitude_m": float(amplitude),
            "diameter_km": float(diameter_km),
            "sla": sla,
            "region": region.copy(),
            "threshold_m": float(threshold),
        }
    )

    return patch


from typing import Any, Literal, cast, overload

Polarity = Literal["maximum", "minimum"]


@overload
def detect_at_threshold(
    filtered_day,
    threshold,
    polarity: Polarity,
    available=None,
    *,
    return_diagnostics: Literal[False] = False,
) -> list[dict[str, Any]]: ...


@overload
def detect_at_threshold(
    filtered_day,
    threshold,
    polarity: Polarity,
    available=None,
    *,
    return_diagnostics: Literal[True],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]: ...


def detect_at_threshold(
    filtered_day,
    threshold,
    polarity: Polarity,
    available=None,
    *,
    return_diagnostics: bool = False,
) -> (
    list[dict[str, Any]]
    | tuple[
        list[dict[str, Any]],
        list[dict[str, Any]],
    ]
):

    if filtered_day.dims != ("longitude", "latitude"):
        raise ValueError("Expected dimensions ('longitude', 'latitude').")

    field = filtered_day.values
    if not np.isfinite(threshold):
        raise ValueError("Threshold must be finite")
    cell_areas = pixel_areas_km2(filtered_day)
    missing = ~np.isfinite(field)

    if available is None:
        available = ~missing
    else:
        available = np.asarray(available, dtype=bool)

        if available.shape != field.shape:
            raise ValueError("Available mask must have the same shape as the field.")

        available = available & ~missing

    # Polarity determines the comparison, independently of threshold sign.
    if polarity == "maximum":
        threshold_mask = (field > threshold) & available
        extrema_field = field
    elif polarity == "minimum":
        threshold_mask = (field < threshold) & available
        extrema_field = -field
    else:
        raise ValueError("Polarity must be 'maximum' or 'minimum'.")

    labels = np.zeros(field.shape, dtype=np.int32)
    count = cast(
        int,
        label(
            threshold_mask,
            structure=CONNECTIVITY,
            output=labels,
        ),
    )

    accepted_patches: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []

    for region_id in range(1, count + 1):
        region = labels == region_id
        current_patch_size = int(region.sum())

        diagnostic = create_default_diagnostic(region_id, current_patch_size, region)
        diagnostic["polarity"] = polarity
        diagnostic["threshold_m"] = float(threshold)
        ii, jj = np.where(region)
        diagnostic["latitude"] = float(np.mean(filtered_day.latitude.values[jj]))
        diagnostic["longitude"] = float(np.mean(filtered_day.longitude.values[ii]))
        diagnostic["diameter_limit_km"] = diameter_limit_km(diagnostic["latitude"])
        diagnostic["area_km2"] = float(cell_areas[region].sum())
        diagnostic["effective_radius_km"] = float(
            np.sqrt(diagnostic["area_km2"] / np.pi)
        )
        diagnostics.append(diagnostic)

        diagnostic["checks"]["domain"] = not touches_edges(region)
        if not diagnostic["checks"]["domain"]:
            diagnostic["reason"] = "Touches the domain boundary"
            continue

        diagnostic["checks"]["missing"] = not has_missing_point(region, missing)
        if not diagnostic["checks"]["missing"]:
            diagnostic["reason"] = "Touches missing data"
            continue

        diagnostic["checks"]["size"] = 8 <= current_patch_size < 1000
        if not diagnostic["checks"]["size"]:
            diagnostic["reason"] = "Size outside [8, 1000) grid cells"
            continue

        diagnostic["checks"]["holes"] = not np.any(binary_fill_holes(region) & ~region)
        if not diagnostic["checks"]["holes"]:
            diagnostic["reason"] = "Contains holes"
            continue

        extrema = find_extrema(extrema_field, region)

        diagnostic["extrema_count"] = len(extrema)
        diagnostic["extrema_indices"] = extrema.copy()

        diagnostic["checks"]["extrema"] = len(extrema) > 0
        if not diagnostic["checks"]["extrema"]:
            diagnostic["reason"] = "No qualifying interior local extremum"
            continue

        amplitude = calc_amplitude(region, field, polarity)
        diagnostic["amplitude_m"] = float(amplitude)
        perimeter = region & np.logical_not(
            binary_erosion(region, structure=CONNECTIVITY, border_value=0)
        )
        diagnostic["boundary_mean_m"] = float(field[perimeter].mean())
        diagnostic["extremum_m"] = float(
            field[region].max() if polarity == "maximum" else field[region].min()
        )

        diagnostic["checks"]["amplitude"] = amplitude >= 0.01
        if not diagnostic["checks"]["amplitude"]:
            diagnostic["reason"] = "Amplitude below 1 cm"
            continue

        diameter_km = calc_diameter_km(filtered_day, region)
        diagnostic["diameter_km"] = float(diameter_km)

        diagnostic["checks"]["diameter"] = diameter_km < diagnostic["diameter_limit_km"]
        if not diagnostic["checks"]["diameter"]:
            diagnostic["reason"] = (
                "Maximum pair distance reaches latitude-dependent limit"
            )
            continue

        diagnostic["accepted"] = True
        diagnostic["reason"] = "All implemented criteria passed"

        patch = create_patch(
            region_id,
            region,
            amplitude,
            diameter_km,
            filtered_day.where(region),
            threshold,
        )
        patch["polarity"] = polarity
        patch["extrema_count"] = len(extrema)
        patch["extrema_indices"] = extrema.copy()
        for key in (
            "latitude",
            "longitude",
            "area_km2",
            "effective_radius_km",
            "boundary_mean_m",
            "extremum_m",
            "diameter_limit_km",
        ):
            patch[key] = diagnostic[key]

        accepted_patches.append(patch)

    if return_diagnostics:
        return accepted_patches, diagnostics

    return accepted_patches


def plot_detected_eddies_on_sla(sla_day, accepted_patches, scan=False):
    # Arrange the data as latitude × longitude for plotting
    field = sla_day.transpose("latitude", "longitude")
    lon = field.longitude.values
    lat = field.latitude.values

    # Convert SLA from metres to centimetres
    sla_cm = field * 100
    vmax = float(np.nanmax(np.abs(sla_cm.values)))

    fig, ax = plt.subplots(figsize=(8, 4), constrained_layout=True)

    sla_cm.plot.pcolormesh(
        ax=ax,
        x="longitude",
        y="latitude",
        cmap="RdBu_r",
        vmin=-vmax,
        vmax=vmax,
        cbar_kwargs={"label": "SLA [cm]"},
    )

    for patch in accepted_patches:
        # Match the region mask to the original data dimensions
        region = sla_day.copy(data=np.asarray(patch["region"], dtype=bool))
        mask = region.transpose("latitude", "longitude").values

        # Draw the detected patch boundary between inside and outside cells
        ax.contour(
            lon,
            lat,
            mask.astype(float),
            levels=[0.5],
            colors="black",
            linewidths=1.5,
            zorder=3,
        )

        # Place the patch ID and diameter near its centre
        iy, ix = np.nonzero(mask)
        if iy.size:
            ax.text(
                lon[ix].mean(),
                lat[iy].mean(),
                f'#{patch["id"]}\n{patch["diameter_km"]:.1f} km',
                ha="center",
                va="center",
                fontsize=8,
                zorder=4,
                bbox=dict(
                    facecolor="white",
                    edgecolor="none",
                    alpha=0.2,
                    boxstyle="round,pad=0.25",
                ),
            )

    # Add a legend entry for the detected boundaries
    ax.plot([], [], color="black", linewidth=1.5, label="Detected patch boundary")
    ax.legend(loc="upper right")

    if scan:
        title = (
            f"Detected patches across scanned thresholds "
            f"({len(accepted_patches)} patches)"
        )
    elif accepted_patches:
        threshold_cm = accepted_patches[0]["threshold_m"] * 100
        title = (
            f"Detected SLA patches at the {threshold_cm:g} cm threshold "
            f"({len(accepted_patches)} patches)"
        )
    else:
        title = "No SLA patches detected"

    ax.set(title=title, xlabel="Longitude [°]", ylabel="Latitude [°]")

    # Approximately correct the geographic aspect ratio
    mean_lat = float(field.latitude.mean())
    ax.set_aspect(1 / np.cos(np.deg2rad(mean_lat)))
    ax.grid(alpha=0.25)

    plt.show()
