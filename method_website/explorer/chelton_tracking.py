"""Load daily SLA, run Chelton detection, and call the existing tracker."""

from datetime import timedelta
import numpy as np

from eddy_detection.chelton_method import high_pass_filter, scan_thresholds
from eddy_detection.method_utils import standardize_chelton
from eddy_tracking.chelton_tracking import track_chelton
from .chelton_diagnostics import filtering_settings
from .datasets import get_available_dates
from .methods import load_sla_day
from .tracking import summarize_tracks


def run_chelton_tracking(settings, *, progress=None, daily_cache=None):
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
            cached = daily_cache.load("chelton", day, settings) if daily_cache else None
            if cached is not None:
                from .comparison_cache import restore_grid

                dataset_grid = restore_grid(dataset_grid, cached["grid"])
                detections_by_day[day] = cached["detections"]
            else:
                height = load_sla_day(day).transpose("longitude", "latitude")
                lat, lon = height.latitude.values, height.longitude.values
                if dataset_grid is None:
                    dataset_grid = {
                        "latitude": lat.tolist(),
                        "longitude": lon.tolist(),
                        "date": day,
                        "valid_sla": (
                            ~np.isnan(height.transpose("latitude", "longitude").values)
                        ).tolist(),
                    }
                elif not (
                    np.array_equal(lat, dataset_grid["latitude"])
                    and np.array_equal(lon, dataset_grid["longitude"])
                ):
                    raise ValueError(
                        "The dataset grid changes within the selected interval."
                    )
                filtering = filtering_settings(
                    height, settings["filter_mode"], settings.get("sigma_cells")
                )
                processed = (
                    high_pass_filter(height, filtering["sigma"])
                    if filtering["sigma"]
                    else height
                )
                detections_by_day[day] = standardize_chelton(
                    scan_thresholds(processed), day
                )
                if daily_cache:
                    payload = {
                        "grid": {**dataset_grid, "date": day},
                        "detections": detections_by_day[day],
                    }
                    daily_cache.save("chelton", day, settings, payload)
            if progress:
                progress("detection", offset + 1, cached is not None)
        except (OSError, KeyError, ValueError, RuntimeError, IndexError) as exc:
            raise ValueError(f"Could not process {day.isoformat()}: {exc}") from exc
    if progress:
        progress("association", settings["duration_days"], False)
    parameters = (
        "east_km",
        "west_km",
        "north_south_km",
        "min_amplitude_ratio",
        "max_amplitude_ratio",
        "min_area_ratio",
        "max_area_ratio",
        "min_lifetime_days",
    )
    tracks = track_chelton(
        detections_by_day, **{key: settings[key] for key in parameters}
    )
    return summarize_tracks(tracks, settings, missing, dataset_grid)
