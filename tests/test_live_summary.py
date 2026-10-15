"""Live equity matches the batch definition and keeps all archetype labels."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
from streamlit.testing.v1 import AppTest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pv_batteries"))
from echarts_charts import build_radar_options
from gmd import gmd_from_frame
from sure_julia.batch import gmd as batch_gmd
from sure_julia.runtime import frame_from_arrays
from sure_pysd import LIVE_OUTPUTS, OUTPUTS
from sure_backend import engine_identity
import pv_batteries_config as pv
import risanamento_config as ris


class LiveSummaryTests(unittest.TestCase):
    def setUp(self):
        dims = ["Type", "Income"]
        self.export = [{"name": name, "dims": dims,
                        "coords": {"Type": ["SFH", "MFH"], "Income": ["low", "high"]}}
                       for name in ("Cost", "Households")]
        self.arrays = {"Cost": np.broadcast_to([[100., 300.], [200., 800.]], (40, 2, 2)).copy(),
                       "Households": np.broadcast_to([[1., 2.], [3., 4.]], (40, 2, 2)).copy()}
        self.specs = {"equity": {"value": "Cost", "weight": "Households"}}

    def test_live_matches_batch_with_reordered_columns(self):
        df = frame_from_arrays(self.arrays, self.export)
        live = gmd_from_frame(df[df.columns[::-1]], self.specs)
        batch = batch_gmd(self.arrays, self.specs, {e["name"]: e for e in self.export})
        self.assertEqual(live, batch)
        self.assertAlmostEqual(live["equity"], 153.)

    def test_missing_coordinates_nonfinite_and_negative_weights_fail(self):
        df = frame_from_arrays(self.arrays, self.export)
        with self.assertRaisesRegex(ValueError, "allineati"):
            gmd_from_frame(df.drop(columns=["Households[SFH,low]"]), self.specs)
        df.loc[2050, "Households[SFH,low]"] = -1.
        with self.assertRaisesRegex(ValueError, "negativi"):
            gmd_from_frame(df, self.specs)
        df.loc[2050, "Households[SFH,low]"] = np.nan
        with self.assertRaisesRegex(ValueError, "non finito"):
            gmd_from_frame(df, self.specs)
        with self.assertRaisesRegex(ValueError, "2050"):
            gmd_from_frame(df.iloc[:-1], self.specs)

    def test_live_output_request_covers_equity_without_reordering_batch(self):
        self.assertEqual(LIVE_OUTPUTS[:len(OUTPUTS)], OUTPUTS)
        self.assertFalse((set(pv.GMD_VARS) | set(ris.GMD_VARS)) - set(LIVE_OUTPUTS))
        self.assertEqual(len(LIVE_OUTPUTS), len(set(LIVE_OUTPUTS)))
        with patch("sure_backend.digest", return_value="same-source"):
            before = engine_identity()
            with patch("sure_backend.OUTPUTS", OUTPUTS):
                self.assertNotEqual(before, engine_identity())

    def test_radar_does_not_clip_live_values_beyond_reference_range(self):
        options = build_radar_options(["A", "B", "C"], [-.5, 1.5, 1.], [1., 1., 1.])
        self.assertTrue(all(axis["min"] <= -50. for axis in options["radar"]["indicator"]))
        self.assertTrue(all(axis["max"] >= 150. for axis in options["radar"]["indicator"]))

    def test_live_pv_displays_six_metrics_and_radar_with_shared_definitions(self):
        from explore_results_charts import _LEGACY_PV_CAPACITY_BASES
        frame = pd.DataFrame({
            "PV residential power by Type[SFH]": [100.],
            "Total PV electricity production": [150.],
            "Total Battery capacity District[Lugano]": [20.],
            "Average electricity and heating and retrofit cost": [2500.],
            **{name: [1000.] for name in _LEGACY_PV_CAPACITY_BASES},
            **{name + "[A]": [10.] for name in pv.GMD_VARS},
            **{name + "[B]": [20.] for name in pv.GMD_VARS},
        }, index=[2050])
        app = AppTest.from_string('''
import streamlit as st
from live_summary import render_live_summary
render_live_summary('PV e Batterie', st.session_state['frame'], st.session_state['frame'])
''')
        app.session_state["frame"] = frame
        with (patch("live_summary.reference_bounds", return_value={name: (0., 100.) for name in pv.GMD_SPEC}),
              patch("echarts_charts.render_echarts") as chart):
            app.run()
            self.assertFalse(app.exception)
            self.assertFalse(app.warning)
            self.assertEqual(len(app.metric), 6)
            self.assertTrue(all(m.value != "n/d" and m.delta == "0.0% vs Base" for m in app.metric))
            self.assertIn("radar", chart.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
