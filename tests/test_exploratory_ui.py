"""The ninth KPI is visible, formatted and usable in policy ranking."""
import unittest
from unittest.mock import patch

import pandas as pd
import streamlit as st
from streamlit.testing.v1 import AppTest

from pv_batteries import exploratory_config as cfg
from test_exploratory import synthetic_store


class ExploratoryUITests(unittest.TestCase):
    def tearDown(self):
        st.cache_data.clear()

    def app_with(self, frame):
        original = pd.read_parquet
        def read(path, *args, **kwargs):
            return frame.copy() if str(path).endswith('exploratory_kpis.parquet') else original(path, *args, **kwargs)
        return patch('pandas.read_parquet', side_effect=read)

    def test_both_views_show_nine_indicators_and_new_weight_changes_ranking(self):
        with self.app_with(synthetic_store()):
            app = AppTest.from_file(str(cfg.ROOT / 'app.py'), default_timeout=60).run()
            app.switch_page('pages/5_Analisi_Esplorativa.py').run()
            self.assertFalse(app.exception)
            self.assertFalse(app.error)
            table = app.dataframe[0].value
            self.assertEqual(len(table), 9)
            row = table.loc[table['Indicatore'] == cfg.KPI_SPEC['pv_self_coverage']['label']].iloc[0]
            self.assertEqual(row['Unità'], '%')
            self.assertAlmostEqual(row['Mediana'], 10.495)
            app.session_state['expl_subpage'] = 'Migliori policy mix'
            app.run()
            self.assertFalse(app.exception)
            self.assertEqual(len(app.slider), 9)
            self.assertAlmostEqual(sum(slider.value for slider in app.slider), 1.)
            app.slider(key='expl_w_pv_self_coverage').set_value(1.).run()
            self.assertFalse(app.exception)
            self.assertFalse(app.error)
            ranking = app.dataframe[0].value
            self.assertEqual(len(ranking), 128)
            self.assertTrue((ranking['N scenari'] == 100).all())
            label = cfg.KPI_SPEC['pv_self_coverage']['label'] + ' (%)'
            self.assertAlmostEqual(ranking.iloc[0][label], 60.495)
            self.assertIn('Spesa cantonale cumulata (Mio CHF)', ranking.columns)

    def test_old_or_partial_dataset_is_rejected(self):
        with self.app_with(synthetic_store().iloc[:-1]):
            app = AppTest.from_file(str(cfg.ROOT / 'app.py'), default_timeout=60).run()
            app.switch_page('pages/5_Analisi_Esplorativa.py').run()
            self.assertFalse(app.exception)
            self.assertTrue(app.error)
            self.assertIn('12800', app.error[0].value)
            self.assertFalse(app.dataframe)


if __name__ == '__main__':
    unittest.main()
