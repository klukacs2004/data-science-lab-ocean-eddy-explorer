"""Run each detector once on a common aligned daily grid and compare geometry."""

from collections import Counter
from itertools import combinations

from shapely.geometry import Polygon
import numpy as np
import xarray as xr

from eddy_detection.chelton_method import high_pass_filter, scan_thresholds
from eddy_detection.nencioli_method import detect_eddies
from eddy_detection.halo_method import HaloDetector
from eddy_detection.method_utils import (
    standardize_chelton,
    standardize_nencioli,
    standardize_okubo_weiss,
)
from eddy_tracking.halo_vorticity import representative_vorticity
from .chelton_diagnostics import filtering_settings

METHODS = (
    ("chelton", "Chelton", "#176443"),
    ("nencioli", "Nencioli", "#7652ad"),
    ("okubo_weiss", "Halo / Okubo–Weiss", "#c26a13"),
)


def summarize(detections):
    rows = []
    for key, label, color in METHODS:
        selected = [e for e in detections if e.method == key]
        radii = [e.radius_km for e in selected]
        counts = Counter(e.polarity for e in selected)
        rows.append(
            {
                "key": key,
                "label": label,
                "color": color,
                "count": len(selected),
                "cyclonic": counts["cyclonic"],
                "anticyclonic": counts["anticyclonic"],
                "unknown": counts["unknown"],
                "mean_radius_km": float(np.mean(radii)) if radii else None,
                "median_radius_km": float(np.median(radii)) if radii else None,
                "min_radius_km": float(min(radii)) if radii else None,
                "max_radius_km": float(max(radii)) if radii else None,
                "mean_area_km2": (
                    float(np.mean([e.area_km2 for e in selected])) if selected else None
                ),
            }
        )
    return rows


def pair_metrics(detections):
    """Cross-method candidates using spherical centers and regional contour overlap.

    Gnomonic projection maps great-circle edges to straight segments. Intersection
    vertices are mapped back to the sphere for areas consistent with adapters.
    Invalid contours have unavailable IoU, never an invented zero overlap.
    """
    from eddy_detection.method_utils import _contour_geometry

    labels = {key: label for key, label, _ in METHODS}

    def vectors(contour):
        lat, lon = np.deg2rad(contour).T
        return np.column_stack(
            (np.cos(lat) * np.cos(lon), np.cos(lat) * np.sin(lon), np.sin(lat))
        )

    rows = []
    for a, b in combinations(detections, 2):
        if a.method == b.method:
            continue
        centers = vectors(
            np.array([[a.latitude, a.longitude], [b.latitude, b.longitude]])
        )
        distance = float(
            6371
            * np.arctan2(np.linalg.norm(np.cross(*centers)), centers[0] @ centers[1])
        )
        iou = None
        axis = centers.sum(axis=0)
        norm = np.linalg.norm(axis)
        if norm > 1e-12:
            axis /= norm
            east = np.cross([0.0, 0.0, 1.0], axis)
            if np.linalg.norm(east) < 1e-12:
                east = np.cross([1.0, 0.0, 0.0], axis)
            east /= np.linalg.norm(east)
            north = np.cross(axis, east)

            def project(contour):
                v = vectors(contour)
                denominator = v @ axis
                if np.any(denominator <= 1e-10):
                    return None
                polygon = Polygon(
                    np.column_stack((v @ east / denominator, v @ north / denominator))
                )
                return polygon if polygon.is_valid and polygon.area > 0 else None

            def area(geometry):
                if geometry.is_empty or geometry.geom_type in (
                    "Point",
                    "LineString",
                    "MultiPoint",
                    "MultiLineString",
                ):
                    return 0.0
                if geometry.geom_type != "Polygon":
                    return sum(area(part) for part in geometry.geoms)

                def ring_area(ring):
                    xy = np.asarray(ring.coords)
                    v = axis + xy[:, :1] * east + xy[:, 1:] * north
                    contour = np.rad2deg(
                        np.column_stack(
                            (
                                np.arctan2(v[:, 2], np.hypot(v[:, 0], v[:, 1])),
                                np.arctan2(v[:, 1], v[:, 0]),
                            )
                        )
                    )
                    return _contour_geometry(contour)[2]

                return ring_area(geometry.exterior) - sum(
                    ring_area(ring) for ring in geometry.interiors
                )

            pa, pb = project(a.contour), project(b.contour)
            if pa is not None and pb is not None:
                intersection = area(pa.intersection(pb))
                union = area(pa) + area(pb) - intersection
                if union > 0:
                    iou = float(np.clip(intersection / union, 0.0, 1.0))
        rows.append(
            {
                "method_a": a.method,
                "label_a": labels[a.method],
                "id_a": a.id,
                "method_b": b.method,
                "label_b": labels[b.method],
                "id_b": b.id,
                "center_distance_km": distance,
                "iou": iou,
                "polarity_a": a.polarity,
                "polarity_b": b.polarity,
                "polarity_check": (
                    "unresolved"
                    if "unknown" in (a.polarity, b.polarity)
                    else "agrees" if a.polarity == b.polarity else "opposite"
                ),
            }
        )
    return sorted(rows, key=lambda row: (-(row["iou"] or 0), row["center_distance_km"]))


def run_comparison(height, u, v, day, settings):
    """Use one source day; only Chelton may apply optional height preprocessing."""
    height, u, v = xr.align(height, u, v, join="exact")
    height = height.transpose("longitude", "latitude")
    u, v = (f.transpose("latitude", "longitude") for f in (u, v))
    lat, lon = height.latitude.values, height.longitude.values
    halo = HaloDetector(
        height.transpose("latitude", "longitude").values,
        lat,
        lon,
        u.values,
        v.values,
        contour_interval=settings["contour_interval_cm"] / 100.0,
        max_diameter_km=settings["max_diameter_km"],
        filter_passes=settings["filter_passes"],
    )
    filtering = filtering_settings(
        height, settings["filter_mode"], settings.get("sigma_cells")
    )
    processed = (
        high_pass_filter(height, filtering["sigma"]) if filtering["sigma"] else height
    )
    chelton = scan_thresholds(processed)
    nencioli, nencioli_diagnostics = detect_eddies(
        u.values,
        v.values,
        lat,
        lon,
        settings["a"],
        settings["b"],
        return_diagnostics=True,
    )
    ow = halo.detect_eddies()
    halo_vorticity, halo_polarity_exclusions = representative_vorticity(
        ow,
        halo.relative_vorticity,
        lat,
        lon,
    )
    detections = (
        standardize_chelton(chelton, day)
        + standardize_nencioli(
            nencioli, day, lat, lon, diagnostics=nencioli_diagnostics
        )
        + standardize_okubo_weiss(ow, day, lat, lon, vorticity_by_id=halo_vorticity)
    )
    labels = {key: label for key, label, _ in METHODS}
    polarity_sources = {
        "chelton": "SLA maximum/minimum",
        "nencioli": "Velocity rotation",
        "okubo_weiss": "Signed contour-mean vorticity",
    }

    def polarity_source(eddy):
        if eddy.polarity != "unknown":
            return polarity_sources[eddy.method]
        reason = (
            halo_polarity_exclusions.get(
                eddy.id, "Contour touches or crosses the equator"
            )
            if eddy.method == "okubo_weiss"
            else "Rotation or hemisphere unresolved"
        )
        return f"Unresolved: {reason}"

    export = [
        {
            "method": e.method,
            "method_label": labels[e.method],
            "id": e.id,
            "date": e.date.isoformat(),
            "latitude": e.latitude,
            "longitude": e.longitude,
            "polarity": e.polarity,
            "radius_km": e.radius_km,
            "area_km2": e.area_km2,
            "polarity_source": polarity_source(e),
            "mean_relative_vorticity_s": (
                halo_vorticity.get(e.id) if e.method == "okubo_weiss" else None
            ),
            "boundary_source": e.boundary_source,
            "has_reliable_radius": e.has_reliable_radius,
            "amplitude_cm": e.amplitude_cm,
            "native_center_latitude": e.native_center_latitude,
            "native_center_longitude": e.native_center_longitude,
        }
        for e in detections
    ]
    return {
        "detections": detections,
        "summary": summarize(detections),
        "detection_rows": export,
        "filtering": filtering,
        "match_rows": pair_metrics(detections),
    }
