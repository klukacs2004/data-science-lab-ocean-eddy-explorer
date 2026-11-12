"""Validate installed daily inputs without changing or recomputing them."""

from pathlib import Path

import numpy as np
import xarray as xr
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from explorer.datasets import get_available_dates

VARIABLES = {
    "sea_surface_height_above_sea_level": "m",
    "surface_geostrophic_eastward_sea_water_velocity": "m s-1",
    "surface_geostrophic_northward_sea_water_velocity": "m s-1",
}


class Command(BaseCommand):
    help = "Check NetCDF names, units, grids, and daily date coverage."

    def add_arguments(self, parser):
        parser.add_argument("--allow-empty", action="store_true")

    def handle(self, *args, **options):
        directory = Path(settings.SLA_DATA_DIR)
        paths = sorted(directory.glob("osu_daily_sla_geovel_*_v2.nc"))
        if not paths:
            message = (
                f"No daily NetCDF files found in {directory}. "
                "Copy the decompressed osu_daily_sla_geovel_YYYY_v2.nc files "
                "there, or set SLA_DATA_DIR in method_website/.env. "
                "The documentation pages can still be opened."
            )
            if options["allow_empty"]:
                self.stdout.write(self.style.WARNING(message))
                return
            raise CommandError(message)
        reference = None
        try:
            for path in paths:
                with xr.open_dataset(path) as dataset:
                    for coordinate in ("latitude", "longitude"):
                        values = dataset[coordinate].values
                        if (
                            values.ndim != 1
                            or len(values) < 3
                            or not np.isfinite(values).all()
                            or not (np.diff(values) > 0).all()
                        ):
                            raise ValueError(f"{path.name}: invalid {coordinate}.")
                    grid = tuple(
                        dataset[name].values for name in ("latitude", "longitude")
                    )
                    if reference is None:
                        reference = grid
                    elif not all(np.array_equal(a, b) for a, b in zip(reference, grid)):
                        raise ValueError(f"{path.name}: the spatial grid differs.")
                    for name, units in VARIABLES.items():
                        variable = dataset[name]
                        if set(variable.dims) != {"time", "latitude", "longitude"}:
                            raise ValueError(
                                f"{path.name}: invalid dimensions for {name}."
                            )
                        if variable.attrs.get("units") != units:
                            raise ValueError(
                                f"{path.name}: expected units {units!r} for {name}."
                            )
            get_available_dates.cache_clear()
            dates = get_available_dates()
            if not dates:
                raise ValueError("The installed files contain no dates.")
        except (OSError, KeyError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            self.style.SUCCESS(
                f"{len(paths)} files; {len(dates):,} dates: "
                f"{min(dates)} to {max(dates)}. Data directory: {directory}"
            )
        )
