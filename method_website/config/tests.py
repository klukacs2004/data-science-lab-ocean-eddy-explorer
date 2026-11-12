"""Configuration and launch preparation checks; numerical routines are unchanged."""

import os
from pathlib import Path
import stat
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase

from .environment import env_bool, env_list, env_path, script_prefix
import run as launcher


class EnvironmentTests(SimpleTestCase):
    def test_explicit_boolean_values(self):
        for value in ("1", "true", "yes", "on"):
            with self.subTest(value=value), patch.dict(os.environ, {"FLAG": value}):
                self.assertTrue(env_bool("FLAG"))
        for value in ("0", "false", "no", "off"):
            with self.subTest(value=value), patch.dict(os.environ, {"FLAG": value}):
                self.assertFalse(env_bool("FLAG", True))
        with patch.dict(os.environ, {"FLAG": ""}):
            self.assertTrue(env_bool("FLAG", True))
        with patch.dict(os.environ, {"FLAG": "maybe"}):
            with self.assertRaises(ImproperlyConfigured):
                env_bool("FLAG")

    def test_comma_separated_lists_and_relative_paths(self):
        with patch.dict(
            os.environ, {"HOSTS": " localhost, example.org, ", "DATA": "fields"}
        ):
            self.assertEqual(env_list("HOSTS"), ["localhost", "example.org"])
            self.assertEqual(
                env_path("DATA", "unused", Path("/project")), Path("/project/fields")
            )
        with patch.dict(os.environ, {"DATA": "/shared/fields"}):
            self.assertEqual(
                env_path("DATA", "unused", Path("/project")), Path("/shared/fields")
            )

    def test_empty_or_absolute_paths(self):
        self.assertIsNone(script_prefix(""))
        self.assertIsNone(script_prefix("/"))
        self.assertEqual(script_prefix(" /reports/eddies/ "), "/reports/eddies")
        self.assertEqual(
            script_prefix("/user/alice/proxy/8000"), "/user/alice/proxy/8000"
        )
        for value in (
            "https://example.org/app",
            "//example.org/app",
            "relative",
            "/a/../b",
            "/a?x=1",
            "/a b",
        ):
            with self.subTest(value=value), self.assertRaises(ImproperlyConfigured):
                script_prefix(value)


class LauncherPreparationTests(SimpleTestCase):
    def test_generated_secret_is_private_stable_and_other_settings_survive(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".env.example").write_text("DJANGO_SECRET_KEY=\nPORT=8123\n")
            with patch.object(launcher, "BASE_DIR", root):
                launcher.ensure_environment_file()
                path = root / ".env"
                original = path.read_text()
                self.assertIn("PORT=8123", original)
                self.assertGreater(len(original.splitlines()[0].split("=", 1)[1]), 50)
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
                launcher.ensure_environment_file()
                self.assertEqual(path.read_text(), original)

    def test_existing_user_secret_is_preserved(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            content = "DJANGO_SECRET_KEY=existing-user-secret\nPORT=8124\n"
            (root / ".env").write_text(content)
            with patch.object(launcher, "BASE_DIR", root):
                launcher.ensure_environment_file()
            self.assertEqual((root / ".env").read_text(), content)
