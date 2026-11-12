from copy import deepcopy

from django import forms

from .datasets import get_available_years, get_dates_for_year


# Shared dataset and date selection.
class DataForm(forms.Form):
    year = forms.ChoiceField(
        label="Year",
        choices=[],
    )

    day = forms.DateField(
        label="Available date",
        widget=forms.Select(),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        years = get_available_years()
        year_field = self.fields["year"]

        if isinstance(year_field, forms.ChoiceField):
            year_field.choices = [(year, year) for year in years]

        selected_year = (
            self.data.get("year")
            if self.is_bound
            else self.initial.get("year", years[0] if years else "")
        )

        self.fields["year"].initial = selected_year

        dates = get_dates_for_year(selected_year)

        self.fields["day"].widget.choices = [(date, date) for date in dates]

        if not self.is_bound and dates:
            self.fields["day"].initial = dates[0]

    def clean(self):
        cleaned = super().clean()

        year = cleaned.get("year")
        day = cleaned.get("day")

        if year and day:
            if day.isoformat() not in get_dates_for_year(year):
                self.add_error(
                    "day",
                    "Select an available date for this year.",
                )

        return cleaned


# Parameters for the individual daily detection explorers.
class CheltonDetectionForm(DataForm):

    filter_mode = forms.ChoiceField(
        label="Background removal",
        choices=[
            ("custom", "Gaussian · custom scale"),
            ("paper_scale", "Gaussian · paper cutoff scales (approximation)"),
            ("none", "No additional filtering"),
        ],
        initial="custom",
    )

    detection_mode = forms.ChoiceField(
        label="Detection mode",
        choices=[
            ("single", "Single threshold"),
            ("scan", "Full threshold scan"),
        ],
        initial="single",
    )

    sigma_cells = forms.FloatField(
        label="Gaussian smoothing scale σ [grid cells]",
        initial=4.0,
        min_value=0.5,
        max_value=20.0,
        required=False,
        widget=forms.NumberInput(attrs={"step": "0.5"}),
        help_text=(
            "Gaussian standard deviation, applied along both grid axes. "
            "Larger values produce a smoother background."
        ),
    )

    threshold_cm = forms.FloatField(
        label="SLA threshold [cm]",
        initial=5.0,
        min_value=-100.0,
        max_value=100.0,
        required=False,
    )

    polarity = forms.ChoiceField(
        label="Eddy polarity",
        choices=[("maximum", "SLA maximum"), ("minimum", "SLA minimum")],
        initial="maximum",
        required=False,
    )

    candidate_id = forms.IntegerField(
        label="Candidate ID to inspect",
        required=False,
        min_value=1,
        widget=forms.NumberInput(attrs={"form": "analysis-form"}),
        help_text=(
            "Optional. Run detection first, then enter an ID "
            "from the candidate diagnostics table."
        ),
    )

    def clean(self):
        cleaned = super().clean()

        if (
            cleaned.get("filter_mode") == "custom"
            and cleaned.get("sigma_cells") is None
            and "sigma_cells" not in (self.errors or {})
        ):
            self.add_error(
                "sigma_cells", "Enter a Gaussian scale for custom filtering."
            )

        if cleaned.get("detection_mode") == "single":
            if cleaned.get("threshold_cm") is None:
                self.add_error(
                    "threshold_cm",
                    "Enter a threshold for single-threshold detection.",
                )

            if not cleaned.get("polarity"):
                self.add_error(
                    "polarity",
                    "Select a polarity for single-threshold detection.",
                )
        return cleaned


class NencioliDetectionForm(DataForm):
    detection_mode = forms.ChoiceField(
        label="Detection mode",
        choices=[
            ("single", "Single parameter configuration"),
            ("sweep", "Parameter sweep"),
        ],
        initial="single",
    )

    a = forms.IntegerField(
        label="Velocity search radius (a) [grid cells]",
        initial=4,
        min_value=2,
        max_value=10,
        required=False,
    )

    b = forms.IntegerField(
        label="Minimum search radius (b) [grid cells]",
        initial=3,
        min_value=1,
        max_value=10,
        required=False,
    )

    a_min = forms.IntegerField(
        label="Minimum a",
        initial=2,
        min_value=2,
        max_value=9,
        required=False,
    )

    a_max = forms.IntegerField(
        label="Maximum a",
        initial=4,
        min_value=2,
        max_value=10,
        required=False,
    )

    b_min = forms.IntegerField(
        label="Minimum b",
        initial=1,
        min_value=1,
        max_value=9,
        required=False,
    )

    b_max = forms.IntegerField(
        label="Maximum b",
        initial=4,
        min_value=1,
        max_value=10,
        required=False,
    )

    candidate_id = forms.IntegerField(
        label="Candidate ID to inspect",
        min_value=1,
        required=False,
        widget=forms.NumberInput(attrs={"form": "analysis-form"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned_data = super().clean()

        mode = cleaned_data.get("detection_mode")
        required_fields = (
            ("a", "b") if mode == "single" else ("a_min", "a_max", "b_min", "b_max")
        )
        for name in required_fields:
            if cleaned_data.get(name) is None and name not in (self.errors or {}):
                self.add_error(name, "Enter a value for this detection mode.")
        if mode != "sweep":
            return cleaned_data

        a_min = cleaned_data.get("a_min")
        a_max = cleaned_data.get("a_max")
        b_min = cleaned_data.get("b_min")
        b_max = cleaned_data.get("b_max")

        if a_min is not None and a_max is not None:
            if a_max < a_min:
                self.add_error("a_max", "Maximum a must be at least the minimum a.")

        if b_min is not None and b_max is not None:
            if b_min > b_max:
                self.add_error("b_max", "Maximum b must be at least the minimum b.")

        return cleaned_data


class HaloDetectionForm(DataForm):
    contour_interval_cm = forms.FloatField(
        label="Contour interval [cm]", initial=2, min_value=0.5, max_value=20
    )
    max_diameter_km = forms.FloatField(
        label="Maximum loop diameter [km]", initial=600, min_value=10, max_value=1000
    )
    filter_passes = forms.IntegerField(
        label="Hanning passes on W", initial=2, min_value=0, max_value=6
    )
    candidate_id = forms.IntegerField(
        label="Candidate ID to inspect",
        min_value=1,
        required=False,
        widget=forms.NumberInput(attrs={"form": "analysis-form"}),
    )


# Shared input and method-specific parameters for comparison runs.
class ComparisonForm(DataForm):
    filter_mode = forms.ChoiceField(
        label="Chelton background removal",
        initial="none",
        choices=[
            ("none", "No additional filtering"),
            ("custom", "Custom Gaussian"),
            ("paper_scale", "Paper-scale Gaussian approximation"),
        ],
    )
    sigma_cells = forms.FloatField(
        label="Gaussian σ [grid cells]",
        initial=4,
        min_value=0.5,
        max_value=20,
        required=False,
    )
    a = forms.IntegerField(
        label="Nencioli velocity radius a [cells]", initial=4, min_value=2, max_value=10
    )
    b = forms.IntegerField(
        label="Nencioli minimum radius b [cells]", initial=3, min_value=1, max_value=10
    )
    contour_interval_cm = forms.FloatField(
        label="Halo contour interval [cm]", initial=2, min_value=0.5, max_value=20
    )
    max_diameter_km = forms.FloatField(
        label="Halo maximum diameter [km]", initial=600, min_value=10, max_value=1000
    )
    filter_passes = forms.IntegerField(
        label="Halo Hanning passes on W", initial=2, min_value=0, max_value=6
    )

    def clean(self):
        cleaned = super().clean()
        if (
            cleaned.get("filter_mode") == "custom"
            and cleaned.get("sigma_cells") is None
            and "sigma_cells" not in self.errors
        ):
            self.add_error(
                "sigma_cells", "Enter a scale for custom Gaussian filtering."
            )
        return cleaned


class ComparisonTrackingForm(ComparisonForm):
    duration_days = forms.IntegerField(
        label="Tracking duration [days]",
        initial=90,
        min_value=1,
        max_value=365,
        help_text="Consecutive calendar days from the selected start date; maximum one year (365 days).",
    )
    min_count = forms.IntegerField(
        label="Minimum tracks per age bin", initial=20, min_value=1
    )
    include_censored = forms.BooleanField(
        label="Include tracks touching the period boundaries in Figure 8",
        required=False,
    )

    def clean(self):
        from datetime import timedelta
        from .datasets import get_available_dates

        cleaned = super().clean()
        start, duration = cleaned.get("day"), cleaned.get("duration_days")
        if start and duration:
            available = get_available_dates()
            missing = sum(
                (start + timedelta(days=i)).isoformat() not in available
                for i in range(duration)
            )
            if missing:
                self.add_error(
                    "duration_days",
                    f"The selected period contains {missing} unavailable daily grids. Choose a fully available period.",
                )
        return cleaned


# Association controls for the individual tracking explorers.
class NencioliTrackingForm(DataForm):
    duration_days = forms.IntegerField(
        label="Tracking duration [days]",
        initial=10,
        min_value=1,
        max_value=30,
        help_text="Consecutive calendar days, including the starting date; maximum 30.",
    )
    a = deepcopy(NencioliDetectionForm.base_fields["a"])
    b = deepcopy(NencioliDetectionForm.base_fields["b"])
    a.required = b.required = True
    daily_radius_km = forms.FloatField(
        label="Daily search radius [km]",
        initial=30,
        min_value=0.001,
        help_text="Maximum center displacement to the next day.",
    )
    gap_radius_km = forms.FloatField(
        label="Gap search radius [km]",
        initial=45,
        min_value=0.001,
        help_text="Maximum displacement across one missing detection day.",
    )
    min_lifetime_days = forms.IntegerField(
        label="Minimum lifetime [days]",
        initial=4,
        min_value=1,
        max_value=30,
        help_text="Calendar span from first to last observation, including gaps.",
    )

    def clean(self):
        cleaned = super().clean()
        if (
            cleaned.get("min_lifetime_days") is not None
            and cleaned.get("duration_days") is not None
            and cleaned["min_lifetime_days"] > cleaned["duration_days"]
        ):
            self.add_error(
                "min_lifetime_days",
                "Minimum lifetime cannot exceed the tracking duration.",
            )
        return cleaned


class CheltonTrackingForm(DataForm):
    duration_days = forms.IntegerField(
        label="Tracking duration [days]",
        initial=90,
        min_value=1,
        max_value=90,
        help_text="Consecutive daily observations, including the start; maximum 90 days.",
    )
    min_lifetime_days = forms.IntegerField(
        label="Minimum retained lifetime [days]",
        initial=28,
        min_value=1,
        max_value=90,
        help_text="Default 28-day retention for the daily OSU adaptation; lower values remain available for exploration.",
    )
    filter_mode = deepcopy(CheltonDetectionForm.base_fields["filter_mode"])
    sigma_cells = deepcopy(CheltonDetectionForm.base_fields["sigma_cells"])
    east_km = forms.FloatField(
        label="Eastward search semi-axis [km]", initial=30, min_value=0.001
    )
    west_km = forms.FloatField(
        label="Westward search semi-axis [km]", initial=50, min_value=0.001
    )
    north_south_km = forms.FloatField(
        label="North–south search semi-axis [km]", initial=30, min_value=0.001
    )
    min_amplitude_ratio = forms.FloatField(
        label="Minimum amplitude ratio", initial=0.25, min_value=0.001
    )
    max_amplitude_ratio = forms.FloatField(
        label="Maximum amplitude ratio", initial=2.5, min_value=0.001
    )
    min_area_ratio = forms.FloatField(
        label="Minimum area ratio", initial=0.25, min_value=0.001
    )
    max_area_ratio = forms.FloatField(
        label="Maximum area ratio", initial=2.5, min_value=0.001
    )

    def clean(self):
        cleaned = super().clean()
        if (
            cleaned.get("filter_mode") == "custom"
            and cleaned.get("sigma_cells") is None
        ):
            self.add_error(
                "sigma_cells", "Enter a Gaussian scale for custom filtering."
            )
        if (
            cleaned.get("min_lifetime_days") is not None
            and cleaned.get("duration_days") is not None
            and cleaned["min_lifetime_days"] > cleaned["duration_days"]
        ):
            self.add_error(
                "min_lifetime_days",
                "Minimum lifetime cannot exceed the tracking duration.",
            )
        for quantity in ("amplitude", "area"):
            lower, upper = f"min_{quantity}_ratio", f"max_{quantity}_ratio"
            if (
                cleaned.get(lower) is not None
                and cleaned.get(upper) is not None
                and cleaned[lower] > cleaned[upper]
            ):
                self.add_error(
                    upper, "Maximum ratio must be at least the minimum ratio."
                )
        return cleaned


class HaloTrackingForm(DataForm):
    vorticity_scale_s = forms.FloatField(
        label="Vorticity scale [s⁻¹]",
        initial=1e-5,
        min_value=1e-12,
        help_text="Normalizes the signed contour-mean vorticity difference in the matching score.",
        widget=forms.NumberInput(attrs={"step": "any"}),
    )
    max_displacement_km = forms.FloatField(
        label="Maximum daily displacement [km]",
        initial=50,
        min_value=0.001,
        help_text="Hard adjacent-day center-distance limit, applied before scoring. 50 km is experimental; compare 30, 50, and 75 km.",
    )
    duration_days = forms.IntegerField(
        label="Tracking duration [days]", initial=30, min_value=1, max_value=90
    )
    min_lifetime_days = forms.IntegerField(
        label="Minimum observed span [days]",
        initial=4,
        min_value=1,
        max_value=90,
        help_text="4 days for diagnostics; 31 selects spans over 30 days. Censored spans are not exact lifetimes.",
    )
    contour_interval_cm = deepcopy(HaloDetectionForm.base_fields["contour_interval_cm"])
    max_diameter_km = deepcopy(HaloDetectionForm.base_fields["max_diameter_km"])
    filter_passes = deepcopy(HaloDetectionForm.base_fields["filter_passes"])
    position_scale_km = forms.FloatField(
        label="Position scale [km]",
        initial=25,
        min_value=0.001,
        help_text="Normalizes center displacement in the matching score; not a hard search radius.",
    )
    diameter_scale_km = forms.FloatField(
        label="Diameter scale [km]",
        initial=200,
        min_value=0.001,
        help_text="Normalizes the change in area-equivalent diameter.",
    )
    max_generalized_distance = forms.FloatField(
        label="Maximum generalized distance [dimensionless]",
        required=False,
        initial=2.0,
        min_value=0.001,
        help_text="2.0 is an uncalibrated experimental candidate. Optional score cutoff in addition to the daily displacement limit. Blank applies no score cutoff.",
    )

    assignment_method = forms.ChoiceField(
        label="Assignment",
        required=False,
        initial="global",
        choices=[
            ("global", "Global one-to-one (experimental)"),
            ("greedy", "Greedy (legacy)"),
        ],
    )
    max_gap_days = forms.IntegerField(
        label="Missing detection days allowed",
        required=False,
        initial=0,
        min_value=0,
        max_value=1,
        help_text="Optional sensitivity. Adjacent-day matches have priority; missing observations are never interpolated.",
    )
    gap_max_displacement_km = forms.FloatField(
        label="Two-day gap total displacement [km]",
        required=False,
        initial=50,
        min_value=0.001,
    )
    gap_max_generalized_distance = forms.FloatField(
        label="Gap maximum score", required=False, initial=1, min_value=0.001
    )
    velocity_smoothing_passes = forms.IntegerField(
        label="Velocity Hanning passes for vorticity",
        required=False,
        initial=0,
        min_value=0,
        max_value=20,
        help_text="0 keeps raw vorticity. This sensitivity leaves detection contours unchanged.",
    )
    minimum_abs_vorticity_s = forms.FloatField(
        label="Uncertain-vorticity floor [s⁻¹]",
        required=False,
        initial=0,
        min_value=0,
        help_text="Means at or below this absolute value are excluded. 0 adds no noise floor; any positive value requires calibration.",
        widget=forms.NumberInput(attrs={"step": "any"}),
    )

    def clean(self):
        cleaned = super().clean()
        defaults = dict(
            assignment_method="global",
            max_gap_days=0,
            gap_max_displacement_km=50.0,
            gap_max_generalized_distance=1.0,
            velocity_smoothing_passes=0,
            minimum_abs_vorticity_s=0.0,
        )
        for key, value in defaults.items():
            if key not in self.errors and cleaned.get(key) in (None, ""):
                cleaned[key] = value
        if cleaned.get("max_gap_days"):
            for gap, daily in [
                ("gap_max_displacement_km", "max_displacement_km"),
                ("gap_max_generalized_distance", "max_generalized_distance"),
            ]:
                if (
                    cleaned.get(gap) is not None
                    and cleaned.get(daily) is not None
                    and cleaned[gap] > cleaned[daily]
                ):
                    self.add_error(
                        gap, "Gap limits must be no looser than daily limits."
                    )
        if (
            cleaned.get("min_lifetime_days") is not None
            and cleaned.get("duration_days") is not None
            and cleaned["min_lifetime_days"] > cleaned["duration_days"]
        ):
            self.add_error(
                "min_lifetime_days",
                "Minimum lifetime cannot exceed the tracking duration.",
            )
        return cleaned
