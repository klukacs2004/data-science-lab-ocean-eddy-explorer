"""Readable Chelton decisions, filtering metadata, and export rows."""

import numpy as np
from eddy_detection.chelton_method import gaussian_cutoff_degrees, paper_scale_sigma

EXPLANATIONS = {
    "Touches the domain boundary": "The candidate reaches the cropped map boundary, so a closed SSH perimeter cannot be established within the available domain.",
    "Touches missing data": "The candidate or its nearest-neighbor perimeter touches missing data. This additional data-quality check avoids treating an unknown coastline or gap as a closed SSH contour.",
    "Size outside [8, 1000) grid cells": "Appendix B.2 requires at least 8 and fewer than 1000 connected pixels.",
    "Contains holes": "The candidate is not simply connected: at least one enclosed pixel is outside the threshold region.",
    "No qualifying interior local extremum": "No strict SSH extremum has all four nearest neighbors inside this candidate. Peaks on the perimeter do not qualify.",
    "Amplitude below 1 cm": "The difference between the interior SSH extremum and the mean SSH of the perimeter pixels is below 1 cm.",
    "Maximum pair distance reaches latitude-dependent limit": "At least one pair of candidate pixels is too far apart. The limit is 400 km poleward of 25°, increasing linearly to 1200 km at the equator.",
    "All implemented criteria passed": "The connected patch passes the implemented single-map shape and amplitude checks. This does not establish its lifetime, propagation speed, or nonlinearity.",
}


def filtering_settings(field, mode, sigma_cells):
    labels = {
        "custom": "Custom Gaussian background removal",
        "paper_scale": "Paper-scale Gaussian approximation",
        "none": "No additional filtering",
    }
    sigma = (
        paper_scale_sigma(field)
        if mode == "paper_scale"
        else (sigma_cells, sigma_cells) if mode == "custom" else None
    )
    result = {"mode": mode, "label": labels[mode], "sigma": sigma}
    if sigma is not None:
        scales = dict(zip(field.dims, sigma))
        for dim, short in (("longitude", "lon"), ("latitude", "lat")):
            result[f"sigma_{short}"] = scales[dim]
            result[f"cutoff_{short}"] = gaussian_cutoff_degrees(
                scales[dim], float(np.median(np.diff(field[dim])))
            )
    return result


def prepare_candidates(diagnostics):
    for candidate in diagnostics:
        candidate["explanation"] = EXPLANATIONS[candidate["reason"]]
        candidate["status"] = "accepted" if candidate["accepted"] else "rejected"
        candidate["threshold_cm"] = candidate["threshold_m"] * 100
        candidate["amplitude_cm"] = (
            candidate["amplitude_m"] * 100
            if candidate["amplitude_m"] is not None
            else None
        )
        candidate["polarity_label"] = (
            "Maximum / concave down"
            if candidate["polarity"] == "maximum"
            else "Minimum / concave up"
        )
        limits = candidate["diameter_limit_km"]
        definitions = [
            (
                "domain",
                "Closed within the map",
                "No contact with the domain edge",
                None,
            ),
            ("missing", "Valid surrounding data", "No adjacent missing pixels", None),
            ("size", "Pixel count", "8 ≤ pixels < 1000", str(candidate["size"])),
            ("holes", "Simply connected", "No enclosed holes", None),
            (
                "extrema",
                "Interior local extrema",
                "At least one strict four-neighbor extremum",
                candidate.get("extrema_count"),
            ),
            (
                "amplitude",
                "Amplitude",
                "At least 1 cm",
                (
                    f"{candidate['amplitude_cm']:.3f} cm"
                    if candidate["amplitude_cm"] is not None
                    else None
                ),
            ),
            (
                "diameter",
                "Maximum pair distance",
                f"Less than {limits:.1f} km",
                (
                    f"{candidate['diameter_km']:.2f} km"
                    if candidate["diameter_km"] is not None
                    else None
                ),
            ),
        ]
        candidate["check_rows"] = [
            {
                "label": label,
                "requirement": requirement,
                "value": value,
                "outcome": (
                    "Not evaluated"
                    if candidate["checks"][key] is None
                    else "Pass" if candidate["checks"][key] else "Fail"
                ),
            }
            for key, label, requirement, value in definitions
        ]
    return diagnostics
