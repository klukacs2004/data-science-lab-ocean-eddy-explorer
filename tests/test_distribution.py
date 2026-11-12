"""Portable bundles must exclude per-machine secrets, environments, and jobs."""

import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "package_method_website",
    Path(__file__).resolve().parents[1] / "scripts/package_method_website.py",
)
package = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(package)


class DistributionTests(unittest.TestCase):
    def test_secrets_databases_caches_and_virtual_environments_are_excluded(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            public = (
                "README.md",
                "method_website/manage.py",
                "method_website/.env.example",
                "method_website/.env.kooplex.example",
            )
            private = (
                "method_website/.env",
                "method_website/db.sqlite3",
                "method_website/.runtime/secret.txt",
                "method_website/.venv/bin/python",
                "method_website/__pycache__/private.pyc",
                "method_website/local-backup.zip",
                "method_website/data/private.nc",
            )
            for name in (*public, *private):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("fixture")
            with patch.object(package, "ROOT", root):
                paths = {
                    p.relative_to(root).as_posix()
                    for p in package.package_files("none")
                }
            self.assertEqual(paths, set(public))

    def test_demo_and_full_data_selection_are_explicit(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            data = root / "data"
            data.mkdir()
            for name in (
                "osu_daily_sla_geovel_1993_v2.nc",
                "osu_daily_sla_geovel_1994_v2.nc",
                "mean_aviso_field_1993_2012_v2.nc",
                "osu_daily_sla_geovel_v2.tar",
            ):
                (data / name).write_text("fixture")
            with patch.object(package, "ROOT", root):
                self.assertEqual(package.package_files("none"), [])
                demo = {p.name for p in package.package_files("demo")}
                full = {p.name for p in package.package_files("all")}
            self.assertEqual(
                demo,
                {
                    "osu_daily_sla_geovel_1993_v2.nc",
                    "mean_aviso_field_1993_2012_v2.nc",
                },
            )
            self.assertEqual(full, demo | {"osu_daily_sla_geovel_1994_v2.nc"})


if __name__ == "__main__":
    unittest.main()
