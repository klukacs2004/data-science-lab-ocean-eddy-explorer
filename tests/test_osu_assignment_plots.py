"""Scientific invariants for the assignment's distributions and age scaling."""

import importlib.util
from pathlib import Path
import unittest
from tempfile import TemporaryDirectory

import numpy as np
import pandas as pd

spec = importlib.util.spec_from_file_location(
    "osu_plots", Path(__file__).resolve().parents[1] / "scripts/plot_osu_assignment.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class AssignmentStatisticsTests(unittest.TestCase):
    def observations(self):
        rows = []
        for identifier in (1, 2):
            for t in range(10):
                rows.append(
                    dict(
                        method="Nencioli",
                        track_id=identifier,
                        date=pd.Timestamp("2000-01-01") + pd.Timedelta(days=t),
                        radius_km=10.0 * identifier,
                        reliable_radius=True,
                        left_censored=False,
                        right_censored=False,
                    )
                )
        return pd.DataFrame(rows)

    def test_age_uses_lifespan_not_last_age_and_preserves_absolute_radius(self):
        obs, tracks = module.prepare(self.observations())
        self.assertEqual(tracks.span_days.tolist(), [10, 10])
        self.assertAlmostEqual(obs.scaled_age.max(), 0.9)
        cycles = module.cycle_table(obs, tracks, min_count=2)
        shown = cycles[cycles.radius_km.notna()]
        self.assertTrue(len(shown))
        np.testing.assert_allclose(shown.radius_km, 15.0)
        self.assertTrue((shown.contributors == 2).all())
        self.assertFalse(
            module.cycle_table(obs, tracks, min_count=3).radius_km.notna().any()
        )

    def test_unreliable_radius_does_not_remove_track_from_span_population(self):
        data = self.observations()
        data.loc[data.track_id == 1, "reliable_radius"] = False
        obs, tracks = module.prepare(data)
        self.assertEqual(len(tracks), 2)
        self.assertTrue(
            np.isnan(tracks.loc[tracks.track_id == 1, "mean_radius_km"].iloc[0])
        )
        self.assertEqual(obs.usable_radius.sum(), 10)

    def test_censored_cycles_and_duplicate_days(self):
        data = self.observations()
        data["left_censored"] = True
        obs, tracks = module.prepare(data)
        self.assertFalse(module.cycle_table(obs, tracks, 2).radius_km.notna().any())
        self.assertTrue(
            module.cycle_table(obs, tracks, 2, True).radius_km.notna().any()
        )
        with self.assertRaises(ValueError):
            module.prepare(pd.concat([data, data.iloc[:1]]))

    def test_exported_distributions_have_correct_denominators(self):
        data = self.observations()
        # Two tracks of spans 1 and 10, but 11 daily detections.
        data = data[(data.track_id == 2) | (data.date == data.date.min())]
        with TemporaryDirectory() as directory:
            output = Path(directory)
            module.plot(data, output)
            radius = pd.read_csv(output / "figure7_radius_data.csv")
            radius = radius[radius.method == "Nencioli"]
            self.assertEqual(radius["count"].sum(), 11)
            self.assertAlmostEqual(radius.percent.sum(), 100.0)
            survival = pd.read_csv(output / "figure7_survival_data.csv")
            survival = survival[survival.method == "Nencioli"].set_index("span_days")
            self.assertEqual(survival.loc[1, "percent"], 100.0)
            self.assertEqual(survival.loc[2, "percent"], 50.0)
            self.assertEqual(survival.loc[11, "percent"], 0.0)


if __name__ == "__main__":
    unittest.main()
