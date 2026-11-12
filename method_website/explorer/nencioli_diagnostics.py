"""Presentation of detector decisions; no additional acceptance criteria."""

from collections import Counter

import numpy as np
from eddy_detection.nencioli_method import NencioliCenterDetector

REASONS = {
    "accepted": (
        "Boundary accepted",
        "The center passes all four constraints and has an accepted boundary.",
    ),
    "zonal_velocity": (
        "2 · North–south velocity",
        "North/south u does not reverse with the expected rotation and increase in magnitude away from this candidate.",
    ),
    "local_minimum": (
        "3 · Stable speed minimum",
        "The two minimum searches disagree, or a search window contains missing data or extends beyond the grid.",
    ),
    "perimeter_domain": (
        "4 · Perimeter outside grid",
        "The square extending a−1 cells from the refined minimum does not fit within the grid.",
    ),
    "perimeter_rotation": (
        "4 · Closed circulation",
        "The perimeter contains missing/zero vectors, reverses its angular progression, skips quadrants, or fails to complete a full turn.",
    ),
    "duplicate_center": (
        "Already detected center",
        "This search reaches a center already recorded by another candidate; it is not a separate eddy.",
    ),
    "no_ocean_region": (
        "Boundary · Insufficient ocean region",
        "No finite local velocity region of the required size is available around this center.",
    ),
    "no_growing_contour": (
        "Boundary · Radial growth",
        "Closed streamfunction contours exist, but none passes the speed-growth test at all four extrema.",
    ),
}


def prepare_diagnostics(diagnostics, results, latitude, longitude, u, v):
    accepted = {(r[0], r[1]): r for r in results}
    rows = []
    for candidate in diagnostics["candidates"]:
        row = dict(candidate)
        ci, cj = row["center_i"], row["center_j"]
        i, j = (ci, cj) if ci is not None else (row["i"], row["j"])
        row.update(
            latitude=float(latitude[i]),
            longitude=float(longitude[j]),
            rotation=row["direction"]
            .name.replace("COUNTERCLOCKWISE", "Counterclockwise")
            .replace("CLOCKWISE", "Clockwise"),
            reason_label=REASONS[row["reason"]][0],
            explanation=REASONS[row["reason"]][1],
            speed=float(np.hypot(u[i, j], v[i, j])),
        )
        row["criteria"] = [
            {"label": "1 · EW reversal and growth", "result": "Pass"},
            *[
                {
                    "label": label,
                    "result": (
                        "Not evaluated"
                        if row[key] is None
                        else "Pass" if row[key] else "Fail"
                    ),
                }
                for key, label in (
                    ("zonal_pass", "2 · NS reversal and growth"),
                    ("minimum_pass", "3 · Stable speed minimum"),
                    ("perimeter_pass", "4 · Closed circulation"),
                )
            ],
        ]
        if row["reason"] == "perimeter_domain":
            row["criteria"][-1]["result"] = "Outside grid"
        if row["status"] == "duplicate":
            row["criteria"][-1]["result"] = "Already recorded"
        result = accepted.get((ci, cj))
        if row["status"] == "accepted" and result is not None:
            row["radius_km"] = result[4]
            row["contour"] = result[3]
        row["source_label"] = {
            "streamfunction": "Closed streamline",
            "circular_fallback": "Estimated circle",
        }.get(row.get("source") or "", "—")
        rows.append(row)
    counts = Counter(row["status"] for row in rows)
    reason_counts = Counter(
        row["reason"] for row in rows if row["status"] == "rejected"
    )
    stats = diagnostics["center_counts"]
    stages = [
        (
            "1 · EW sign reversal and growth",
            stats["meridional_pass"],
            "Adjacent EW pairs",
        ),
        (
            "2 · NS sign reversal and growth",
            stats["zonal_pass"],
            "Pair members passing criterion 2",
        ),
        (
            "3 · Stable local minimum",
            stats["minimum_pass"],
            "Searches passing criterion 3, including repeats",
        ),
        (
            "4 · Closed circulation",
            len(diagnostics["centers"]),
            "Unique centers passing all four constraints",
        ),
        ("Boundary selection", len(results), "Centers with accepted boundaries"),
    ]
    return {
        "diagnostics": rows,
        "accepted_eddies": [row for row in rows if row["status"] == "accepted"],
        "diagnostic_summary": {
            "total": len(rows),
            "centers": len(diagnostics["centers"]),
            "accepted": counts["accepted"],
            "rejected": counts["rejected"],
            "duplicates": counts["duplicate"],
            "circular": sum(row.get("source") == "circular_fallback" for row in rows),
            "reasons": [
                {"label": REASONS[reason][0], "key": reason, "count": count}
                for reason, count in reason_counts.most_common()
            ],
        },
        "stages": [
            {"label": label, "count": count, "unit": unit}
            for label, count, unit in stages
        ],
    }


def grid_comparison(latitude, longitude, a, b):
    """Physical distances for interpreting a and b on the actual selected grid."""
    dy_km = 6371 * np.deg2rad(float(np.median(np.diff(latitude))))
    dx_km = (
        6371
        * np.cos(np.deg2rad(float(np.mean(latitude))))
        * np.deg2rad(float(np.median(np.diff(longitude))))
    )
    return {
        "dx_km": dx_km,
        "dy_km": dy_km,
        "a_x_km": a * dx_km,
        "a_y_km": a * dy_km,
        "b_x_km": b * dx_km,
        "b_y_km": b * dy_km,
        "perimeter_x_km": (a - 1) * dx_km,
        "perimeter_y_km": (a - 1) * dy_km,
    }


def perimeter_evidence(latitude, longitude, u, v, a, b, candidate):
    if candidate["perimeter_pass"] is None:
        return None
    detector = NencioliCenterDetector(latitude, longitude, u, v, a, b)
    vectors = detector.extract_perimeter_vectors(
        candidate["center_i"], candidate["center_j"]
    )
    if vectors is None:
        return "The perimeter contains missing velocity vectors."
    if np.any(np.linalg.norm(vectors, axis=1) == 0):
        return "The perimeter contains zero-speed vectors, so their direction is undefined."
    angles = np.arctan2(vectors[:, 1], vectors[:, 0])
    steps = np.angle(np.exp(1j * (np.roll(angles, -1) - angles)))
    quadrants = np.floor(np.mod(angles, 2 * np.pi) / (np.pi / 2)).astype(int)
    jumps = (np.roll(quadrants, -1) - quadrants) % 4
    return (
        f"Total turning: {np.rad2deg(steps.sum()):.1f}° (required: 360°). "
        f"Reverse angular steps: {np.count_nonzero(steps < -1e-10)} (required: 0). "
        f"Transitions outside the same or next CCW quadrant: {np.count_nonzero(jumps > 1)} (required: 0)."
    )
