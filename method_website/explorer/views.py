from typing import cast
import logging

from django.shortcuts import render
from django.http import JsonResponse
import pandas as pd

from explorer.plots.halo import HaloPlotter

from .methods import load_sla_day, load_velocity_field, load_reference_mean

from .forms import CheltonDetectionForm, NencioliDetectionForm
from .plots.chelton import CheltonPlotter
from .plots.chelton import InteractiveCheltonPlotter
from .plots.sla_map import InteractiveSlaMapPlotter
from eddy_detection.chelton_method import (
    Polarity,
    high_pass_filter,
    paper_scale_sigma,
    detect_at_threshold,
    scan_thresholds,
)

from eddy_detection.nencioli_method import NencioliCenterDetector, detect_eddies
from .plots.nencioli import NencioliPlotter
from .plots.nencioli import InteractiveNencioliPlotter

from .nencioli_diagnostics import (
    prepare_diagnostics,
    grid_comparison,
    perimeter_evidence,
)

from .chelton_diagnostics import prepare_candidates, filtering_settings

from collections import Counter

from .datasets import get_available_dates, get_available_years, get_dates_for_year


# Dataset availability, project overview, and reproduction instructions.
def available_dates(request):
    year = request.GET.get("year", "")

    if year not in get_available_years():
        return JsonResponse({"dates": []}, status=400)

    return JsonResponse(
        {
            "dates": get_dates_for_year(year),
        }
    )


def welcome_page(request):
    from datetime import date
    import numpy as np

    context, fields = {}, {}
    try:
        dates = get_available_dates()
        if dates:
            day = date.fromisoformat(min(dates))
            fields["sla"] = load_sla_day(day)
            context["sla_date"] = day
    except (OSError, KeyError, ValueError):
        context["sla_map_error"] = (
            "The introductory SLA field is currently unavailable."
        )
    try:
        fields["reference"] = load_reference_mean()
    except (OSError, KeyError, ValueError):
        context["reference_map_error"] = (
            "The 1993–2012 reference mean field is currently unavailable."
        )

    # Keep the daily anomaly scale; stretch the mean field across its observed range.
    maxima = [
        float(np.max(np.abs(field.values[np.isfinite(field.values)]))) * 100
        for field in fields.values()
        if np.isfinite(field.values).any()
    ]
    vmax = max(maxima, default=0) or 1.0
    shared_view = None
    script_loaded = False
    for key, field in fields.items():
        try:
            kwargs = {"vmax_cm": vmax}
            if key == "reference":
                values = field.values[np.isfinite(field.values)]
                minimum, maximum = (
                    (float(values.min()) * 100, float(values.max()) * 100)
                    if values.size
                    else (0.0, 1.0)
                )
                if minimum == maximum:
                    padding = max(abs(minimum) * 0.01, 0.01)
                    minimum, maximum = minimum - padding, maximum + padding
                kwargs.update(
                    field_label="Mean AVISO SLA · 1993–2012",
                    colorbar_title="Mean SLA<br>(cm)",
                    vmin_cm=minimum,
                    vmax_cm=maximum,
                    colorscale="viridis",
                )
            figure = InteractiveSlaMapPlotter().detection(field, **kwargs)
            if key == "sla":
                try:
                    u, v = load_velocity_field(context["sla_date"])
                    InteractiveSlaMapPlotter().add_velocity(figure, field, u, v)
                    context["velocity_shown"] = True
                except (OSError, KeyError, ValueError):
                    context["velocity_error"] = (
                        "Geostrophic velocities are unavailable for this daily grid."
                    )
            if key == "reference":
                figure.data[1].marker.colorbar.update(tickformat=".1f", nticks=7)
            map_layout = figure.to_dict()["layout"]["map"]
            if shared_view is None:
                shared_view = {
                    "zoom": max(0, map_layout["zoom"] - 1.1),
                    "center": {
                        **map_layout["center"],
                        "lon": map_layout["center"]["lon"] - 2.0,
                    },
                }
            figure.update_layout(
                map_zoom=shared_view["zoom"],
                map_center=shared_view["center"],
                height=500,
                margin={"l": 0, "r": 95, "t": 0, "b": 0, "autoexpand": False},
                map_domain={"x": [0, 1], "y": [0, 1]},
            )
            context[f"{key}_map_html"] = figure.to_html(
                full_html=False,
                include_plotlyjs=not script_loaded,
                div_id=f"welcome-{key}-map",
                config={"responsive": True, "scrollZoom": True, "displayModeBar": True},
            )
            script_loaded = True
        except (OSError, KeyError, ValueError):
            context[f"{key}_map_error"] = (
                "The introductory field is currently unavailable."
            )
    return render(request, "explorer/welcome.html", context)


def reproduction_page(request):
    return render(request, "explorer/reproduction.html")


# Chelton methodology, daily detection, and tracking.
def chelton_methodology_page(request):
    return render(request, "explorer/chelton/methodology.html")


def chelton_detection_page(request):
    context = {}
    if request.method == "POST":
        data = request.POST.copy()
        data.setdefault("filter_mode", "custom")
        if "inspect_candidate" in data:
            data["candidate_id"] = data["inspect_candidate"]
        form = CheltonDetectionForm(data)
        if form.is_valid():
            day = form.cleaned_data["day"]
            try:
                sla_day = load_sla_day(day)
            except (KeyError, ValueError):
                form.add_error(
                    "day", "No unique daily SLA field is available for this date."
                )
            else:
                mode = form.cleaned_data["detection_mode"]
                filtering = filtering_settings(
                    sla_day,
                    form.cleaned_data["filter_mode"],
                    form.cleaned_data.get("sigma_cells"),
                )
                filtered_day = (
                    high_pass_filter(sla_day, sigma=filtering["sigma"])
                    if filtering["sigma"]
                    else sla_day.copy()
                )
                threshold = form.cleaned_data["threshold_cm"]
                polarity = cast(Polarity, form.cleaned_data["polarity"])
                if mode == "scan":
                    patches, diagnostics = scan_thresholds(
                        filtered_day, return_diagnostics=True
                    )
                else:
                    patches, diagnostics = detect_at_threshold(
                        filtered_day,
                        threshold / 100.0,
                        polarity,
                        return_diagnostics=True,
                    )
                diagnostics = prepare_candidates(diagnostics)
                context["patches"] = patches
                context["diagnostics"] = diagnostics
                context["accepted_patches"] = [
                    candidate for candidate in diagnostics if candidate["accepted"]
                ]
                context["filtering"] = filtering
                context["run_settings"] = {
                    "day": day,
                    "mode": mode,
                    "threshold_cm": threshold,
                    "polarity": polarity,
                    "sigma_cells": form.cleaned_data.get("sigma_cells"),
                }
                counts = Counter(c["reason"] for c in diagnostics if not c["accepted"])
                context["diagnostic_summary"] = {
                    "total": len(diagnostics),
                    "accepted": len(patches),
                    "rejected": len(diagnostics) - len(patches),
                    "reasons": [
                        {"reason": reason, "count": count}
                        for reason, count in counts.most_common()
                    ],
                }
                plotter = CheltonPlotter()
                context["plot_image"] = plotter.to_base64(
                    plotter.detection(sla_day, patches)
                )
                context["plot_image_html"] = (
                    InteractiveCheltonPlotter()
                    .detection(
                        sla_day,
                        patches,
                        diagnostics=diagnostics,
                    )
                    .to_html(
                        full_html=False,
                        include_plotlyjs=True,
                        div_id="chelton-map",
                        config={"responsive": True},
                    )
                )
                context["filtering_image"] = plotter.to_base64(
                    plotter.filtering(sla_day, filtered_day)
                )
                if mode == "single":
                    context["threshold_image"] = plotter.to_base64(
                        plotter.threshold(
                            filtered_day, threshold / 100.0, patches, polarity=polarity
                        )
                    )
                context["diagnostics_plot"] = plotter.to_base64(
                    plotter.diagnostics(filtered_day, diagnostics)
                )
                fields = (
                    "id",
                    "status",
                    "reason",
                    "polarity",
                    "threshold_cm",
                    "size",
                    "latitude",
                    "longitude",
                    "amplitude_cm",
                    "diameter_km",
                    "area_km2",
                    "effective_radius_km",
                    "extrema_count",
                )
                context["candidate_export"] = [
                    {key: candidate.get(key) for key in fields}
                    for candidate in diagnostics
                ]
                context["scan_rows"] = []
                if mode == "scan":
                    groups = {}
                    for candidate in diagnostics:
                        key = (candidate["polarity"], candidate["threshold_m"])
                        item = groups.setdefault(
                            key,
                            {
                                "polarity": key[0],
                                "threshold_cm": round(key[1] * 100),
                                "candidates": 0,
                                "accepted": 0,
                            },
                        )
                        item["candidates"] += 1
                        item["accepted"] += int(candidate["accepted"])
                    context["scan_rows"] = list(groups.values())
                    context["scan_image"] = plotter.to_base64(
                        plotter.scan_summary(diagnostics)
                    )
                candidate_id = form.cleaned_data.get("candidate_id")
                if candidate_id is not None:
                    selected = next(
                        (c for c in diagnostics if c["id"] == candidate_id), None
                    )
                    if selected is None:
                        form.add_error(
                            "candidate_id",
                            "This ID does not exist for the current date, filter, and detection settings.",
                        )
                    else:
                        context["selected_candidate"] = selected
                        context["candidate_image"] = plotter.to_base64(
                            plotter.candidate(filtered_day, selected)
                        )
                if filtering["mode"] == "paper_scale":
                    reference = patches
                else:
                    reference_field = high_pass_filter(
                        sla_day, paper_scale_sigma(sla_day)
                    )
                    reference = (
                        scan_thresholds(reference_field)
                        if mode == "scan"
                        else detect_at_threshold(
                            reference_field, threshold / 100.0, polarity
                        )
                    )
                context["paper_comparison"] = {
                    "selected": len(patches),
                    "paper_scale": len(reference),
                }
    else:
        form = CheltonDetectionForm()
    return render(request, "explorer/chelton/index.html", {"form": form, **context})


def chelton_tracking_page(request):
    import logging
    from .forms import CheltonTrackingForm
    from .chelton_tracking import run_chelton_tracking
    from .plots.tracking import NencioliTrackingPlotter

    form = CheltonTrackingForm(request.POST if request.method == "POST" else None)
    context = {"is_chelton": True}
    if request.method == "POST" and form.is_valid():
        try:
            result = run_chelton_tracking(form.cleaned_data)
            figure = NencioliTrackingPlotter().trajectories(
                result["tracks"], result["dataset_grid"], method_label="Chelton"
            )
            map_html = figure.to_html(
                full_html=False,
                include_plotlyjs=True,
                div_id="tracking-map",
                config={"responsive": True, "scrollZoom": False},
            )
            context.update(
                {
                    **result,
                    "ran": True,
                    "run_settings": form.cleaned_data,
                    "map_html": map_html,
                }
            )
        except (OSError, KeyError, ValueError, RuntimeError, IndexError) as exc:
            form.add_error(None, f"Cannot run tracking: {exc}")
        except Exception:
            logging.getLogger(__name__).exception("Chelton tracking failed")
            form.add_error(
                None,
                "Tracking could not be completed. Please try a shorter duration or another date.",
            )
    return render(request, "explorer/chelton/tracking.html", {"form": form, **context})


# Nencioli methodology, daily detection, and tracking.
def nencioli_methodology_page(request):
    return render(request, "explorer/nencioli/methodology.html")


def nencioli_detection_page(request):
    context = {}

    if request.method == "POST":
        data = request.POST.copy()
        action_error = None
        if "inspect_configuration" in data:
            parts = data["inspect_configuration"].split(",")
            if len(parts) == 2:
                data["a"], data["b"] = parts
                data["detection_mode"] = "single"
                data.pop("candidate_id", None)
            else:
                action_error = "Select a valid parameter configuration."
        if "inspect_candidate" in data:
            data["candidate_id"] = data["inspect_candidate"]
        form = NencioliDetectionForm(data)
        valid = form.is_valid()
        if action_error:
            form.add_error(None, action_error)

        if valid and not action_error:
            day = form.cleaned_data["day"]
            try:
                sla_day = load_sla_day(day)
                u, v = load_velocity_field(day)
            except (KeyError, ValueError):
                form.add_error(
                    "day",
                    "No unique daily SLA field is available for this date.",
                )
            else:
                mode = form.cleaned_data["detection_mode"]
                lon = sla_day["longitude"].values
                lat = sla_day["latitude"].values
                sla = sla_day.transpose("latitude", "longitude").values

                if mode == "single":
                    a = form.cleaned_data["a"]
                    b = form.cleaned_data["b"]
                    results, diagnostics = detect_eddies(
                        u=u.values,
                        v=v.values,
                        latitude=lat,
                        longitude=lon,
                        a=a,
                        b=b,
                        return_diagnostics=True,
                    )
                    context.update(
                        prepare_diagnostics(
                            diagnostics, results, lat, lon, u.values, v.values
                        )
                    )
                    context["run_settings"] = {"day": day, "a": a, "b": b}
                    context["grid_comparison"] = grid_comparison(lat, lon, a, b)
                    reference_results, reference_diagnostics = (
                        (results, diagnostics)
                        if (a, b) == (4, 3)
                        else detect_eddies(
                            u.values,
                            v.values,
                            lat,
                            lon,
                            4,
                            3,
                            return_diagnostics=True,
                        )
                    )
                    context["paper_settings"] = {
                        "centers": len(reference_diagnostics["centers"]),
                        "boundaries": len(reference_results),
                    }
                    eddies = [
                        (center_i, center_j, direction, contour)
                        for center_i, center_j, direction, contour, *_ in results
                    ]
                    plotter = NencioliPlotter()
                    context["plot_image"] = plotter.to_base64(
                        plotter.velocity_field(
                            lon, lat, u.values, v.values, sla=sla, a=a, eddies=eddies
                        )
                    )
                    context["plot_image_html"] = (
                        InteractiveNencioliPlotter()
                        .detection(
                            lon,
                            lat,
                            sla,
                            u.values,
                            v.values,
                            context["diagnostics"],
                        )
                        .to_html(
                            full_html=False,
                            include_plotlyjs=True,
                            div_id="nencioli-map",
                            config={"responsive": True, "scrollZoom": False},
                        )
                    )
                    context["diagnostics_plot"] = plotter.to_base64(
                        plotter.diagnostics(
                            lon,
                            lat,
                            u.values,
                            v.values,
                            sla,
                            a,
                            eddies,
                            context["diagnostics"],
                        )
                    )
                    export_fields = (
                        "id",
                        "status",
                        "reason_label",
                        "latitude",
                        "longitude",
                        "rotation",
                        "speed",
                        "radius_km",
                        "source_label",
                        "land_limited",
                        "boundary_limited",
                    )
                    context["candidate_export"] = [
                        {key: row.get(key) for key in export_fields}
                        for row in context["diagnostics"]
                    ]
                    candidate_id = form.cleaned_data.get("candidate_id")
                    if candidate_id is not None:
                        selected = next(
                            (
                                row
                                for row in context["diagnostics"]
                                if row["id"] == candidate_id
                            ),
                            None,
                        )
                        if selected is None:
                            form.add_error(
                                "candidate_id",
                                "This ID does not exist for the current date and parameter settings.",
                            )
                        else:
                            context["selected_candidate"] = selected
                            context["perimeter_evidence"] = perimeter_evidence(
                                lat, lon, u.values, v.values, a, b, selected
                            )
                            context["candidate_image"] = plotter.to_base64(
                                plotter.candidate(
                                    lon, lat, u.values, v.values, a, b, selected
                                )
                            )
                            boundary_figure = plotter.boundary(
                                lon, lat, u.values, v.values, a, selected
                            )
                            if boundary_figure is not None:
                                context["boundary_image"] = plotter.to_base64(
                                    boundary_figure
                                )
                else:
                    a_range = range(
                        form.cleaned_data["a_min"], form.cleaned_data["a_max"] + 1
                    )
                    b_range = range(
                        form.cleaned_data["b_min"], form.cleaned_data["b_max"] + 1
                    )
                    center_detector = NencioliCenterDetector(
                        latitude=lat,
                        longitude=lon,
                        u=u.values,
                        v=v.values,
                        a=None,
                        b=None,
                        a_range=a_range,
                        b_range=b_range,
                    )

                    summary_df, detections_df = center_detector.sweep_parameters()
                    sweep_parameter_heatmap = (
                        InteractiveNencioliPlotter().parameter_sensitivity_heatmap(
                            summary_df=summary_df
                        )
                    )
                    context["sweep_parameter_heatmap_html"] = (
                        sweep_parameter_heatmap.to_html(
                            full_html=False,
                            include_plotlyjs=True,
                            div_id="nencioli-sweep",
                            config={"responsive": True},
                        )
                    )
                    context["sweep_rows"] = summary_df.to_dict("records")
                    context["sweep_day"] = day
                    context["sweep_export"] = context["sweep_rows"]
    else:
        form = NencioliDetectionForm()

    return render(
        request,
        "explorer/nencioli/index.html",
        {"form": form, **context},
    )


def nencioli_tracking_page(request):
    import logging
    from .forms import NencioliTrackingForm
    from .tracking import run_tracking
    from .plots.tracking import NencioliTrackingPlotter

    form = NencioliTrackingForm(request.POST if request.method == "POST" else None)
    context = {}
    if request.method == "POST" and form.is_valid():
        try:
            result = run_tracking(form.cleaned_data)
            map_html = (
                NencioliTrackingPlotter()
                .trajectories(result["tracks"], result["dataset_grid"])
                .to_html(
                    full_html=False,
                    include_plotlyjs=True,
                    div_id="tracking-map",
                    config={"responsive": True, "scrollZoom": False},
                )
            )
            context = {
                **result,
                "ran": True,
                "run_settings": form.cleaned_data,
                "map_html": map_html,
            }
        except (OSError, KeyError, ValueError, RuntimeError, IndexError) as exc:
            form.add_error(None, f"Cannot run tracking: {exc}")
        except Exception:
            logging.getLogger(__name__).exception("Nencioli tracking failed")
            form.add_error(
                None,
                "Tracking could not be completed. Please try a shorter duration or another date.",
            )
    return render(request, "explorer/nencioli/tracking.html", {"form": form, **context})


# Halo methodology, daily detection, and tracking.
def halo_methodology_page(request):
    return render(request, "explorer/halo/methodology.html")


def halo_page(request):
    from .forms import HaloDetectionForm
    from eddy_detection.halo_method import HaloDetector
    from .plots.halo import InteractiveHaloPlotter

    context = {}
    data = request.POST.copy() if request.method == "POST" else None
    if data is not None and "inspect_candidate" in data:
        data["candidate_id"] = data["inspect_candidate"]
    form = HaloDetectionForm(data)
    if data is not None and form.is_valid():
        day = form.cleaned_data["day"]
        try:
            height = load_sla_day(day)
            u, v = load_velocity_field(day)
            # Align explicitly: shape equality alone does not establish grid identity.
            import xarray as xr

            height, u, v = xr.align(height, u, v, join="exact")
            detector = HaloDetector(
                height.transpose("latitude", "longitude").values,
                height.latitude.values,
                height.longitude.values,
                u.transpose("latitude", "longitude").values,
                v.transpose("latitude", "longitude").values,
                contour_interval=form.cleaned_data["contour_interval_cm"] / 100.0,
                max_diameter_km=form.cleaned_data["max_diameter_km"],
                filter_passes=form.cleaned_data["filter_passes"],
            )
            results, diagnostics = detector.detect_eddies(return_diagnostics=True)
        except (KeyError, ValueError) as exc:
            form.add_error(None, f"Cannot analyse this daily grid: {exc}")
        else:
            from .halo_diagnostics import prepare_candidates

            candidates, summary = prepare_candidates(
                diagnostics["candidates"], detector
            )
            diagnostics["candidates"] = candidates
            selected_id = form.cleaned_data.get("candidate_id")
            selected = next((c for c in candidates if c["id"] == selected_id), None)
            if selected_id is not None and selected is None:
                form.add_error(
                    "candidate_id",
                    "This ID does not exist for the current date and parameter settings.",
                )
            reference = results
            if (
                detector.contour_interval,
                detector.max_diameter_km,
                detector.filter_passes,
            ) != (0.02, 600.0, 2):
                reference = HaloDetector(
                    detector.sla_field,
                    detector.latitude,
                    detector.longitude,
                    detector.u,
                    detector.v,
                ).detect_eddies()
            plotter = HaloPlotter()
            context.update(
                diagnostic_summary=summary,
                diagnostics=candidates,
                core_count=diagnostics["core_count"],
                run_settings={
                    "day": day,
                    "contour_interval_cm": form.cleaned_data["contour_interval_cm"],
                    "max_diameter_km": form.cleaned_data["max_diameter_km"],
                    "filter_passes": form.cleaned_data["filter_passes"],
                },
                accepted_eddies=[c for c in candidates if c["accepted"]],
                selected_candidate=selected,
                paper_comparison={"selected": len(results), "defaults": len(reference)},
                plot_image=plotter.to_base64(plotter.detection(detector, diagnostics)),
                ow_image=plotter.to_base64(plotter.OW_field(detector, diagnostics)),
                regions_image=plotter.to_base64(
                    plotter.rotating_regions(detector, diagnostics)
                ),
                diagnostics_plot=plotter.to_base64(
                    plotter.detection(detector, diagnostics, annotate=True)
                ),
                plot_image_html=InteractiveHaloPlotter()
                .detection(detector, diagnostics, selected)
                .to_html(
                    full_html=False,
                    include_plotlyjs=True,
                    div_id="halo-map",
                    config={"responsive": True, "scrollZoom": False},
                ),
                candidate_export=[
                    {
                        k: c[k]
                        for k in (
                            "id",
                            "status",
                            "reason",
                            "reason_label",
                            "level_cm",
                            "diameter_km",
                            "latitude",
                            "longitude",
                            "area_cells",
                            "region_ids",
                        )
                    }
                    for c in candidates
                ],
            )
            if selected is not None:
                context["candidate_image"] = plotter.to_base64(
                    plotter.detection(detector, diagnostics, selected)
                )

    return render(request, "explorer/halo/index.html", {"form": form, **context})


def halo_tracking_page(request):
    import logging
    from .forms import HaloTrackingForm
    from .halo_tracking import run_halo_tracking
    from .plots.tracking import NencioliTrackingPlotter

    form = HaloTrackingForm(request.POST if request.method == "POST" else None)
    context = {"is_halo": True}
    if request.method == "POST" and form.is_valid():
        try:
            result = run_halo_tracking(form.cleaned_data)
            figure = NencioliTrackingPlotter().trajectories(
                result["tracks"],
                result["dataset_grid"],
                method_label="Halo / Okubo–Weiss",
                vorticity_by_detection=result["vorticity_by_detection"],
            )
            map_html = figure.to_html(
                full_html=False,
                include_plotlyjs=True,
                div_id="tracking-map",
                config={"responsive": True, "scrollZoom": False},
            )
            context.update(
                {
                    **result,
                    "ran": True,
                    "run_settings": form.cleaned_data,
                    "map_html": map_html,
                }
            )
        except (OSError, KeyError, ValueError, RuntimeError, IndexError) as exc:
            form.add_error(None, f"Cannot run tracking: {exc}")
        except Exception:
            logging.getLogger(__name__).exception("Halo tracking failed")
            form.add_error(
                None,
                "Tracking could not be completed. Please try a shorter duration or another date.",
            )
    return render(request, "explorer/halo/tracking.html", {"form": form, **context})


# Cross-method comparison and background tracking jobs.
def comparison_methodology_page(request):
    return render(request, "explorer/comparison/methodology.html")


def comparison_page(request):
    from .forms import ComparisonForm, ComparisonTrackingForm
    from .comparison import run_comparison
    from .plots.comparison import ComparisonPlotter

    if request.method == "GET" and request.GET.get("job"):
        from .comparison_job_views import comparison_job_page

        return comparison_job_page(request)

    tracking_requested = (
        request.method == "POST" and request.POST.get("comparison_mode") == "tracking"
    )
    form_class = ComparisonTrackingForm if tracking_requested else ComparisonForm
    form = form_class(request.POST if request.method == "POST" else None)
    tracking_form = form if tracking_requested else ComparisonTrackingForm()
    context = {"tracking_form": tracking_form, "tracking_requested": tracking_requested}
    if tracking_requested:
        if form.is_valid():
            try:
                from .comparison_jobs import enqueue, ensure_worker, result_url
                from django.http import HttpResponseRedirect

                job = enqueue(form.cleaned_data)
                if job["status"] in ("queued", "running"):
                    ensure_worker()
                return HttpResponseRedirect(
                    result_url(
                        job["id"],
                        form.cleaned_data["min_count"],
                        form.cleaned_data["include_censored"],
                    )
                )
            except OSError:
                logging.getLogger(__name__).exception("Could not enqueue comparison")
                form.add_error(
                    None, "The comparison could not be queued. Please try again."
                )
        return render(
            request, "explorer/comparison/index.html", {"form": form, **context}
        )
    if request.method == "POST" and form.is_valid():
        day = form.cleaned_data["day"]
        try:
            height = load_sla_day(day)
            u, v = load_velocity_field(day)
            result = run_comparison(height, u, v, day, form.cleaned_data)
            plotter = ComparisonPlotter()
            context.update(
                {
                    **result,
                    "ran": True,
                    "run_settings": form.cleaned_data,
                    "map_html": plotter.detection(
                        height, result["detections"], u, v
                    ).to_html(
                        full_html=False,
                        include_plotlyjs=True,
                        div_id="comparison-map",
                        config={"responsive": True, "scrollZoom": True},
                    ),
                    "statistics_html": plotter.statistics(
                        result["detections"], result["summary"]
                    ).to_html(
                        full_html=False,
                        include_plotlyjs=False,
                        div_id="comparison-statistics",
                        config={"responsive": True, "displayModeBar": False},
                    ),
                }
            )
        except (OSError, KeyError, ValueError) as exc:
            form.add_error(None, f"Cannot compare this daily grid: {exc}")
    return render(request, "explorer/comparison/index.html", {"form": form, **context})
