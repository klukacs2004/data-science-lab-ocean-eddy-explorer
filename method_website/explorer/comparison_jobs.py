"""Durable single-host queue. Scientific work never runs in an HTTP request."""

from contextlib import contextmanager
from datetime import date, timedelta
import fcntl
import json
import logging
import os
from pathlib import Path
import pickle
import re
import subprocess
import sys
import time
from types import SimpleNamespace
import uuid

from django.conf import settings
from django.urls import reverse

from .comparison_cache import (
    atomic_write,
    digest,
    input_signature,
    source_version,
    storage_root,
)

DISPLAY_FIELDS = {"year", "min_count", "include_censored"}


@contextmanager
def lock(name, *, blocking=True):
    with (storage_root() / name).open("a") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def job_path(job_id):
    if not re.fullmatch(r"[0-9a-f]{32}", job_id):
        raise FileNotFoundError("Unknown comparison run")
    return storage_root() / "jobs" / job_id


def read_job(job_id):
    return json.loads((job_path(job_id) / "state.json").read_text())


def write_job(job):
    job["updated_at"] = time.time()
    atomic_write(job_path(job["id"]) / "state.json", json.dumps(job).encode())


def decode_parameters(parameters):
    return {**parameters, "day": date.fromisoformat(parameters["day"])}


def enqueue(parameters):
    from .datasets import get_available_dates

    available = get_available_dates()
    start, duration = parameters["day"], parameters["duration_days"]
    files = {
        available[(start + timedelta(days=i)).isoformat()] for i in range(duration)
    }
    computation = {
        key: value for key, value in parameters.items() if key not in DISPLAY_FIELDS
    }
    if computation["filter_mode"] != "custom":
        computation["sigma_cells"] = None
    key = digest(
        [source_version(), computation, sorted(input_signature(p) for p in files)]
    )
    index = storage_root() / "index" / f"{key}.json"
    with lock("queue.lock"):
        if index.exists():
            existing = read_job(json.loads(index.read_text())["id"])
            if existing["status"] in ("queued", "running", "succeeded"):
                return existing
        job = dict(
            id=uuid.uuid4().hex,
            status="queued",
            message="Waiting for the comparison worker.",
            completed=0,
            total=3 * (duration + 1),
            cache_hits=0,
            created_at=time.time(),
            parameters=json.loads(json.dumps(parameters, default=str)),
        )
        write_job(job)
        atomic_write(index, json.dumps({"id": job["id"]}).encode())
    return job


def ensure_worker():
    if not getattr(settings, "COMPARISON_AUTOSTART", True):
        return
    # Multiple requests may race to launch; the worker lock admits only one.
    with lock("worker.lock", blocking=False) as idle:
        if not idle:
            return
        with (storage_root() / "worker.log").open("ab") as output:
            subprocess.Popen(
                [
                    sys.executable,
                    str(settings.BASE_DIR / "manage.py"),
                    "runcomparisonjobs",
                    "--work-dir",
                    str(storage_root().resolve()),
                ],
                cwd=settings.BASE_DIR,
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=output,
                start_new_session=True,
                close_fds=True,
            )


def public_state(job):
    return {
        key: job[key]
        for key in (
            "id",
            "status",
            "message",
            "completed",
            "total",
            "cache_hits",
            "updated_at",
        )
    }


def result_url(job_id, min_count, include_censored):
    return (
        f"{reverse('comparison')}?job={job_id}&min_count={min_count}"
        f"&include_censored={int(bool(include_censored))}"
    )


def compact_results(results):
    """Keep only the observations needed by the two comparison figures."""
    return [
        {
            "tracks": [
                SimpleNamespace(
                    id=t.id,
                    start_date=t.start_date,
                    end_date=t.end_date,
                    detections=[
                        SimpleNamespace(
                            date=e.date,
                            radius_km=e.radius_km,
                            has_reliable_radius=e.has_reliable_radius,
                        )
                        for e in t.detections
                    ],
                )
                for t in result["tracks"]
            ],
            "missing_days": result["missing_days"],
            "comparison_parameters": result.get("comparison_parameters", []),
        }
        for result in results
    ]


def load_results(job_id):
    # The result is created exclusively by our worker in the private directory.
    return pickle.loads((job_path(job_id) / "results.pickle").read_bytes())


def run_job(job):
    from .comparison_cache import DailyDetectionCache
    from .comparison_tracking import run_tracking_comparison
    from .datasets import get_available_dates

    parameters = decode_parameters(job["parameters"])
    labels = ("Chelton", "Nencioli", "Halo")
    duration = parameters["duration_days"]
    job.update(
        status="running", message="Preparing daily data.", completed=0, cache_hits=0
    )
    write_job(job)

    def progress(method, phase, completed, cached):
        done = method * (duration + 1) + completed
        if phase == "association":
            message = f"{labels[method]}: linking tracks over {duration} days."
        else:
            message = f"{labels[method]}: {completed}/{duration} days processed."
        job.update(
            completed=done, message=message, cache_hits=job["cache_hits"] + int(cached)
        )
        write_job(job)

    try:
        results = run_tracking_comparison(
            parameters,
            progress=progress,
            daily_cache=DailyDetectionCache(get_available_dates()),
        )
        atomic_write(
            job_path(job["id"]) / "results.pickle",
            pickle.dumps(compact_results(results), protocol=pickle.HIGHEST_PROTOCOL),
        )
        job.update(
            status="succeeded", message="Comparison ready.", completed=job["total"]
        )
    except Exception:
        logging.getLogger(__name__).exception("Comparison job %s failed", job["id"])
        job.update(
            status="failed",
            message="The comparison could not be completed. Retry the run; completed daily detections will be reused.",
        )
    write_job(job)


def work_queue():
    with lock("worker.lock", blocking=False) as acquired:
        if not acquired:
            return
        # A running entry with no worker lock belonged to an interrupted worker.
        # Daily checkpoints make restarting safe without changing association rules.
        while True:
            with lock("queue.lock"):
                jobs = [
                    json.loads(path.read_text())
                    for path in (storage_root() / "jobs").glob("*/state.json")
                ]
                waiting = sorted(
                    (job for job in jobs if job["status"] in ("queued", "running")),
                    key=lambda job: job["created_at"],
                )
                if not waiting:
                    return
                job = waiting[0]
                job.update(status="running", message="Starting comparison.")
                write_job(job)
            run_job(job)
