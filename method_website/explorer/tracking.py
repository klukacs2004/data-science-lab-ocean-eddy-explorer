"""Daily loading and presentation for the Nencioli tracking explorer."""

from datetime import timedelta
import numpy as np
import xarray as xr

from eddy_detection.nencioli_method import detect_eddies
from eddy_detection.method_utils import standardize_nencioli
from eddy_tracking.nencioli_tracking import track_nencioli
from .datasets import get_available_dates
from .methods import load_sla_day, load_velocity_field


def run_tracking(settings, *, progress=None, daily_cache=None):
    available = get_available_dates()
    detections_by_day, missing = {}, []
    dataset_grid = None
    for offset in range(settings["duration_days"]):
        day = settings["day"] + timedelta(days=offset)
        detections_by_day[day] = []
        if day.isoformat() not in available:
            missing.append(day)
            continue
        try:
            cached = (
                daily_cache.load("nencioli", day, settings) if daily_cache else None
            )
            if cached is not None:
                from .comparison_cache import restore_grid

                dataset_grid = restore_grid(dataset_grid, cached["grid"])
                detections_by_day[day] = cached["detections"]
            else:
                u, v = load_velocity_field(day)
                u, v = xr.align(u, v, join="exact")
                u, v = (field.transpose("latitude", "longitude") for field in (u, v))
                lat, lon = u.latitude.values, u.longitude.values
                if dataset_grid is None:
                    sla = load_sla_day(day).transpose("latitude", "longitude")
                    xr.align(u, sla, join="exact")
                    dataset_grid = {
                        "latitude": lat.tolist(),
                        "longitude": lon.tolist(),
                        "date": day,
                        "valid_sla": (~np.isnan(sla.values)).tolist(),
                    }
                elif not (
                    np.array_equal(lat, dataset_grid["latitude"])
                    and np.array_equal(lon, dataset_grid["longitude"])
                ):
                    raise ValueError(
                        "The dataset grid changes within the selected interval."
                    )
                results, diagnostics = detect_eddies(
                    u.values,
                    v.values,
                    lat,
                    lon,
                    settings["a"],
                    settings["b"],
                    return_diagnostics=True,
                )
                detections_by_day[day] = standardize_nencioli(
                    results, day, lat, lon, diagnostics=diagnostics
                )
                if daily_cache:
                    payload = {
                        "grid": {**dataset_grid, "date": day},
                        "detections": detections_by_day[day],
                    }
                    daily_cache.save("nencioli", day, settings, payload)
            if progress:
                progress("detection", offset + 1, cached is not None)
        except (OSError, KeyError, ValueError, RuntimeError, IndexError) as exc:
            raise ValueError(f"Could not process {day.isoformat()}: {exc}") from exc
    if progress:
        progress("association", settings["duration_days"], False)
    tracks = track_nencioli(
        detections_by_day,
        daily_radius_km=settings["daily_radius_km"],
        gap_radius_km=settings["gap_radius_km"],
        min_lifetime_days=settings["min_lifetime_days"],
    )
    return summarize_tracks(tracks, settings, missing, dataset_grid)


def summarize_tracks(tracks, settings, missing, dataset_grid):
    """Shared presentation statistics for daily tracking explorers."""
    rows = [
        {
            "id": track.id,
            "polarity": track.detections[0].polarity,
            "start_date": track.start_date,
            "end_date": track.end_date,
            "lifetime_days": track.lifetime_days,
            "observations": len(track.detections),
            "mean_radius_km": float(np.mean([e.radius_km for e in track.detections])),
        }
        for track in tracks
    ]
    # Exact equality describes repeated assigned centers, not physical stationarity.
    from .plots.tracking import track_center

    center_sequences = [[track_center(e) for e in track.detections] for track in tracks]
    comparable = [centers for centers in center_sequences if len(centers) >= 2]
    adjacent_pairs = [
        (previous, current)
        for track, centers in zip(tracks, center_sequences)
        for i, (previous, current) in enumerate(zip(centers, centers[1:]), 1)
        if (track.detections[i].date - track.detections[i - 1].date).days == 1
    ]
    center_diagnostics = {
        "comparable_tracks": len(comparable),
        "single_center_tracks": sum(len(set(centers)) == 1 for centers in comparable),
        "adjacent_pairs": len(adjacent_pairs),
        "identical_adjacent_pairs": sum(a == b for a, b in adjacent_pairs),
    }
    lifetimes = [track.lifetime_days for track in tracks]
    summary = {
        "total": len(tracks),
        "cyclonic": sum(row["polarity"] == "cyclonic" for row in rows),
        "anticyclonic": sum(row["polarity"] == "anticyclonic" for row in rows),
        "unknown": sum(row["polarity"] == "unknown" for row in rows),
        "mean_lifetime": float(np.mean(lifetimes)) if lifetimes else None,
        "max_lifetime": max(lifetimes) if lifetimes else None,
        "observations": sum(len(track.detections) for track in tracks),
    }
    return {
        "dataset_grid": dataset_grid,
        "center_diagnostics": center_diagnostics,
        "tracks": tracks,
        "track_rows": rows,
        "tracking_summary": summary,
        "missing_days": missing,
        "end_day": settings["day"] + timedelta(days=settings["duration_days"] - 1),
    }
