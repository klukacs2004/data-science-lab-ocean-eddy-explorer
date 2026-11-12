import xarray as xr
from .datasets import get_available_dates


def load_sla_day(day):
    date = day.isoformat()
    path = get_available_dates().get(date)

    if path is None:
        raise ValueError("No data available for this date.")

    with xr.open_dataset(path) as ds:
        selected = ds["sea_surface_height_above_sea_level"].sel(time=date)

        if selected.sizes.get("time", 0) != 1:
            raise ValueError("Expected exactly one SLA field for this date.")

        sla_day = selected.isel(time=0).load()

    return sla_day.transpose("longitude", "latitude")


def load_velocity_field(day):
    date = day.isoformat()
    path = get_available_dates().get(date)

    if path is None:
        raise ValueError("No data available for this date.")

    with xr.open_dataset(path) as ds:
        u = ds["surface_geostrophic_eastward_sea_water_velocity"].sel(time=date)
        v = ds["surface_geostrophic_northward_sea_water_velocity"].sel(time=date)

        u_day = u.isel(time=0).transpose("latitude", "longitude").load()
        v_day = v.isel(time=0).transpose("latitude", "longitude").load()

    return (u_day, v_day)


def load_reference_mean():
    """Load the supplied 1993–2012 AVISO mean SLA field without altering it."""
    from django.conf import settings

    with xr.open_dataset(
        settings.SLA_DATA_DIR / "mean_aviso_field_1993_2012_v2.nc"
    ) as ds:
        field = ds["sea_surface_height_above_sea_level"].load()
    if field.attrs.get("units") != "m":
        raise ValueError("Expected reference mean sea level in metres.")
    return field.transpose("longitude", "latitude")
