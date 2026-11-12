from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from math import isfinite, radians, sqrt

import numpy as np
from scipy.optimize import linear_sum_assignment

from eddy_detection.method_utils import EddyDetection, haversine
from .nencioli_tracking import EddyTrack


def _distance_km(first: EddyDetection, second: EddyDetection) -> float:
    return float(
        haversine(
            radians(first.longitude),
            radians(second.longitude),
            radians(first.latitude),
            radians(second.latitude),
        )
    )


def _generalized_distance(
    first: EddyDetection,
    second: EddyDetection,
    vorticity_by_detection: Mapping[tuple[date, int], float] | None,
    position_scale_km: float,
    diameter_scale_km: float,
    vorticity_scale_s: float,
) -> float:
    # Diameter is twice the equivalent-area radius in the standardized model.
    dx = _distance_km(first, second) / position_scale_km
    dr = (2.0 * second.radius_km - 2.0 * first.radius_km) / diameter_scale_km
    score_squared = dx * dx + dr * dr

    if vorticity_by_detection is not None:
        v1 = vorticity_by_detection[(first.date, first.id)]
        v2 = vorticity_by_detection[(second.date, second.id)]
        # A sign reversal is forbidden by Halo/Penven.
        if v1 * v2 <= 0:
            return float("inf")
        dv = (v2 - v1) / vorticity_scale_s
        score_squared += dv * dv
    else:
        # Standardized Halo detections do not currently include vorticity.
        # 'unknown' polarity is not evidence of opposite rotation.
        if (
            first.polarity != "unknown"
            and second.polarity != "unknown"
            and first.polarity != second.polarity
        ):
            return float("inf")

    return sqrt(score_squared)


def _assign_candidates(candidates, track_ids, detection_count, assignment_method):
    """Maximize gated match count, then minimize total score within this day.

    Explicit unmatched columns make infeasible/rectangular problems safe.
    The greedy option reproduces historical runs. Neither option optimizes
    trajectories over future dates. Input rows/columns define tie ordering.
    """
    if not candidates:
        return []
    if assignment_method == "greedy":
        chosen, used_tracks, used_detections = [], set(), set()
        for candidate in sorted(candidates):
            _, track_id, index = candidate
            if track_id not in used_tracks and index not in used_detections:
                chosen.append(candidate)
                used_tracks.add(track_id)
                used_detections.add(index)
        return chosen
    ids = sorted(track_ids)
    row_by_id = {identifier: row for row, identifier in enumerate(ids)}
    # Normalize before adding penalties to avoid overflow with large scores.
    scale = max(1.0, max(score for score, _, _ in candidates))
    unmatched = min(len(ids), detection_count) + 1.0
    costs = np.full((len(ids), detection_count + len(ids)), np.inf)
    costs[:, detection_count:] = unmatched
    lookup = {}
    for score, track_id, index in candidates:
        costs[row_by_id[track_id], index] = score / scale
        lookup[(track_id, index)] = score
    rows, columns = linear_sum_assignment(costs)
    return [
        (lookup[(ids[row], col)], ids[row], int(col))
        for row, col in zip(rows, columns)
        if col < detection_count
    ]


def track_halo(
    detections_by_day: Mapping[date, Sequence[EddyDetection]],
    *,
    vorticity_by_detection: Mapping[tuple[date, int], float] | None = None,
    max_displacement_km: float = 50.0,
    position_scale_km: float = 25.0,
    diameter_scale_km: float = 200.0,
    vorticity_scale_s: float = 1e-5,
    max_generalized_distance: float | None = 2.0,
    min_lifetime_days: int = 4,
    assignment_method: str = "global",
    max_gap_days: int = 0,
    gap_max_displacement_km: float = 50.0,
    gap_max_generalized_distance: float = 1.0,
    gap_max_diameter_ratio: float = 1.5,
    gap_max_vorticity_ratio: float = 2.0,
    minimum_abs_vorticity_s: float = 0.0,
    diagnostics: dict | None = None,
) -> list[EddyTrack]:
    """Halo-inspired association for the daily OSU SLA adaptation.

    Reference score scales are 25 km, 200 km and 1e-5 s^-1; these are
    configuration values, not universal constants. The 50 km daily gate and
    score cutoff 2 are experimental candidates, not calibrated paper values.
    Set assignment_method='greedy', max_generalized_distance=None and
    max_gap_days=0 to reproduce the previous adjacent-day tracker.

    Global matching maximizes eligible pair count, then minimizes total score
    for one date. With an optional one-day gap, daily matching has priority;
    remaining observations may reconnect to tracks last seen two days ago.
    Gap links use a total-distance cap (not doubled), a stricter score cutoff,
    and symmetric diameter/vorticity ratio gates. No observations are invented.

    Weak signed means at/below minimum_abs_vorticity_s are excluded and flagged;
    sign reversals remain forbidden. The default floor 0 adds no noise model.
    Diagnostics optionally expose every evaluated pair and accepted gap interval.
    Retention uses inclusive observed span; use 31 for an over-30-day analysis
    and distinguish window-censored spans from measured physical lifetimes.
    """
    positive = dict(
        max_displacement_km=max_displacement_km,
        position_scale_km=position_scale_km,
        diameter_scale_km=diameter_scale_km,
        vorticity_scale_s=vorticity_scale_s,
        gap_max_displacement_km=gap_max_displacement_km,
        gap_max_generalized_distance=gap_max_generalized_distance,
    )
    for name, value in positive.items():
        if not isfinite(value) or value <= 0:
            raise ValueError(f"{name} must be positive and finite")
    if max_generalized_distance is not None and (
        not isfinite(max_generalized_distance) or max_generalized_distance <= 0
    ):
        raise ValueError("max_generalized_distance must be positive and finite or None")
    if assignment_method not in ("global", "greedy"):
        raise ValueError("assignment_method must be global or greedy")
    if type(max_gap_days) is not int or max_gap_days not in (0, 1):
        raise ValueError("max_gap_days must be 0 or 1")
    if type(min_lifetime_days) is not int or min_lifetime_days < 1:
        raise ValueError("min_lifetime_days must be a positive integer")
    if not isfinite(minimum_abs_vorticity_s) or minimum_abs_vorticity_s < 0:
        raise ValueError("minimum_abs_vorticity_s must be nonnegative and finite")
    for ratio in (gap_max_diameter_ratio, gap_max_vorticity_ratio):
        if not isfinite(ratio) or ratio < 1:
            raise ValueError("Gap ratio limits must be finite and at least 1")
    if (max_gap_days or minimum_abs_vorticity_s) and vorticity_by_detection is None:
        raise ValueError(
            "Gap recovery and vorticity quality floors require signed vorticity"
        )
    if max_gap_days and (
        gap_max_displacement_km > max_displacement_km
        or (
            max_generalized_distance is not None
            and gap_max_generalized_distance > max_generalized_distance
        )
    ):
        raise ValueError(
            "Gap displacement and score limits must be no looser than daily limits"
        )
    if diagnostics is not None:
        diagnostics.clear()
        diagnostics.update(candidates=[], links=[], exclusions=[])
    if not detections_by_day:
        return []
    eligible_by_day = {}
    for day, eddies in detections_by_day.items():
        seen_ids, eligible = set(), []
        for eddy in eddies:
            if eddy.date != day or eddy.method != "okubo_weiss":
                raise ValueError("Expected Okubo-Weiss detections with matching dates")
            if eddy.id in seen_ids:
                raise ValueError(f"Duplicate detection ID {eddy.id} on {day}")
            seen_ids.add(eddy.id)
            if not (
                isfinite(eddy.latitude)
                and isfinite(eddy.longitude)
                and isfinite(eddy.radius_km)
                and eddy.radius_km > 0
            ):
                raise ValueError(
                    "Detection coordinates and radius must be finite; radius > 0"
                )
            if vorticity_by_detection is not None:
                key = (day, eddy.id)
                if key not in vorticity_by_detection:
                    raise ValueError(f"Missing signed vorticity for detection {key}")
                value = vorticity_by_detection[key]
                if not isfinite(value) or value == 0:
                    raise ValueError(f"Vorticity must be finite and nonzero for {key}")
                if abs(value) <= minimum_abs_vorticity_s:
                    if diagnostics is not None:
                        diagnostics["exclusions"].append(
                            dict(
                                date=day,
                                id=eddy.id,
                                reason="Weak mean vorticity",
                                vorticity_s=value,
                            )
                        )
                    continue
            eligible.append(eddy)
        eligible_by_day[day] = eligible

    tracks, active = [], []
    day, last_day = min(eligible_by_day), max(eligible_by_day)
    while day <= last_day:
        detections = eligible_by_day.get(day, [])
        assigned_tracks, assigned_detections = set(), set()
        active_by_id = {track.id: track for track in active}
        for elapsed in range(1, max_gap_days + 2):
            candidates, records = [], {}
            for track in active:
                previous = track.detections[-1]
                if track.id in assigned_tracks or (day - previous.date).days != elapsed:
                    continue
                for index, eddy in enumerate(detections):
                    if index in assigned_detections:
                        continue
                    displacement = _distance_km(previous, eddy)
                    limit = (
                        max_displacement_km if elapsed == 1 else gap_max_displacement_km
                    )
                    cutoff = (
                        max_generalized_distance
                        if elapsed == 1
                        else gap_max_generalized_distance
                    )
                    score, reason = None, None
                    if displacement > limit:
                        reason = "displacement"
                    else:
                        score = _generalized_distance(
                            previous,
                            eddy,
                            vorticity_by_detection,
                            position_scale_km,
                            diameter_scale_km,
                            vorticity_scale_s,
                        )
                        if not isfinite(score):
                            score, reason = None, "rotation_sign"
                        elif cutoff is not None and score > cutoff:
                            reason = "score"
                        elif elapsed == 2:
                            diameter_ratio = eddy.radius_km / previous.radius_km
                            vorticity_ratio = abs(
                                vorticity_by_detection[(eddy.date, eddy.id)]
                                / vorticity_by_detection[(previous.date, previous.id)]
                            )
                            if (
                                not 1 / gap_max_diameter_ratio
                                <= diameter_ratio
                                <= gap_max_diameter_ratio
                            ):
                                reason = "gap_diameter_ratio"
                            elif (
                                not 1 / gap_max_vorticity_ratio
                                <= vorticity_ratio
                                <= gap_max_vorticity_ratio
                            ):
                                reason = "gap_vorticity_ratio"
                    if reason is None:
                        candidates.append((score, track.id, index))
                    if diagnostics is not None:
                        record = dict(
                            track_id=track.id,
                            first_date=previous.date,
                            first_id=previous.id,
                            second_date=eddy.date,
                            second_id=eddy.id,
                            elapsed_days=elapsed,
                            displacement_km=displacement,
                            score=score,
                            accepted=False,
                            reason=reason or "assignment_conflict",
                        )
                        diagnostics["candidates"].append(record)
                        records[(track.id, index)] = record
            chosen = _assign_candidates(
                candidates,
                {track_id for _, track_id, _ in candidates},
                len(detections),
                assignment_method,
            )
            for score, track_id, index in chosen:
                previous = active_by_id[track_id].detections[-1]
                active_by_id[track_id].detections.append(detections[index])
                assigned_tracks.add(track_id)
                assigned_detections.add(index)
                if diagnostics is not None:
                    record = records[(track_id, index)]
                    record.update(accepted=True, reason="accepted")
                    diagnostics["links"].append(
                        dict(
                            record,
                            recovered_gap=elapsed == 2,
                            missing_date=(
                                previous.date + timedelta(days=1)
                                if elapsed == 2
                                else None
                            ),
                        )
                    )
        active = [
            track for track in active if (day - track.end_date).days <= max_gap_days
        ]
        for index, eddy in enumerate(detections):
            if index not in assigned_detections:
                track = EddyTrack(id=len(tracks) + 1, detections=[eddy])
                tracks.append(track)
                active.append(track)
        day += timedelta(days=1)
    return [track for track in tracks if track.lifetime_days >= min_lifetime_days]
