"""Temporal views preserve model timing, baseline alignment and missing data."""
import hashlib
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from streamlit.testing.v1 import AppTest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pv_batteries"))
from chart_views import historical_series, transform_series
from sd_explainer.loaders import load_calibration_series, load_pv_buildings_input
from pv_batteries.history_data import available_history, calibration_observations
from sd_explainer.paths import IMAGE_WORKSHOP, PV_INPUT_CSV, SIM_ADOPTIONS_CSV


class TemporalViewsTests(unittest.TestCase):
    def test_installed_power_uses_forward_step_and_excludes_initial_stock(self):
        stock = pd.DataFrame({"PV": [100., 120., 155.]}, index=[2023, 2024, 2025])
        annual = transform_series(stock, "stock", "annual")
        self.assertEqual(annual.PV.iloc[:2].tolist(), [20., 35.])
        self.assertTrue(pd.isna(annual.PV.loc[2025]))
        pd.testing.assert_frame_equal(transform_series(stock, "stock", "native"), stock)

    def test_missing_intervals_are_neither_zero_nor_multi_year_changes(self):
        data = pd.DataFrame({"PV": [10., 30., 40.]}, index=[2020, 2022, 2023])
        annual = transform_series(data, "stock", "annual")
        self.assertTrue(pd.isna(annual.PV.loc[2020]))
        self.assertEqual(annual.PV.loc[2022], 10.)
        cumulative = transform_series(data, "flow", "cumulative")
        self.assertEqual(cumulative.PV.loc[2020], 10.)
        self.assertTrue(cumulative.PV.loc[2022:].isna().all())
        self.assertTrue(transform_series(data.iloc[:0], "flow", "cumulative").empty)

    def test_flow_sums_are_inclusive_and_missing_values_propagate(self):
        flow = pd.DataFrame({"A": [2., 3., 4.], "B": [1., None, 2.]}, index=[2011, 2012, 2013])
        cumulative = transform_series(flow, "flow", "cumulative")
        self.assertEqual(cumulative.A.tolist(), [2., 5., 9.])
        self.assertTrue(cumulative.B.iloc[1:].isna().all())

    def test_chart_switch_updates_scenario_and_base_on_their_own_years(self):
        script = '''
import pandas as pd
from echarts_charts import render_echarts_line
df = pd.DataFrame({'PV[A]': [100., 120., 155.]}, index=[2023, 2024, 2025])
base = pd.DataFrame({'PV[A]': [70., 80., 95., 110.]}, index=[2022, 2023, 2024, 2025])
render_echarts_line(df, {'base':'PV', 'kind':'line', 'title':'PV', 'unit':'MW',
                         'time_basis':'stock'}, df_base=base)
'''
        with patch("echarts_charts.render_echarts") as render:
            app = AppTest.from_string(script).run()
            self.assertFalse(app.exception)
            app.session_state["PV_time_view"] = "annual"
            app.run()
            self.assertFalse(app.exception)
            options = render.call_args.args[0]
            self.assertEqual(options["series"][0]["data"], [20., 35., None])
            self.assertEqual(options["series"][1]["data"], [15., 15., None])

    def test_historical_pv_capacity_stops_at_last_observation(self):
        history = historical_series("pv_capacity")
        self.assertEqual(history.index.max(), 2026)
        self.assertEqual(set(history), {"30–100 kW", "> 100 kW"})
        annual = transform_series(history, "stock", "annual").reindex(range(2011, 2051))
        self.assertEqual(annual.loc[2025].tolist(), [7815., 13478.])
        self.assertTrue(annual.loc[2026:].isna().all().all())

    def test_vehicle_history_only_overlays_bev_and_keeps_other_simulated_types(self):
        history = historical_series("vehicle_adoptions")
        self.assertEqual(list(history), ["BEV"])
        raw = pd.read_csv(Path(__file__).resolve().parents[1] / "Vensim/EVinput.csv", index_col=0)
        expected = available_history(raw, ["Adoption Vehicles[BEV]"])
        self.assertEqual(history.BEV.tolist(), expected.iloc[:, 0].tolist())
        script = '''
import pandas as pd
from echarts_charts import render_echarts_line
from veicoli_config import OUTPUTS
df = pd.DataFrame({'Adoption Vehicles[BEV]': [100., 120.],
                   'Adoption Vehicles[PHEV]': [50., 60.],
                   'Adoption Vehicles[ICE]': [1000., 900.]}, index=[2023, 2024])
render_echarts_line(df, OUTPUTS[0], chart_key='vehicles', df_base=df * 0.9)
'''
        with patch("echarts_charts.render_echarts") as render:
            app = AppTest.from_string(script).run()
            app.checkbox[0].check().run()
            self.assertFalse(app.exception)
            series = render.call_args.args[0]["series"]
            self.assertEqual([s["name"] for s in series if s["type"] == "scatter"], ["BEV (storico)"])
            self.assertEqual({s["name"] for s in series if s["type"] == "line"},
                             {"BEV", "PHEV", "ICE", "BEV (Base)", "PHEV (Base)", "ICE (Base)"})

    def test_annual_only_charts_ignore_an_old_cumulative_selection(self):
        cases = [
            ("veicoli_config", "Adoption Vehicles", "render_echarts_line",
             {"Adoption Vehicles[BEV]": [2., 3.]}),
            ("pv_batteries_config", "Energia PV annuale", "render_echarts_line_composite",
             {"Total PV electricity production": [2., 3.],
              "Total PV electricity injected in the grid": [1., 2.],
              "Total PV electricity SC": [1., 1.]}),
        ]
        for config, name, renderer, data in cases:
            with self.subTest(chart=name), patch("echarts_charts.render_echarts") as render:
                script = f'''
import pandas as pd
import streamlit as st
from echarts_charts import {renderer}
from {config} import OUTPUTS
st.session_state['test_time_view'] = 'cumulative'
meta = next(m for m in OUTPUTS if m.get('base', m['title']) == {name!r})
df = pd.DataFrame({data!r}, index=[2023, 2024])
{renderer}(df, meta, chart_key='test', df_base=df * 0.5)
'''
                app = AppTest.from_string(script).run()
                app.checkbox[0].check().run()
                self.assertFalse(app.exception)
                self.assertFalse([control for control in app.get("button_group") if control.key == "test_time_view"])
                series = render.call_args.args[0]["series"]
                self.assertEqual(series[0]["data"], [2., 3.])
                baseline = next(s for s in series if s["name"] == series[0]["name"] + " (Base)")
                self.assertEqual(baseline["data"], [1., 1.5])

    def test_nonresidential_history_controls_stay_below_chart_after_toggle(self):
        script = '''
import pandas as pd
from echarts_charts import render_echarts_line_composite
from pv_batteries_config import OUTPUTS
meta = next(m for m in OUTPUTS if m['title'] == 'Potenza PV non residenziale')
df = pd.DataFrame({'"Capacity PV 30 - 100 kW total"': [100., 120.],
                   '"Capacity PV > 100 kW total"': [200., 240.]}, index=[2023, 2024])
render_echarts_line_composite(df, meta, chart_key='nonresidential')
'''
        app = AppTest.from_string(script).run()
        for checked in (False, True, False):
            app.checkbox[0].set_value(checked).run()
            self.assertFalse(app.exception)
            elements = list(app.main)
            chart_pos = next(i for i, el in enumerate(elements) if el.type == "iframe")
            check_pos = next(i for i, el in enumerate(elements) if el.type == "checkbox")
            self.assertLess(chart_pos, check_pos)
            self.assertTrue(all(i > chart_pos for i, el in enumerate(elements) if el.type == "caption"))
            if checked:
                history_captions = [
                    i for i, el in enumerate(elements)
                    if el.type == "caption" and el.value.startswith(("Dati disponibili:", "Dati di input"))
                ]
                self.assertEqual(len(history_captions), 2)
                self.assertTrue(all(i > check_pos for i in history_captions))

    def test_calibration_uses_model_inputs_for_every_year(self):
        years, series = load_calibration_series("Fotovoltaico")
        raw = pd.read_csv(PV_INPUT_CSV, index_col=0)
        rows = [f"Adoption PV Type[{t}]" for t in ("SFH", "DFH", "MFH")]
        expected = raw.loc[rows, years].astype(float).sum().tolist()
        self.assertEqual(series["Osservato"], expected)
        self.assertEqual(years[-1], '2025')
        self.assertEqual(series["Osservato"][-1], 1232.)
        self.assertEqual(sum(series["Osservato"]), 14199.)
        self.assertIsNotNone(series["Simulato"][-1])
        self.assertNotEqual(series["Simulato"][-1], series["Osservato"][-1])

    def test_calibration_plot_belongs_to_the_current_model_and_calibration(self):
        from sure_julia.common import MODEL_REVISION, model_sources
        audit = json.loads(SIM_ADOPTIONS_CSV.with_suffix('.json').read_text())
        self.assertEqual(audit['model_revision'], MODEL_REVISION)
        self.assertEqual(audit['model_sources'], model_sources())
        self.assertEqual(audit['csv_sha256'], hashlib.sha256(SIM_ADOPTIONS_CSV.read_bytes()).hexdigest())
        self.assertEqual(audit['validated_python_outputs_exact'], 137)
        self.assertTrue(audit['validated_julia_comparison_pass'])
        frame = pd.read_csv(SIM_ADOPTIONS_CSV, index_col=0)
        self.assertEqual(list(frame.index), list(range(2011, 2026)))
        for tech, years in audit['observation_years'].items():
            self.assertEqual(years, calibration_observations(tech).dropna().index.tolist())

    def test_missing_years_and_partial_totals_are_not_fabricated(self):
        raw = pd.DataFrame({'2023': [10., 0.], '2025': [3., None],
                            '2026': [None, None]}, index=['A', 'B'])
        history = available_history(raw, ['A', 'B'])
        self.assertEqual(history.index.tolist(), [2023, 2024, 2025])
        total = history.sum(axis=1, min_count=2)
        self.assertEqual(total.loc[2023], 10.)
        self.assertTrue(total.loc[2024:].isna().all())
        with patch('pv_batteries.history_data.CALIBRATION_INPUTS', {'test': ('unused.csv', ['A', 'B'])}), \
             patch('pv_batteries.history_data.pd.read_csv', return_value=raw):
            self.assertEqual(calibration_observations('test').to_dict(), {2023: 10.})

    def test_calibration_chart_uses_each_technologys_observed_period(self):
        for tech, end in [('Fotovoltaico', 2025), ('Pompe di calore', 2025),
                          ('Accumulatori', 2024), ('Veicoli elettrici', 2024)]:
            with self.subTest(technology=tech), patch('echarts_charts.render_echarts') as render:
                script = f'from chart_views import render_calibration_reference\nrender_calibration_reference({tech!r}, key="test")'
                app = AppTest.from_string(script).run()
                app.checkbox[0].check().run()
                self.assertFalse(app.exception)
                chart = render.call_args.args[0]
                self.assertEqual(chart['xAxis']['data'][-1], str(end))
                self.assertTrue(all(v is not None for v in chart['series'][1]['data']))

    def test_cumulative_pv_history_includes_2025_without_empty_2026(self):
        years, series = load_pv_buildings_input('Tipo di edificio')
        self.assertEqual(years[-1], '2025')
        self.assertEqual(sum(values[-1] for values in series.values()), 14199.)

    def test_workshop_asset_name_matches_case_on_linux(self):
        self.assertIn(IMAGE_WORKSHOP.name, [p.name for p in IMAGE_WORKSHOP.parent.iterdir()])


if __name__ == "__main__":
    unittest.main()
