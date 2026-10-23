"""Composition views: physical denominators, baseline and display round trips."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "pv_batteries")]
from chart_views import composition_series, historical_series, relative_series, transform_series
from pv_batteries_config import OUTPUTS as PV
from risanamento_config import OUTPUTS as HEAT


def output(items, title):
    return next(m for m in items if m.get("title") == title)


class EnergyRelativeViewsTests(unittest.TestCase):
    def test_pv_uses_production_once_and_never_invents_historical_shares(self):
        meta = output(PV, "Energia PV annuale")
        raw = pd.DataFrame({"Produzione": [100., 0., np.nan],
                            "In rete": [70., 0., 70.], "Autoconsumo (SC)": [30., 0., 30.]})
        shares = composition_series(raw, meta)
        self.assertEqual(list(shares), ["Autoconsumo (SC)", "In rete"])
        self.assertEqual(shares.loc[0].tolist(), [30., 70.])
        self.assertTrue(shares.iloc[1:].isna().all().all())
        self.assertTrue(composition_series(raw.drop(columns="In rete"), meta).isna().all().all())
        self.assertTrue(historical_series("pv_production", relative=True).empty)
        self.assertFalse(historical_series("pv_production").empty)

    def test_heating_cumulative_share_is_energy_weighted_and_includes_ambient(self):
        meta = output(HEAT, "Consumi annuali per vettore")
        frame = pd.DataFrame(0., index=[2023, 2024], columns=meta["relative_components"])
        frame["Olio"] = [80., 0.]
        frame["Calore ambiente"] = [20., 900.]
        cumulative = composition_series(transform_series(frame, "flow", "cumulative"), meta)
        self.assertEqual(cumulative.loc[2024, "Olio"], 8.)
        self.assertEqual(cumulative.loc[2024, "Calore ambiente"], 92.)
        np.testing.assert_allclose(cumulative.sum(axis=1), 100.)
        self.assertNotEqual(cumulative.loc[2024, "Olio"], composition_series(frame, meta)["Olio"].mean())

    def test_pv_renderer_history_baseline_and_absolute_round_trip(self):
        script = '''
import pandas as pd
from echarts_charts import render_echarts_line_composite
from pv_batteries_config import OUTPUTS
meta=next(m for m in OUTPUTS if m.get('title')=='Energia PV annuale')
df=pd.DataFrame({'Total PV electricity production':[100.,200.],
'Total PV electricity injected in the grid':[70.,140.],
'Total PV electricity SC':[30.,60.]},index=[2023,2024])
base=df.copy()
base['Total PV electricity production']=[200.,400.]
base['Total PV electricity injected in the grid']=[170.,340.]
render_echarts_line_composite(df,meta,chart_key='pv',df_base=base)
'''
        with patch("echarts_charts.render_echarts") as render:
            app = AppTest.from_string(script).run()
            app.checkbox[0].check().run()
            app.session_state["pv_composition"] = "relative"
            render.reset_mock()
            app.run()
            self.assertFalse(app.exception)
            self.assertTrue(app.checkbox[0].disabled)
            charts = {c.kwargs["chart_key"]: c.args[0] for c in render.call_args_list}
            for key, expected in (("pv", [30., 70.]), ("pv_relative_base", [15., 85.])):
                chart = charts[key]
                self.assertEqual(len(chart["series"]), 2)
                self.assertEqual([s["data"][0] for s in chart["series"]], expected)
                self.assertEqual(chart["yAxis"]["max"], 100)
            app.session_state["pv_composition"] = "absolute"
            app.run()
            self.assertFalse(app.checkbox[0].disabled)
            absolute = render.call_args.args[0]
            self.assertIsNone(absolute["yAxis"]["max"])
            self.assertEqual(absolute["yAxis"]["name"], "GWh")
            self.assertIn("Produzione", [s["name"] for s in absolute["series"]])
            self.assertIn("Produzione (storico)", [s["name"] for s in absolute["series"]])

    def test_heated_area_classes_have_independent_scenario_totals(self):
        script = '''
import pandas as pd
from echarts_charts import render_echarts_line
from risanamento_config import OUTPUTS
meta=next(m for m in OUTPUTS if m.get('base')=='Building area by Performance')
df=pd.DataFrame({'Building area by Performance[A]':[2.,3.], 'Building area by Performance[B]':[8.,7.]},index=[2023,2024])
base=df.copy()*2
base['Building area by Performance[A]']=[16.,14.]
render_echarts_line(df,meta,chart_key='area',df_base=base)
'''
        with patch("echarts_charts.render_echarts") as render:
            app = AppTest.from_string(script).run()
            app.session_state["area_composition"] = "relative"
            render.reset_mock()
            app.run()
            self.assertFalse(app.exception)
            charts = {c.kwargs["chart_key"]: c.args[0] for c in render.call_args_list}
            self.assertEqual(charts["area"]["series"][0]["data"], [20., 30.])
            self.assertEqual(charts["area_relative_base"]["series"][0]["data"], [50., 50.])

    def test_electricity_all_views_normalize_after_aggregation_excluding_imports(self):
        script = '''
from types import SimpleNamespace
import pandas as pd
from section_ui_hourly import _render_output
from elettricita_config import OUTPUTS
meta=next(m for m in OUTPUTS if m['base']=='Hourly available supply by Supplier')
rows=[]
for hour,hydro,pv in [('H1',1.,3.),('H2',9.,1.),('H3',0.,0.)]:
 for supplier,value in [('Hydro',hydro),('PV',pv),('Import',100.)]:
  rows.append(dict(variable=meta['base'],year=2024,month='M1',hour=hour,supplier=supplier,value=value))
df=pd.DataFrame(rows)
base=df.copy()
base.loc[base.supplier=='PV','value']*=2
cfg=SimpleNamespace(DISPLAY_YEARS=[2024],DISPLAY_MONTHS=['M1'],ALL_MONTHS=['M1'],YEARS=range(2024,2025),FINAL_YEAR=2024)
_render_output(df,meta,cfg,df_base=base)
'''
        with patch("section_ui_hourly.render_echarts") as render:
            app = AppTest.from_string(script).run()
            app.session_state["elec_Hourly available supply by Supplier_composition"] = "relative"
            for view, key in (("Totale annuo", "annual_supplier"), ("Profilo mensile", "monthly_2024"), ("Profilo orario", "hourly_M1_2024")):
                with self.subTest(view=view):
                    render.reset_mock()
                    app.selectbox[0].set_value(view).run()
                    self.assertFalse(app.exception)
                    charts = {c.kwargs["chart_key"]: c.args[0] for c in render.call_args_list}
                    chart = charts[f"Hourly available supply by Supplier_{key}"]
                    base_chart = charts[f"Hourly available supply by Supplier_{key}_relative_base"]
                    self.assertEqual([s['name'] for s in chart['series']], ["Hydro", "PV"])
                    self.assertEqual(chart['yAxis']['max'], 100)
                    actual = [s['data'][0] for s in chart['series']]
                    expected = [25., 75.] if view == "Profilo orario" else [1000/14, 400/14]
                    np.testing.assert_allclose(actual, expected)
                    expected_base = [100/7, 600/7] if view == "Profilo orario" else [1000/18, 800/18]
                    np.testing.assert_allclose([s['data'][0] for s in base_chart['series']], expected_base)
                    if view == "Profilo orario":
                        self.assertTrue(all(s['data'][2] is None for s in chart['series']))
                        self.assertTrue(all(s.get('stack') == 'shares' for s in chart['series']))
                    app.session_state["elec_Hourly available supply by Supplier_composition"] = "absolute"
                    app.run()
                    absolute = render.call_args.args[0]
                    self.assertIsNone(absolute['yAxis']['max'])
                    self.assertEqual(absolute['yAxis']['name'], 'GWh')
                    app.session_state["elec_Hourly available supply by Supplier_composition"] = "relative"


if __name__ == "__main__":
    unittest.main()
