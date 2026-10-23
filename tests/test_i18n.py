"""Italian/English pilot: locale isolation, stable choices and identical data."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import pandas as pd
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'pv_batteries')]
from pv_batteries import i18n
from pv_batteries.policy_labels import POLICY_LABELS
import pv_batteries_config as cfg


def numeric_chart(options):
    """All data, ranges and styling except explicitly localised presentation."""
    item = deepcopy(options)
    item.pop('toolbox', None)
    item.get('grid', {}).pop('containLabel', None)
    def strip(v):
        if isinstance(v, dict):
            return {k: strip(x) for k, x in v.items() if k != 'name'}
        if isinstance(v, list):
            return [strip(x) for x in v]
        return '<label>' if isinstance(v, str) else v
    return strip(item)


class TranslationTests(unittest.TestCase):
    def test_catalog_and_fallback(self):
        en = i18n.catalog('en')
        self.assertEqual(en.gettext('Potenza PV totale'), 'Total PV capacity')
        self.assertEqual(en.gettext('Unknown technical variable'), 'Unknown technical variable')
        self.assertEqual(i18n.catalog('it').gettext('Potenza PV totale'), 'Potenza PV totale')
        for name in cfg.INPUT_ORDER:
            for field in ('label', 'short_label', 'control_label', 'help'):
                message = POLICY_LABELS[name].get(field)
                if message:
                    self.assertNotEqual(en.gettext(message), message, (name, field))

    def test_chart_translation_is_pure_and_preserves_data(self):
        from echarts_charts import build_line_options
        from chart_views import add_historical_options
        source = build_line_options([2023, 2024], {'Produzione': [1.2, None]}, unit='GWh', compare={'Produzione':[1.0, 3.0]})
        add_historical_options(source, pd.DataFrame({'Produzione':[1.1, 2.0]}))
        original = deepcopy(source)
        with patch.object(i18n, 'language', return_value='en'):
            translated = i18n.chart_options(source)
        self.assertEqual(source, original)
        for before, after in zip(source["series"], translated["series"]):
            for field in ("lineStyle", "itemStyle", "data"):
                self.assertEqual(before.get(field), after.get(field))
        self.assertEqual(numeric_chart(source), numeric_chart(translated))
        self.assertEqual([s['name'] for s in translated['series']],
                         ['Generation', 'Generation (Baseline)', 'Generation (observed)'])
        self.assertEqual(translated['legend']['data'], [s['name'] for s in translated['series']])

    def test_language_is_session_local(self):
        code = "from pv_batteries.i18n import language_selector, tr\nimport streamlit as st\nlanguage_selector()\nst.title(tr('Potenza PV totale'))"
        a = AppTest.from_string(code).run()
        b = AppTest.from_string(code).run()
        a.radio(key='ui_language').set_value('en').run()
        self.assertEqual(a.title[0].value, 'Total PV capacity')
        b.run()
        self.assertEqual(b.title[0].value, 'Potenza PV totale')

    def test_home_language_switch(self):
        at = AppTest.from_file(str(ROOT/'app.py'), default_timeout=30).run()
        at.radio(key='ui_language').set_value('en').run()
        self.assertFalse(at.exception)
        self.assertEqual(at.title[0].value, 'The SEneCa model for Ticino')
        at.radio(key='ui_language').set_value('it').run()
        self.assertEqual(at.title[0].value, 'Modello SEneCa per il Ticino')

    @unittest.skipUnless(cfg.CONSOLIDATED_TRAJ.exists(), 'Install the pinned data release for the PV integration test')
    def test_pv_values_options_history_and_all_sections_survive_language_switch(self):
        # AppTest.switch_page executes a child page directly in Streamlit 1.64;
        # reproduce the shared entrypoint selector here. Real navigation is also
        # checked in the browser.
        code = f"import runpy\nfrom pv_batteries.i18n import language_selector\nlanguage_selector()\nrunpy.run_path({str(ROOT/'pages/1_PV_e_Batterie.py')!r})"
        at = AppTest.from_string(code, default_timeout=45).run()
        self.assertFalse(at.exception)
        at.select_slider(key='pv_input_PV rebate cantonal').set_value(.2).run()
        at.checkbox(key='pv_compare_base').check().run()
        at.session_state['pv_input_Energy Community scenario'] = 1.0
        at.run()
        for section in [g['title'] for g in cfg.OUTPUT_GROUPS]:
            at.session_state['pv_section'] = section
            at.run()
            if section == 'Adozione fotovoltaico':
                at.checkbox(key='pv_0_Fotovoltaico_calibration').check().run()
                at.checkbox(key='pv_Adozione fotovoltaico_Potenza PV non residenziale_history').check().run()
                at.session_state['pv_Adozione fotovoltaico_Potenza PV non residenziale_time_view'] = 'annual'
                at.run()
            if section == 'Adozione batterie':
                at.checkbox(key='pv_0_Accumulatori_calibration').check().run()
            self.assertFalse(at.exception)
            values = [m.value for m in at.metric]
            frame = at.dataframe[0].value.copy()
            at.radio(key='ui_language').set_value('en').run()
            self.assertFalse(at.exception)
            self.assertEqual(at.session_state['pv_section'], section)
            self.assertEqual(at.select_slider(key='pv_input_PV rebate cantonal').value,.2)
            self.assertEqual(at.session_state['pv_input_Energy Community scenario'],1.0)
            self.assertTrue(at.checkbox(key='pv_compare_base').value)
            self.assertEqual([m.value for m in at.metric],values)
            pd.testing.assert_frame_equal(at.dataframe[0].value,frame)
            self.assertEqual(at.title[0].value,'PV & decentralised batteries')
            at.radio(key='ui_language').set_value('it').run()
            self.assertFalse(at.exception)
            self.assertEqual([m.value for m in at.metric],values)
            pd.testing.assert_frame_equal(at.dataframe[0].value,frame)


if __name__ == '__main__':
    unittest.main()
