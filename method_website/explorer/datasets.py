from functools import lru_cache

import xarray as xr
from django.conf import settings


@lru_cache(maxsize=1)
def get_available_dates():
    """Map each available date to its NetCDF file."""
    date_files = {}

    paths = sorted(settings.SLA_DATA_DIR.glob("osu_daily_sla_geovel_*_v2.nc"))

    for path in paths:
        with xr.open_dataset(path) as ds:
            dates = ds.time.dt.strftime("%Y-%m-%d").values

            for date in dates:
                date = str(date)

                if date in date_files:
                    raise ValueError(f"Multiple SLA fields found for {date}.")

                date_files[date] = path

    return dict(sorted(date_files.items()))


def get_available_years():
    return sorted({date[:4] for date in get_available_dates()})


def get_dates_for_year(year):
    return [date for date in get_available_dates() if date.startswith(f"{year}-")]
