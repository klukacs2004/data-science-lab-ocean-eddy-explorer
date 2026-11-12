from dataclasses import dataclass, field
from datetime import date, timedelta
from math import sqrt, sin, cos, asin, radians
from typing import Mapping

from eddy_detection.method_utils import (
    EddyDetection,
    standardize_nencioli,
)


@dataclass
class EddyTrack:
    """
    A class representing a single ocean eddy observed over multiple days.
    """

    id: int
    detections: list[EddyDetection] = field(default_factory=list)

    @property
    def start_date(self) -> date:
        return self.detections[0].date

    @property
    def end_date(self) -> date:
        return self.detections[-1].date

    @property
    def lifetime_days(self) -> int:
        return (self.end_date - self.start_date).days + 1


def _center(eddy: EddyDetection) -> tuple[float, float]:
    """
    Prefer the original velocity-based center over contour centroid.
    """
    lat = eddy.native_center_latitude
    lon = eddy.native_center_longitude
    if lat is None or lon is None:
        return eddy.latitude, eddy.longitude
    return lat, lon


def _distance_km(first: EddyDetection, second: EddyDetection) -> float:
    lat1, lon1 = _center(first)
    lat2, lon2 = _center(second)
    phi1, phi2 = radians(lat1), radians(lat2)
    dphi = phi2 - phi1
    dlambda = radians((lon2 - lon1 + 180) % 360 - 180)
    a = sin(dphi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(dlambda / 2) ** 2
    return 2 * 6371.0 * asin(sqrt(min(1.0, max(0.0, a))))


def _global_matches(candidates, detection_count):
    """Maximize gated match count, then minimize summed center displacement."""
    import numpy as np
    from scipy.optimize import linear_sum_assignment

    if not candidates:
        return []
    identifiers = sorted({track_id for _, track_id, _ in candidates})
    rows_by_id = {identifier: row for row, identifier in enumerate(identifiers)}
    scale = max(1.0, max(distance for distance, _, _ in candidates))
    unmatched = min(len(identifiers), detection_count) + 1.0
    costs = np.full((len(identifiers), detection_count + len(identifiers)), np.inf)
    costs[:, detection_count:] = unmatched
    distances = {}
    for distance, identifier, index in candidates:
        costs[rows_by_id[identifier], index] = distance / scale
        distances[identifier, index] = distance
    rows, columns = linear_sum_assignment(costs)
    return [
        (distances[identifiers[row], int(column)], identifiers[row], int(column))
        for row, column in zip(rows, columns)
        if column < detection_count
    ]


def track_nencioli(
    detections_by_day: Mapping[date, list[EddyDetection]],
    daily_radius_km: float = 30.0,
    gap_radius_km: float = 45.0,
    min_lifetime_days: int = 4,
    *,
    max_gap_days: int = 1,
    assignment_method: str = "greedy",
) -> list[EddyTrack]:
    """
    Link Nencioli detections across consecutive calendar days.

    At day t+1, match nearest same-polarity center within daily_radius_km.
    By default, if absent, try once at t+2 within gap_radius_km.
    Set max_gap_days=0 to disable recovery during association, rather than
    splitting already-linked tracks afterwards.
    Greedy assignment is the historical default. Global assignment maximizes
    gated one-to-one matches, then minimizes total displacement within each day.
    Both methods match next-day observations before attempting gap recovery.
    Each detection can belong to only one track. Unmatched detections start
    new tracks. Return only tracks spanning at least min_lifetime_days.

    Distances and greedy conflict resolution are practical adaptations,
    not an exact reproduction of the paper's grid-window implementation.
    """

    if assignment_method not in ("greedy", "global"):
        raise ValueError("assignment_method must be greedy or global")
    if type(max_gap_days) is not int or max_gap_days not in (0, 1):
        raise ValueError("max_gap_days must be 0 or 1")
    if daily_radius_km <= 0 or gap_radius_km <= 0:
        raise ValueError("Search radii must be positive")
    if min_lifetime_days < 1:
        raise ValueError("Minimum lifetime must be at least one day")
    if not detections_by_day:
        return []

    for day, eddies in detections_by_day.items():
        for eddy in eddies:
            if eddy.date != day:
                raise ValueError("Detection date does not match dictionary key")
            if eddy.method != "nencioli":
                raise ValueError("Nencioli tracker accepts only Nencioli detections")

    tracks: list[EddyTrack] = []
    active: list[EddyTrack] = []
    next_id = 1

    # Iterate through all calendar days, including missing/empty days.
    first_day = min(detections_by_day)
    last_day = max(detections_by_day)
    day = first_day
    while day <= last_day:
        # Get today's detections
        detections = list(detections_by_day.get(day, ()))
        assigned_detections: set[int] = set()
        assigned_tracks: set[int] = set()

        # Find possible matches
        search_steps = (
            ((1, daily_radius_km), (2, gap_radius_km))
            if max_gap_days
            else ((1, daily_radius_km),)
        )
        for elapsed, radius in search_steps:
            candidates: list[tuple[float, int, int]] = []
            for track in active:
                if track.id in assigned_tracks:
                    continue
                last = track.detections[-1]
                if (day - last.date).days != elapsed:
                    continue
                for index, eddy in enumerate(detections):
                    if index in assigned_detections:
                        continue
                    if eddy.polarity != last.polarity:
                        continue
                    distance = _distance_km(last, eddy)
                    if distance <= radius:
                        candidates.append((distance, track.id, index))

            # Select the best matches
            candidates = (
                _global_matches(candidates, len(detections))
                if assignment_method == "global"
                else sorted(candidates)
            )
            active_by_id = {track.id: track for track in active}
            for _, track_id, index in candidates:
                if track_id in assigned_tracks or index in assigned_detections:
                    continue
                active_by_id[track_id].detections.append(detections[index])
                assigned_tracks.add(track_id)
                assigned_detections.add(index)

        # Remove inactive tracks
        active = [
            track for track in active if (day - track.end_date).days <= max_gap_days
        ]

        # Create new tracks
        for index, eddy in enumerate(detections):
            if index not in assigned_detections:
                track = EddyTrack(id=next_id, detections=[eddy])
                tracks.append(track)
                active.append(track)
                next_id += 1

        day += timedelta(days=1)

    return [track for track in tracks if track.lifetime_days >= min_lifetime_days]
