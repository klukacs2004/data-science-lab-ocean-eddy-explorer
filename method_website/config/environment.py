"""Small, explicit parsers for deployment settings."""

import os
from pathlib import Path
from urllib.parse import urlsplit

from django.core.exceptions import ImproperlyConfigured


def env_bool(name, default=False):
    value = os.environ.get(name, "").strip().lower()
    if not value:
        return default
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise ImproperlyConfigured(f"{name} must be true or false.")


def env_list(name, default=()):
    value = os.environ.get(name)
    if value is None:
        return list(default)
    return [item.strip() for item in value.split(",") if item.strip()]


def env_path(name, default, base_dir):
    value = os.environ.get(name, "").strip()
    path = Path(value).expanduser() if value else Path(default)
    return path if path.is_absolute() else base_dir / path


def script_prefix(value):
    value = value.strip()
    if not value or value == "/":
        return None
    if (
        not value.startswith("/")
        or value.startswith("//")
        or urlsplit(value).scheme
        or urlsplit(value).netloc
        or "?" in value
        or "#" in value
        or "\\" in value
        or any(character.isspace() for character in value)
        or any(part in {".", ".."} for part in value.split("/"))
    ):
        raise ImproperlyConfigured(
            "DJANGO_FORCE_SCRIPT_NAME must be a URL path, such as /reports/eddies."
        )
    return value.rstrip("/")
