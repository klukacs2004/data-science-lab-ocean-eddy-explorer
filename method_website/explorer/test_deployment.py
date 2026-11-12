"""Root and prefixed hosting, production static files, and proxied form posts."""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.conf import settings
from django.core.management import call_command
from django.test import Client, SimpleTestCase, override_settings
from django.urls import get_script_prefix, reverse, set_script_prefix


@override_settings(
    DEBUG=False,
    ALLOWED_HOSTS=["testserver", "kooplex.test"],
    CSRF_TRUSTED_ORIGINS=["https://kooplex.test"],
    SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO", "https"),
)
class DeploymentTests(SimpleTestCase):
    def setUp(self):
        self.prefix = get_script_prefix()
        self.addCleanup(set_script_prefix, self.prefix)

    def test_health_works_without_netcdf_inputs(self):
        response = self.client.get(reverse("health"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_prefix_is_preserved_in_navigation_and_browser_api_urls(self):
        prefix = "/reports/eddies"
        with (
            override_settings(FORCE_SCRIPT_NAME=prefix, STATIC_URL=f"{prefix}/static/"),
            patch("explorer.forms.get_available_years", return_value=[]),
            patch("explorer.forms.get_dates_for_year", return_value=[]),
        ):
            set_script_prefix(prefix)
            response = self.client.get("/explorer/compare")
            self.assertEqual(response.status_code, 200)
            self.assertContains(
                response, f'href="{prefix}/methods/comparison/methodology/"'
            )
            self.assertContains(response, f"{prefix}/static/explorer/style.css")
            self.assertContains(response, f"{prefix}/explorer/available-dates/")

    def test_proxied_https_post_passes_csrf_and_foreign_origin_does_not(self):
        with (
            patch("explorer.forms.get_available_years", return_value=[]),
            patch("explorer.forms.get_dates_for_year", return_value=[]),
        ):
            client = Client(enforce_csrf_checks=True)
            headers = {"HTTP_HOST": "kooplex.test", "HTTP_X_FORWARDED_PROTO": "https"}
            response = client.get("/explorer/compare", **headers)
            self.assertEqual(response.status_code, 200)
            token = client.cookies[settings.CSRF_COOKIE_NAME].value
            data = {"csrfmiddlewaretoken": token}
            response = client.post(
                "/explorer/compare", data, HTTP_ORIGIN="https://kooplex.test", **headers
            )
            self.assertEqual(response.status_code, 200)
            rejected = client.post(
                "/explorer/compare",
                data,
                HTTP_ORIGIN="https://unrelated.test",
                **headers,
            )
            self.assertEqual(rejected.status_code, 403)

    def test_unknown_host_is_rejected(self):
        response = self.client.get("/health/", HTTP_HOST="unrelated.test")
        self.assertEqual(response.status_code, 400)

    def test_collected_css_is_served_with_debug_disabled(self):
        with (
            TemporaryDirectory() as directory,
            override_settings(STATIC_ROOT=Path(directory)),
        ):
            call_command("collectstatic", interactive=False, verbosity=0)
            response = Client().get("/static/explorer/style.css")
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response["Content-Type"].startswith("text/css"))
            content = b"".join(response.streaming_content)
            response.close()
            self.assertIn(b".methodology", content)
