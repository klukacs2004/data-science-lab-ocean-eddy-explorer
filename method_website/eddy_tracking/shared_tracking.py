"""Comparable daily association, independent of detector-specific trackers.

Experimental rules: known equal polarity, a circular displacement gate, and
optionally a symmetric reliable-area gate and area-consistency score. Assignment
maximizes gated cardinality, then minimizes total score. No gap recovery or
look-ahead is performed. Detection objects are never modified.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from math import asin, cos, isfinite, log, radians, sin, sqrt

import numpy as np
from scipy.optimize import linear_sum_assignment
from eddy_detection.method_utils import EddyDetection


@dataclass
class SharedTrack:
    id: int
    detections: list[EddyDetection] = field(default_factory=list)

    @property
    def start_date(self):
        return self.detections[0].date

    @property
    def end_date(self):
        return self.detections[-1].date

    @property
    def lifetime_days(self):
        return (self.end_date - self.start_date).days + 1


@dataclass
class SharedTrackingResult:
    tracks: list[SharedTrack]
    links: list[dict]
    daily_diagnostics: list[dict]
    candidate_diagnostics: list[dict] = field(default_factory=list)


def center(detection, policy="standardized"):
    if (
        policy == "native_preferred"
        and detection.native_center_latitude is not None
        and detection.native_center_longitude is not None
    ):
        return detection.native_center_latitude, detection.native_center_longitude
    return detection.latitude, detection.longitude


def distance_km(first, second, policy="standardized"):
    lat1, lon1 = center(first, policy)
    lat2, lon2 = center(second, policy)
    phi1, phi2 = radians(lat1), radians(lat2)
    a = (
        sin((phi2 - phi1) / 2) ** 2
        + cos(phi1) * cos(phi2) * sin(radians((lon2 - lon1 + 180) % 360 - 180) / 2) ** 2
    )
    return 12742.0 * asin(sqrt(min(1.0, max(0.0, a))))


def global_assignment(candidates, detection_count):
    """Candidates are (nonnegative score, track ID, detection column)."""
    if not candidates:
        return []
    ids = sorted({identifier for _, identifier, _ in candidates})
    row_by_id = {identifier: i for i, identifier in enumerate(ids)}
    scale = max(1.0, max(score for score, _, _ in candidates))
    # One lost match must cost more than any possible change in feasible scores.
    unmatched = min(len(ids), detection_count) + 1.0
    costs = np.full((len(ids), detection_count + len(ids)), np.inf)
    costs[:, detection_count:] = unmatched
    lookup = {}
    for score, identifier, index in candidates:
        costs[row_by_id[identifier], index] = score / scale
        lookup[identifier, index] = score
    rows, columns = linear_sum_assignment(costs)
    return [
        (lookup[ids[row], int(column)], ids[row], int(column))
        for row, column in zip(rows, columns)
        if column < detection_count
    ]


def track_shared(
    detections_by_day: Mapping[date, Sequence[EddyDetection]],
    *,
    max_displacement_km: float,
    use_area_consistency: bool = True,
    maximum_area_factor: float | None = 2.0,
    position_score_scale_km: float | None = None,
    area_score_factor: float | None = None,
    record_candidates: bool = False,
    stable_detection_ties: bool = False,
    center_policy: str = "standardized",
    polarity_by_detection: Mapping[tuple[date, int], str] | None = None,
    reliable_area_by_detection: Mapping[tuple[date, int], bool] | None = None,
) -> SharedTrackingResult:
    """Track one frozen catalogue; return all segments including singletons.

    Supply position_score_scale_km and area_score_factor explicitly to hold
    assignment preferences fixed while varying maximum_area_factor. None as
    maximum_area_factor removes its gate but retains the area score. Defaults
    preserve the earlier coupled-scale experiment. stable_detection_ties uses
    daily source detection IDs for row tie ordering, independent of track IDs.
    record_candidates records all known-polarity candidates inside the position
    gate, including rejected, eligible-but-unassigned and selected pairs.
    Primary area score is sqrt((distance/position_scale)^2 + (log(area ratio)/log(area_scale))^2).
    The displacement-only ablation retains known equal polarity but removes both
    the area gate and its score term. Unknown polarity never establishes identity.
    Nencioli fallback/unknown boundary areas cannot enter the area gate or score.
    Standardized contour centers are primary; native_preferred is an explicit
    center-policy sensitivity. No detector-specific amplitude/vorticity-magnitude
    terms are used. Halo polarity annotations must be supplied separately.
    """
    if not isfinite(max_displacement_km) or max_displacement_km <= 0:
        raise ValueError("max_displacement_km must be positive and finite")
    if maximum_area_factor is not None and (
        not isfinite(maximum_area_factor) or maximum_area_factor <= 1
    ):
        raise ValueError("maximum_area_factor must exceed one or be None")
    position_scale = (
        max_displacement_km
        if position_score_scale_km is None
        else position_score_scale_km
    )
    area_scale = (
        (maximum_area_factor if maximum_area_factor is not None else 2.0)
        if area_score_factor is None
        else area_score_factor
    )
    if not isfinite(position_scale) or position_scale <= 0:
        raise ValueError("position_score_scale_km must be positive and finite")
    if not isfinite(area_scale) or area_scale <= 1:
        raise ValueError("area_score_factor must exceed one")
    if center_policy not in ("standardized", "native_preferred"):
        raise ValueError("Unknown center_policy")
    # Validate the frozen catalogue before building any temporal links.
    methods = set()
    for day, detections in detections_by_day.items():
        ids = set()
        for e in detections:
            if e.date != day or e.id in ids:
                raise ValueError(
                    "Dates must match dictionary keys and daily IDs must be unique"
                )
            ids.add(e.id)
            methods.add(e.method)
            lat, lon = center(e, center_policy)
            if not isfinite(lat) or not isfinite(lon) or abs(lat) > 90:
                raise ValueError("Detection center must be finite and geographic")
    if len(methods) > 1:
        raise ValueError("Track each detection catalogue separately")
    if not detections_by_day:
        return SharedTrackingResult([], [], [])

    def polarity(e):
        return (
            polarity_by_detection.get((e.date, e.id), "unknown")
            if polarity_by_detection is not None
            else e.polarity
        )

    def reliable(e):
        return (
            reliable_area_by_detection.get((e.date, e.id), False)
            if reliable_area_by_detection is not None
            else e.has_reliable_radius
        )

    tracks, links, diagnostics, active = [], [], [], []
    candidate_audit = []
    day, last_day = min(detections_by_day), max(detections_by_day)
    while day <= last_day:
        # Build same-polarity candidates under the displacement and area gates.
        detections = sorted(detections_by_day.get(day, ()), key=lambda e: e.id)
        candidates, details = [], {}
        daily_audit = []
        counts = {
            "date": day,
            "source_tracks": len(active),
            "detections": len(detections),
            "polarity_rejections": 0,
            "distance_rejections": 0,
            "unreliable_area_rejections": 0,
            "area_ratio_rejections": 0,
        }
        current_polarities = np.array([polarity(e) for e in detections], dtype=object)
        if active and detections:
            previous_centers = np.deg2rad(
                np.array([center(t.detections[-1], center_policy) for t in active])
            )
            current_centers = np.deg2rad(
                np.array([center(e, center_policy) for e in detections])
            )
            latitude_difference = (
                current_centers[None, :, 0] - previous_centers[:, None, 0]
            )
            longitude_difference = (
                current_centers[None, :, 1] - previous_centers[:, None, 1] + np.pi
            ) % (2 * np.pi) - np.pi
            h = (
                np.sin(latitude_difference / 2) ** 2
                + np.cos(previous_centers[:, None, 0])
                * np.cos(current_centers[None, :, 0])
                * np.sin(longitude_difference / 2) ** 2
            )
            distances = 12742.0 * np.arcsin(np.sqrt(np.clip(h, 0, 1)))
        for row, track in enumerate(active):
            a = track.detections[-1]
            known = polarity(a) in ("cyclonic", "anticyclonic")
            matching = (current_polarities == polarity(a)) & known
            counts["polarity_rejections"] += int((~matching).sum())
            within = (
                distances[row] <= max_displacement_km
                if detections
                else np.array([], dtype=bool)
            )
            counts["distance_rejections"] += int((matching & ~within).sum())
            for index in np.flatnonzero(matching & within):
                b = detections[index]
                displacement = float(distances[row, index])
                ratio, area_score = None, 0.0
                audit = {
                    "first_date": a.date,
                    "first_detection_id": a.id,
                    "second_date": b.date,
                    "second_detection_id": b.id,
                    "displacement_km": displacement,
                    "area_ratio": None,
                    "assignment_score": None,
                    "decision": "eligible",
                    "selected": False,
                }
                if record_candidates:
                    daily_audit.append(audit)
                if use_area_consistency:
                    if (
                        not reliable(a)
                        or not reliable(b)
                        or a.area_km2 is None
                        or b.area_km2 is None
                        or not isfinite(a.area_km2)
                        or not isfinite(b.area_km2)
                        or min(a.area_km2, b.area_km2) <= 0
                    ):
                        counts["unreliable_area_rejections"] += 1
                        audit["decision"] = "unreliable_area"
                        continue
                    ratio = b.area_km2 / a.area_km2
                    area_score = log(ratio) / log(area_scale)
                score = sqrt((displacement / position_scale) ** 2 + area_score**2)
                audit["area_ratio"], audit["assignment_score"] = ratio, score
                if (
                    use_area_consistency
                    and maximum_area_factor is not None
                    and not 1 / maximum_area_factor <= ratio <= maximum_area_factor
                ):
                    counts["area_ratio_rejections"] += 1
                    audit["decision"] = "area_ratio"
                    continue
                candidates.append((score, track.id, index))
                details[track.id, index] = displacement, ratio
        # Resolve today's candidates globally, with the selected tie policy.
        if stable_detection_ties:
            source_ids = {track.id: track.detections[-1].id for track in active}
            track_ids = {value: identifier for identifier, value in source_ids.items()}
            chosen = [
                (score, track_ids[source_id], index)
                for score, source_id, index in global_assignment(
                    [
                        (score, source_ids[identifier], index)
                        for score, identifier, index in candidates
                    ],
                    len(detections),
                )
            ]
        else:
            chosen = global_assignment(candidates, len(detections))
        # Record assignment outcomes separately from the accepted track links.
        if record_candidates:
            selected_keys = {
                (
                    next(t.detections[-1].id for t in active if t.id == identifier),
                    detections[index].id,
                )
                for _, identifier, index in chosen
            }
            for audit in daily_audit:
                audit["selected"] = (
                    audit["first_detection_id"],
                    audit["second_detection_id"],
                ) in selected_keys
                if audit["decision"] == "eligible":
                    audit["decision"] = (
                        "selected" if audit["selected"] else "assignment_conflict"
                    )
            candidate_audit.extend(daily_audit)
        by_id = {t.id: t for t in active}
        assigned = set()
        source_counts, target_counts = {}, {}
        for _, identifier, index in candidates:
            source_counts[identifier] = source_counts.get(identifier, 0) + 1
            target_counts[index] = target_counts.get(index, 0) + 1
        # Extend assigned tracks and start new tracks for unused detections.
        new_active = []
        for score, identifier, index in chosen:
            track, b = by_id[identifier], detections[index]
            a = track.detections[-1]
            displacement, ratio = details[identifier, index]
            links.append(
                {
                    "track_id": identifier,
                    "first_date": a.date,
                    "first_detection_id": a.id,
                    "second_date": b.date,
                    "second_detection_id": b.id,
                    "elapsed_days": 1,
                    "displacement_km": displacement,
                    "area_ratio": ratio,
                    "assignment_score": score,
                    "source_candidates": source_counts[identifier],
                    "target_candidates": target_counts[index],
                }
            )
            track.detections.append(b)
            assigned.add(index)
            new_active.append(track)
        for index, e in enumerate(detections):
            if index not in assigned:
                track = SharedTrack(len(tracks) + 1, [e])
                tracks.append(track)
                new_active.append(track)
        counts.update(
            eligible_candidates=len(candidates),
            links=len(chosen),
            assignment_conflict_candidates=len(candidates) - len(chosen),
            ended_tracks=len(active) - len(chosen),
            new_tracks=len(detections) - len(chosen),
        )
        diagnostics.append(counts)
        active = sorted(new_active, key=lambda t: t.id)
        day += timedelta(days=1)
    return SharedTrackingResult(tracks, links, diagnostics, candidate_audit)
