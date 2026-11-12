"""Presentation metadata for Halo candidates; detection decisions stay unchanged."""

from collections import Counter
import numpy as np

REASONS = {
    "accepted": (
        "Accepted",
        "This is the largest eligible loop enclosing this core representative.",
    ),
    "missing_data": (
        "Missing interior data",
        "The loop encloses grid points without finite height or velocity.",
    ),
    "no_rotating_core": (
        "No rotating region",
        "The loop contains no negative-W grid points.",
    ),
    "multiple_cores": (
        "Multiple core representatives",
        "The loop encloses representatives of more than one connected negative-W region.",
    ),
    "partial_core": (
        "Incidental core overlap",
        "The loop intersects negative W but does not enclose a core's minimum-W representative.",
    ),
    "nested_duplicate": (
        "Nested duplicate",
        "A larger eligible loop was selected for the same core representative.",
    ),
}


def prepare_candidates(candidates, detector):
    rows = []
    for candidate in candidates:
        c = dict(candidate)
        contour = c["contour"]
        center = contour[:-1].mean(axis=0)
        c.update(
            status="accepted" if c["accepted"] else "rejected",
            level_cm=c["level"] * 100.0,
            latitude=float(
                np.interp(
                    center[0], np.arange(len(detector.latitude)), detector.latitude
                )
            ),
            longitude=float(
                np.interp(
                    center[1], np.arange(len(detector.longitude)), detector.longitude
                )
            ),
            reason_label=REASONS[c["reason"]][0],
            explanation=REASONS[c["reason"]][1],
            core_count=len(c["region_ids"]),
        )
        c["check_rows"] = [
            {
                "label": "Closed loop",
                "requirement": "Closed on the available height grid",
                "value": "Closed",
                "outcome": "Passed",
            },
            {
                "label": "Diameter",
                "requirement": f"At most {detector.max_diameter_km:g} km",
                "value": f'{c["diameter_km"]:.2f} km',
                "outcome": "Passed",
            },
        ]
        checks = [
            ("Finite interior", "Finite height and both velocities", "missing_data"),
            ("Rotation support", "At least one negative-W pixel", "no_rotating_core"),
            (
                "Core association",
                "Exactly one enclosed minimum-W representative",
                ("multiple_cores", "partial_core"),
            ),
            (
                "Outermost selection",
                "Largest eligible loop for this core",
                "nested_duplicate",
            ),
        ]
        failed = False
        for label, requirement, reason in checks:
            matches = (
                c["reason"] in reason
                if isinstance(reason, tuple)
                else c["reason"] == reason
            )
            outcome = "Not evaluated" if failed else "Failed" if matches else "Passed"
            c["check_rows"].append(
                {
                    "label": label,
                    "requirement": requirement,
                    "value": (
                        "—" if failed else c["reason_label"] if matches else "Satisfied"
                    ),
                    "outcome": outcome,
                }
            )
            failed |= matches
        rows.append(c)
    counts = Counter(c["reason"] for c in rows if not c["accepted"])
    summary = {
        "total": len(rows),
        "accepted": sum(c["accepted"] for c in rows),
        "rejected": sum(not c["accepted"] for c in rows),
        "reasons": [
            {"key": key, "label": REASONS[key][0], "count": count}
            for key, count in counts.most_common()
        ],
    }
    return rows, summary
