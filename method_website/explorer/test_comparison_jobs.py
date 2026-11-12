"""Persistent jobs, scientific cache boundaries, and nonblocking HTTP behavior."""

from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings
from django.urls import reverse

from . import comparison_jobs as jobs
from .comparison_cache import DailyDetectionCache


class ComparisonJobTests(SimpleTestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.override = override_settings(
            COMPARISON_WORK_DIR=Path(self.directory.name) / "work",
            COMPARISON_AUTOSTART=False,
        )
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.source = Path(self.directory.name) / "source.nc"
        self.source.write_bytes(b"dataset")
        self.available = {
            (date(2000, 1, 1) + timedelta(days=i)).isoformat(): self.source
            for i in range(20)
        }
        self.dates_patch = patch(
            "explorer.datasets.get_available_dates", return_value=self.available
        )
        self.dates_patch.start()
        self.addCleanup(self.dates_patch.stop)
        self.parameters = dict(
            day=date(2000, 1, 1),
            year="2000",
            duration_days=10,
            min_count=20,
            include_censored=False,
            filter_mode="none",
            sigma_cells=None,
            a=2,
            b=2,
            contour_interval_cm=2.0,
            max_diameter_km=600.0,
            filter_passes=2,
        )

    def test_duplicate_requests_share_job_and_display_options_do_not_recompute(self):
        first = jobs.enqueue(self.parameters)
        again = jobs.enqueue(
            {
                **self.parameters,
                "min_count": 1,
                "include_censored": True,
                "sigma_cells": 10,
            }
        )
        self.assertEqual(first["id"], again["id"])
        self.assertNotEqual(
            first["id"], jobs.enqueue({**self.parameters, "duration_days": 11})["id"]
        )
        self.assertNotEqual(
            first["id"], jobs.enqueue({**self.parameters, "a": 4})["id"]
        )
        self.source.write_bytes(b"changed dataset")
        self.assertNotEqual(first["id"], jobs.enqueue(self.parameters)["id"])

    def test_cache_invalidates_detector_settings_data_and_preserves_day_reuse(self):
        cache = DailyDetectionCache(self.available)
        start = self.parameters["day"]
        cached = {"grid": {}, "detections": []}
        cache.save("nencioli", start, self.parameters, cached)
        self.assertEqual(
            cache.load(
                "nencioli",
                start,
                {**self.parameters, "duration_days": 365, "min_count": 1},
            ),
            cached,
        )
        self.assertIsNone(cache.load("nencioli", start, {**self.parameters, "a": 4}))
        self.assertIsNone(
            cache.load("nencioli", start + timedelta(days=1), self.parameters)
        )
        cache.version = "new-source-version"
        self.assertIsNone(cache.load("nencioli", start, self.parameters))
        cache.version = DailyDetectionCache(self.available).version
        self.source.write_bytes(b"changed input")
        self.assertIsNone(cache.load("nencioli", start, self.parameters))

    def test_worker_progress_persists_results_and_does_not_repeat_success(self):
        job = jobs.enqueue(self.parameters)

        def science(parameters, *, progress, daily_cache):
            progress(0, "detection", 3, True)
            state = jobs.read_job(job["id"])
            self.assertEqual(state["completed"], 3)
            self.assertEqual(state["cache_hits"], 1)
            self.assertIn("3/10", state["message"])
            return [{"tracks": [], "missing_days": []} for _ in range(3)]

        with patch(
            "explorer.comparison_tracking.run_tracking_comparison", side_effect=science
        ) as runner:
            jobs.work_queue()
            jobs.work_queue()
            runner.assert_called_once()
        saved = jobs.read_job(job["id"])
        self.assertEqual(saved["status"], "succeeded")
        self.assertEqual(saved["completed"], saved["total"])
        self.assertEqual(len(jobs.load_results(job["id"])), 3)
        self.assertEqual(jobs.enqueue(self.parameters)["id"], job["id"])

    def test_worker_lock_prevents_duplicates_and_recovers_interrupted_job(self):
        job = jobs.enqueue(self.parameters)
        with (
            jobs.lock("worker.lock"),
            patch("explorer.comparison_tracking.run_tracking_comparison") as runner,
        ):
            jobs.work_queue()
            runner.assert_not_called()
        job.update(status="running", completed=4)
        jobs.write_job(job)
        with patch(
            "explorer.comparison_tracking.run_tracking_comparison",
            return_value=[{"tracks": [], "missing_days": []}] * 3,
        ):
            jobs.work_queue()
        self.assertEqual(jobs.read_job(job["id"])["status"], "succeeded")

    def test_failed_job_is_visible_and_can_be_retried(self):
        job = jobs.enqueue(self.parameters)
        with (
            patch(
                "explorer.comparison_tracking.run_tracking_comparison",
                side_effect=ValueError("bad input"),
            ),
            self.assertLogs("explorer.comparison_jobs", level="ERROR"),
        ):
            jobs.work_queue()
        self.assertEqual(jobs.read_job(job["id"])["status"], "failed")
        self.assertNotEqual(jobs.enqueue(self.parameters)["id"], job["id"])

    def test_progress_endpoint_and_pending_page_survive_reload(self):
        job = jobs.enqueue(self.parameters)
        url = jobs.result_url(job["id"], 1, False)
        with (
            patch("explorer.forms.get_available_years", return_value=["2000"]),
            patch(
                "explorer.forms.get_dates_for_year", return_value=list(self.available)
            ),
            patch("explorer.comparison_tracking.run_tracking_comparison") as science,
        ):
            for _ in range(2):
                response = self.client.get(url)
                self.assertContains(response, "comparison-job-progress")
                self.assertContains(response, "Tracking comparison in progress")
                self.assertNotContains(
                    response, "One period, three tracking methods</h2>"
                )
            science.assert_not_called()
        response = self.client.get(reverse("comparison_job_status", args=[job["id"]]))
        self.assertEqual(response.json()["status"], "queued")
        self.assertIn("no-store", response["Cache-Control"])
        self.assertNotIn("parameters", response.json())
        self.assertEqual(
            self.client.get(
                reverse("comparison_job_status", args=["unknown"])
            ).status_code,
            404,
        )

    def test_completed_results_replot_without_science_and_checkbox_matches_url(self):
        job = jobs.enqueue(self.parameters)
        with patch(
            "explorer.comparison_tracking.run_tracking_comparison",
            return_value=[{"tracks": [], "missing_days": []}] * 3,
        ):
            jobs.work_queue()
        with (
            patch("explorer.forms.get_available_years", return_value=["2000"]),
            patch(
                "explorer.forms.get_dates_for_year", return_value=list(self.available)
            ),
            patch("explorer.comparison_tracking.run_tracking_comparison") as science,
        ):
            response = self.client.get(jobs.result_url(job["id"], 1, False))
            self.assertContains(response, "comparison-figure7")
            self.assertContains(response, "comparison-figure8")
            self.assertFalse(response.context["tracking_settings"]["include_censored"])
            self.assertNotIn(
                "checked", str(response.context["form"]["include_censored"])
            )
            response = self.client.get(jobs.result_url(job["id"], 3, True))
            self.assertEqual(response.context["tracking_settings"]["min_count"], 3)
            self.assertTrue(response.context["tracking_settings"]["include_censored"])
            science.assert_not_called()

    def test_concurrent_requests_create_one_job(self):
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=5) as pool:
            ids = list(
                pool.map(lambda _: jobs.enqueue(self.parameters)["id"], range(10))
            )
        self.assertEqual(len(set(ids)), 1)

    def test_missing_result_is_marked_failed_for_retry(self):
        job = jobs.enqueue(self.parameters)
        job["status"] = "succeeded"
        jobs.write_job(job)
        with (
            patch("explorer.forms.get_available_years", return_value=["2000"]),
            patch(
                "explorer.forms.get_dates_for_year", return_value=list(self.available)
            ),
            self.assertLogs("explorer.comparison_job_views", level="ERROR"),
        ):
            response = self.client.get(jobs.result_url(job["id"], 1, False))
        self.assertContains(response, "The saved result is unavailable")
        self.assertEqual(jobs.read_job(job["id"])["status"], "failed")
        self.assertNotEqual(jobs.enqueue(self.parameters)["id"], job["id"])
