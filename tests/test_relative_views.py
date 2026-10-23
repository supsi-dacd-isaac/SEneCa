"""Relative display preserves scenario totals and uses the complete historical denominator."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import pandas as pd
import numpy as np
from streamlit.testing.v1 import AppTest
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'pv_batteries')]
from chart_views import relative_series, historical_series
from history_data import available_history

class RelativeViewsTests(unittest.TestCase):
    def test_complete_rows_sum_to_100_missing_zero_negative_stay_undefined(self):
        raw=pd.DataFrame({'a':[2,0,1,-1], 'b':[6,0,np.nan,3]},index=[2021,2022,2023,2024])
        original=raw.copy(deep=True)
        result=relative_series(raw)
        self.assertEqual(result.loc[2021].tolist(),[25,75])
        self.assertTrue(result.loc[2022:].isna().all().all())
        pd.testing.assert_frame_equal(raw,original)

    def test_historical_bev_share_uses_all_seven_categories_from_2011(self):
        raw=pd.read_csv(ROOT/'Vensim/EVinput.csv',index_col=0)
        names=[f'Adoption Vehicles[{t}]' for t in ['Petrol','Diesel','PetrolHEV','PetrolPHEV','DieselHEV','DieselPHEV','BEV']]
        all_types=available_history(raw,names)
        result=historical_series('vehicle_adoptions',relative=True)
        self.assertEqual(result.index.min(),2011)
        self.assertEqual(result.index.max(),2024)
        expected=100*all_types[names[-1]]/all_types.sum(axis=1)
        np.testing.assert_allclose(result.BEV,expected)
        self.assertFalse(result.isna().any().any())

    def test_selected_baseline_and_observation_have_separate_denominators(self):
        script='''
import pandas as pd
from echarts_charts import render_echarts_line
from veicoli_config import OUTPUTS
df=pd.DataFrame({'Adoption Vehicles[BEV]':[20.,40.], 'Adoption Vehicles[Petrol]':[80.,60.]},index=[2023,2024])
base=pd.DataFrame({'Adoption Vehicles[BEV]':[10.,30.], 'Adoption Vehicles[Petrol]':[190.,270.]},index=[2023,2024])
render_echarts_line(df,OUTPUTS[0],chart_key='test',df_base=base)
'''
        with patch('echarts_charts.render_echarts') as render:
            app=AppTest.from_string(script).run()
            app.session_state['test_composition']='relative'
            app.run()
            app.checkbox[0].check().run()
            self.assertFalse(app.exception)
            calls={call.kwargs['chart_key']:call.args[0] for call in render.call_args_list}
            options=calls['test']
            by_name={s['name']:s['data'] for s in options['series']}
            baseline={s['name']:s['data'] for s in calls['test_relative_base']['series']}
            self.assertEqual(by_name['BEV'],[20,40])
            self.assertEqual(baseline['BEV'],[5,10])
            self.assertNotIn('BEV (Base)',by_name)
            for chart in (options,calls['test_relative_base']):
                areas=[s for s in chart['series'] if s['type']=='line']
                self.assertEqual(areas[0]['name'],'BEV')
                self.assertTrue(all(s.get('stack')=='shares' and 'areaStyle' in s and not s['smooth'] for s in areas))
                np.testing.assert_allclose(np.array([s['data'] for s in areas]).sum(axis=0),[100,100])
                self.assertNotIn('stack',chart['series'][-1])
            np.testing.assert_allclose(by_name['BEV (storico)'],historical_series('vehicle_adoptions',True).loc[[2023,2024],'BEV'])
            self.assertEqual(options['yAxis']['max'],100)
            app.session_state['test_composition']='absolute'
            app.run()
            absolute=render.call_args.args[0]
            self.assertEqual(absolute['yAxis']['name'],'veicoli/anno')
            self.assertIsNone(absolute['yAxis']['max'])
            self.assertTrue(all('stack' not in s and 'areaStyle' not in s for s in absolute['series']))
