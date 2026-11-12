"""Progress and saved-result views for background tracking comparisons."""

from datetime import timedelta
import logging
import pickle

from django.core.exceptions import ValidationError
from django.http import Http404, JsonResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from . import comparison_jobs as jobs
from .forms import ComparisonTrackingForm


def get_job(job_id):
    try:
        return jobs.read_job(job_id)
    except FileNotFoundError:
        raise Http404("This comparison run does not exist.")


@require_GET
@never_cache
def comparison_job_status(request, job_id):
    job = get_job(job_id)
    if job["status"] in ("queued", "running"):
        jobs.ensure_worker()
    return JsonResponse(jobs.public_state(job))


@never_cache
def comparison_job_page(request):
    job = get_job(request.GET["job"])
    parameters = jobs.decode_parameters(job["parameters"])
    data = {
        **job["parameters"],
        "min_count": request.GET.get("min_count", parameters["min_count"]),
        "include_censored": request.GET.get(
            "include_censored", str(int(parameters["include_censored"]))
        )
        not in ("0", "False", "false", ""),
    }
    # A bound form preserves both original settings and validation feedback.
    form = ComparisonTrackingForm(data)
    form.is_valid()
    try:
        parameters["min_count"] = form.fields["min_count"].clean(data["min_count"])
        parameters["include_censored"] = form.fields["include_censored"].clean(
            data["include_censored"]
        )
    except ValidationError:
        parameters["min_count"] = job["parameters"]["min_count"]
        parameters["include_censored"] = job["parameters"]["include_censored"]
    context = dict(
        form=form,
        tracking_form=form,
        tracking_requested=True,
        comparison_job=job,
        job_pending=job["status"] in ("queued", "running"),
        job_failed=job["status"] == "failed",
    )
    if context["job_pending"]:
        jobs.ensure_worker()
    elif job["status"] == "succeeded":
        from .comparison_tracking import tracking_figures

        try:
            f7, f8, summaries = tracking_figures(
                jobs.load_results(job["id"]),
                parameters["day"],
                parameters["duration_days"],
                parameters["min_count"],
                parameters["include_censored"],
            )
            context.update(
                tracking_ran=True,
                tracking_settings=parameters,
                tracking_end=parameters["day"]
                + timedelta(days=parameters["duration_days"] - 1),
                tracking_summaries=summaries,
                figure7_html=f7.to_html(
                    full_html=False,
                    include_plotlyjs=True,
                    div_id="comparison-figure7",
                    config={"responsive": True},
                ),
                figure8_html=f8.to_html(
                    full_html=False,
                    include_plotlyjs=False,
                    div_id="comparison-figure8",
                    config={"responsive": True},
                ),
            )
        except (OSError, ValueError, EOFError, pickle.UnpicklingError):
            logging.getLogger(__name__).exception(
                "Could not load comparison result %s", job["id"]
            )
            job.update(
                status="failed",
                message="The saved result is unavailable. Please retry the comparison.",
            )
            jobs.write_job(job)
            context["job_failed"] = True
            form.add_error(None, job["message"])
    return render(request, "explorer/comparison/index.html", context)
