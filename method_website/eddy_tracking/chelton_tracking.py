from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from math import cos, radians, isfinite

from eddy_detection.method_utils import EddyDetection, haversine

from .nencioli_tracking import EddyTrack


def _distance_km(first: EddyDetection, second: EddyDetection) -> float:
    """
    Compute the great-circle distance between two eddy detections in kilometers.
    """
    return float(
        haversine(
            radians(first.longitude),
            radians(second.longitude),
            radians(first.latitude),
            radians(second.latitude),
        )
    )


def _ratio_in_range(
    first: float | None, second: float | None, minimum: float, maximum: float
) -> bool:
    """Return False for missing or non-positive measurements."""
    if first is None or second is None or first <= 0 or second <= 0:
        return False
    return minimum <= second / first <= maximum


def _inside_search_ellipse(
    first: EddyDetection,
    second: EddyDetection,
    east_km: float,
    west_km: float,
    north_south_km: float,
) -> bool:
    """Local east/north offsets, with an asymmetric west/east elliptical gate."""
    delta_lon = (second.longitude - first.longitude + 180.0) % 360.0 - 180.0
    mean_lat = (first.latitude + second.latitude) / 2.0
    dx = 6371.0 * cos(radians(mean_lat)) * radians(delta_lon)
    dy = 6371.0 * radians(second.latitude - first.latitude)
    horizontal_limit = east_km if dx >= 0 else west_km
    return (dx / horizontal_limit) ** 2 + (dy / north_south_km) ** 2 <= 1.0


def track_chelton(
    detections_by_day: Mapping[date, Sequence[EddyDetection]],
    *,
    east_km: float = 30.0,
    west_km: float = 50.0,
    north_south_km: float = 30.0,
    min_amplitude_ratio: float = 0.25,
    max_amplitude_ratio: float = 2.5,
    min_area_ratio: float = 0.25,
    max_area_ratio: float = 2.5,
    min_lifetime_days: int = 28,
) -> list[EddyTrack]:
    """Link same-polarity Chelton eddies on adjacent days.

    Matching requirements:
      * same polarity;
      * center inside the configured east/west-asymmetric ellipse;
      * positive, available amplitudes and areas, with ratios in the specified
        intervals relative to the track's last observation;
      * one-to-one assignment, nearest eligible pair first.

    No missing-day recovery is performed. Unmatched detections start new tracks.
    Track IDs are new sequential IDs, independent of daily detection IDs.
    Calendar-day lifetime includes both the start and end date.

    Defaults are an experimental DAILY OSU adaptation: 30 km east/north/south,
    50 km west, with a 28-day inclusive calendar-span retention filter. These
    daily distances are not published Chelton parameters. No latitude-dependent
    Rossby-speed limit, missing-day recovery, or trajectory smoothing is applied.
    Candidates are globally sorted by distance; ties use track ID then today's
    input detection index. Each track/detection is assigned at most once per day.
    """
    if any(
        not isfinite(value) or value <= 0
        for value in (east_km, west_km, north_south_km)
    ):
        raise ValueError("All search distances must be positive")
    if not (0 < min_amplitude_ratio <= max_amplitude_ratio):
        raise ValueError("Invalid amplitude ratio interval")
    if not (0 < min_area_ratio <= max_area_ratio):
        raise ValueError("Invalid area ratio interval")
    if min_lifetime_days < 1:
        raise ValueError("Minimum lifetime must be at least one day")
    if not detections_by_day:
        return []

    for day, detections in detections_by_day.items():
        for eddy in detections:
            if eddy.date != day:
                raise ValueError("Detection date does not match dictionary key")
            if eddy.method != "chelton":
                raise ValueError("Chelton tracker accepts only Chelton detections")

    tracks: list[EddyTrack] = []
    active: list[EddyTrack] = []
    next_id = 1
    day = min(detections_by_day)
    last_day = max(detections_by_day)

    while day <= last_day:
        detections = list(detections_by_day.get(day, ()))
        candidates: list[tuple[float, int, int]] = []

        for track in active:
            last = track.detections[-1]
            if (day - last.date).days != 1:
                continue
            for index, eddy in enumerate(detections):
                if eddy.polarity != last.polarity:
                    continue
                if not _inside_search_ellipse(
                    last, eddy, east_km, west_km, north_south_km
                ):
                    continue
                if not _ratio_in_range(
                    last.amplitude_cm,
                    eddy.amplitude_cm,
                    min_amplitude_ratio,
                    max_amplitude_ratio,
                ):
                    continue
                if not _ratio_in_range(
                    last.area_km2, eddy.area_km2, min_area_ratio, max_area_ratio
                ):
                    continue
                candidates.append((_distance_km(last, eddy), track.id, index))

        candidates.sort()
        assigned_tracks: set[int] = set()
        assigned_detections: set[int] = set()
        active_by_id = {track.id: track for track in active}
        for _, track_id, index in candidates:
            if track_id in assigned_tracks or index in assigned_detections:
                continue
            active_by_id[track_id].detections.append(detections[index])
            assigned_tracks.add(track_id)
            assigned_detections.add(index)

        # No look-ahead: only tracks observed today can match tomorrow.
        active = [track for track in active if track.id in assigned_tracks]

        for index, eddy in enumerate(detections):
            if index not in assigned_detections:
                track = EddyTrack(id=next_id, detections=[eddy])
                tracks.append(track)
                active.append(track)
                next_id += 1

        day += timedelta(days=1)

    return [track for track in tracks if track.lifetime_days >= min_lifetime_days]
