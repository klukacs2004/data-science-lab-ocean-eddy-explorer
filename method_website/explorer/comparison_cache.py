"""Private on-disk checkpoints, invalidated by data, settings, and source changes."""

import hashlib
import json
import os
from pathlib import Path
import pickle
import tempfile

from django.conf import settings


def storage_root():
    root = Path(
        getattr(
            settings,
            "COMPARISON_WORK_DIR",
            settings.BASE_DIR.parent / "artifacts/comparison_work",
        )
    )
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    return root


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, default=str).encode()
    ).hexdigest()


def source_version():
    root = Path(__file__).resolve().parent
    files = [
        *root.glob("*tracking*.py"),
        root / "comparison_cache.py",
        root / "chelton_diagnostics.py",
        root / "methods.py",
        root / "forms.py",
        *(root.parent / "eddy_detection").glob("*.py"),
        *(root.parent / "eddy_tracking").glob("*.py"),
    ]
    return digest(
        [
            (str(p), hashlib.sha256(p.read_bytes()).hexdigest())
            for p in sorted(set(files))
        ]
    )


def input_signature(path):
    path = Path(path)
    stat = path.stat()
    return [str(path.resolve()), stat.st_size, stat.st_mtime_ns]


def atomic_write(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class DailyDetectionCache:
    fields = {
        "chelton": ("filter_mode", "sigma_cells"),
        "nencioli": ("a", "b"),
        "halo": (
            "contour_interval_cm",
            "max_diameter_km",
            "filter_passes",
            "velocity_smoothing_passes",
            "minimum_abs_vorticity_s",
        ),
    }

    def __init__(self, available):
        self.available = available
        self.version = source_version()

    def path(self, method, day, parameters):
        selected = {key: parameters.get(key) for key in self.fields[method]}
        if method == "chelton" and selected["filter_mode"] != "custom":
            selected.pop("sigma_cells")
        key = digest(
            [
                self.version,
                method,
                day,
                selected,
                input_signature(self.available[day.isoformat()]),
            ]
        )
        return storage_root() / "daily" / f"{key}.pickle"

    def load(self, method, day, parameters):
        path = self.path(method, day, parameters)
        try:
            # Only server-created files in the private work directory are read.
            return pickle.loads(path.read_bytes())
        except (FileNotFoundError, EOFError, pickle.UnpicklingError):
            return None

    def save(self, method, day, parameters, payload):
        atomic_write(
            self.path(method, day, parameters),
            pickle.dumps(payload, protocol=pickle.HIGHEST_PROTOCOL),
        )


def restore_grid(current, saved):
    import numpy as np

    if current is not None and not all(
        np.array_equal(current[key], saved[key]) for key in ("latitude", "longitude")
    ):
        raise ValueError("The dataset grid changes within the selected interval.")
    return current if current is not None else saved
