"""Daily Halo detection and integration with the existing Halo tracker."""

from datetime import timedelta
import numpy as np
import xarray as xr

from eddy_detection.halo_method import HaloDetector
from eddy_detection.method_utils import standardize_okubo_weiss
from eddy_tracking.halo_tracking import track_halo
from eddy_tracking.halo_vorticity import representative_vorticity, velocity_vorticity
from .datasets import get_available_dates
from .methods import load_sla_day, load_velocity_field
from .tracking import summarize_tracks


def run_halo_tracking(settings, *, progress=None, daily_cache=None):
    available = get_available_dates()
    detections_by_day, missing = {}, []
    dataset_grid = None
    vorticity_by_detection, vorticity_exclusions = {}, []
    for offset in range(settings["duration_days"]):
        day = settings["day"] + timedelta(days=offset)
        detections_by_day[day] = []
        if day.isoformat() not in available:
            missing.append(day)
            continue
        try:
            cached = daily_cache.load("halo", day, settings) if daily_cache else None
            if cached is not None:
                from .comparison_cache import restore_grid

                dataset_grid = restore_grid(dataset_grid, cached["grid"])
                detections_by_day[day] = cached["detections"]
                vorticity_by_detection.update(cached["vorticity"])
                vorticity_exclusions.extend(cached["exclusions"])
            else:
                height = load_sla_day(day)
                u, v = load_velocity_field(day)
                height, u, v = xr.align(height, u, v, join="exact")
                height, u, v = (
                    field.transpose("latitude", "longitude") for field in (height, u, v)
                )
                lat, lon = height.latitude.values, height.longitude.values
                if dataset_grid is None:
                    dataset_grid = {
                        "latitude": lat.tolist(),
                        "longitude": lon.tolist(),
                        "date": day,
                        "valid_sla": (~np.isnan(height.values)).tolist(),
                    }
                elif not (
                    np.array_equal(lat, dataset_grid["latitude"])
                    and np.array_equal(lon, dataset_grid["longitude"])
                ):
                    raise ValueError(
                        "The dataset grid changes within the selected interval."
                    )
                detector = HaloDetector(
                    height.values,
                    lat,
                    lon,
                    u.values,
                    v.values,
                    contour_interval=settings["contour_interval_cm"] / 100.0,
                    max_diameter_km=settings["max_diameter_km"],
                    filter_passes=settings["filter_passes"],
                )
                results = detector.detect_eddies()
                passes = settings.get("velocity_smoothing_passes", 0)
                vorticity = (
                    velocity_vorticity(u.values, v.values, lat, lon, passes)
                    if passes
                    else detector.relative_vorticity
                )
                means, exclusions = representative_vorticity(
                    results,
                    vorticity,
                    lat,
                    lon,
                    settings.get("minimum_abs_vorticity_s", 0.0),
                )
                detections_by_day[day] = [
                    eddy
                    for eddy in standardize_okubo_weiss(results, day, lat, lon)
                    if eddy.id in means
                ]
                vorticity_by_detection.update(
                    {(day, identifier): value for identifier, value in means.items()}
                )
                vorticity_exclusions.extend(
                    {"date": day, "id": identifier, "reason": reason}
                    for identifier, reason in exclusions.items()
                )
                if daily_cache:
                    payload = {
                        "grid": {**dataset_grid, "date": day},
                        "detections": detections_by_day[day],
                    }
                    payload.update(
                        vorticity={(day, key): value for key, value in means.items()},
                        exclusions=[
                            {"date": day, "id": key, "reason": reason}
                            for key, reason in exclusions.items()
                        ],
                    )
                    daily_cache.save("halo", day, settings, payload)
            if progress:
                progress("detection", offset + 1, cached is not None)
        except (OSError, KeyError, ValueError, RuntimeError, IndexError) as exc:
            raise ValueError(f"Could not process {day.isoformat()}: {exc}") from exc
    if progress:
        progress("association", settings["duration_days"], False)
    diagnostics = {}
    tracks = track_halo(
        detections_by_day,
        vorticity_by_detection=vorticity_by_detection,
        vorticity_scale_s=settings["vorticity_scale_s"],
        max_displacement_km=settings["max_displacement_km"],
        position_scale_km=settings["position_scale_km"],
        diameter_scale_km=settings["diameter_scale_km"],
        max_generalized_distance=settings["max_generalized_distance"],
        min_lifetime_days=settings["min_lifetime_days"],
        assignment_method=settings.get("assignment_method", "global"),
        max_gap_days=settings.get("max_gap_days", 0),
        gap_max_displacement_km=settings.get("gap_max_displacement_km", 50.0),
        gap_max_generalized_distance=settings.get("gap_max_generalized_distance", 1.0),
        gap_max_diameter_ratio=settings.get("gap_max_diameter_ratio", 1.5),
        gap_max_vorticity_ratio=settings.get("gap_max_vorticity_ratio", 2.0),
        diagnostics=diagnostics,
    )
    retained = {track.id for track in tracks}
    links = [row for row in diagnostics.get("links", []) if row["track_id"] in retained]
    result = summarize_tracks(tracks, settings, missing, dataset_grid)
    margin = settings.get("max_gap_days", 0)
    for row, track in zip(result["track_rows"], tracks):
        left = (track.start_date - settings["day"]).days <= margin
        right = (result["end_day"] - track.end_date).days <= margin
        row.update(
            left_censored=left,
            right_censored=right,
            complete_within_window=not (left or right),
            median_radius_km=float(np.median([e.radius_km for e in track.detections])),
            missing_observation_days=track.lifetime_days - len(track.detections),
        )
    return {
        **result,
        "vorticity_by_detection": vorticity_by_detection,
        "vorticity_exclusions": vorticity_exclusions,
        "tracking_links": links,
        "recovered_gap_links": [row for row in links if row["recovered_gap"]],
        "tracking_diagnostics": diagnostics,
    }
