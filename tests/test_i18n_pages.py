"""Presentation changes must preserve selections, scenario data and cached runs."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import pandas as pd
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'pv_batteries')]
from pv_batteries import i18n


def page(name):
    return AppTest.from_string(
        f"import runpy\nfrom pv_batteries.i18n import language_selector\nlanguage_selector()\nrunpy.run_path({str(ROOT/'pages'/name)!r})",
        default_timeout=60,
    ).run()


def metric_values(at):
    # Display units are translated; values and deltas must not change.
    return [(m.value.split(' ')[0], m.delta.split(' ')[0]) for m in at.metric]


class RemainingPageTests(unittest.TestCase):
    def assert_ok(self, at):
        self.assertFalse(at.exception, [e.message for e in at.exception])
        self.assertFalse(at.error, [e.value for e in at.error])

    def test_heating_and_vehicles_keep_scenarios_and_data(self):
        for filename, prefix, title, meta in [
            ('2_Riscaldamento_e_Risanamento.py', 'heat', 'Heating & renovation', 'risanamento_config'),
            ('3_Veicoli.py', 'vehicles', 'Vehicles', 'veicoli_config'),
        ]:
            with self.subTest(page=filename):
                cfg = __import__(meta)
                at = page(filename)
                self.assert_ok(at)
                name = cfg.INPUT_ORDER[0]
                target = cfg.INPUT_GRID[name][-1]
                at.select_slider(key=f'{prefix}_input_{name}').set_value(target).run()
                if prefix == 'heat':
                    at.radio(key='heat_input_MuKEn scenario').set_value('MoPEC 2025').run()
                at.checkbox(key=f'{prefix}_compare_base').check().run()
                self.assert_ok(at)
                before = metric_values(at)
                frame = at.dataframe[0].value.copy()
                at.radio(key='ui_language').set_value('en').run()
                self.assert_ok(at)
                self.assertEqual(at.title[0].value, title)
                self.assertEqual(at.select_slider(key=f'{prefix}_input_{name}').value, target)
                self.assertTrue(at.checkbox(key=f'{prefix}_compare_base').value)
                self.assertEqual(before, metric_values(at))
                pd.testing.assert_frame_equal(frame, at.dataframe[0].value)
                if prefix == 'heat':
                    self.assertEqual(at.radio(key='heat_input_MuKEn scenario').value,'MoPEC 2025')
                at.radio(key='ui_language').set_value('it').run()
                self.assert_ok(at)
                self.assertEqual(before, metric_values(at))

    def test_electricity_all_sections_and_views_keep_data(self):
        import elettricita_config as cfg
        at = page('4_Elettricità.py')
        self.assert_ok(at)
        binary = next(iter(cfg.BINARY_INPUTS))
        at.session_state[f'electricity_input_{binary}'] = 'Sì'
        at.checkbox(key='electricity_compare_base').check().run()
        for meta in cfg.OUTPUTS:
            at.session_state['elec_section'] = meta['desc']
            at.run()
            views = ['Totale annuo', 'Profilo mensile', 'Profilo orario'] if meta.get('extended_layout') else ['Profilo orario']
            for view in views:
                with self.subTest(section=meta['desc'], view=view):
                    if meta.get('extended_layout'):
                        at.selectbox(key=f"elec_view_{meta['base']}").set_value(view).run()
                    self.assert_ok(at)
                    before = metric_values(at)
                    at.radio(key='ui_language').set_value('en').run()
                    self.assert_ok(at)
                    self.assertEqual(at.title[0].value,'Electricity')
                    self.assertEqual(at.session_state['elec_section'],meta['desc'])
                    self.assertEqual(at.session_state[f'electricity_input_{binary}'],'Sì')
                    self.assertEqual(before,metric_values(at))
                    if meta.get('extended_layout'):
                        self.assertEqual(at.selectbox(key=f"elec_view_{meta['base']}").value,view)
                    at.radio(key='ui_language').set_value('it').run()

    def test_exploration_keeps_policy_values_and_ranking(self):
        import exploratory_config as cfg
        at = page('5_Analisi_Esplorativa.py')
        self.assert_ok(at)
        name=cfg.POLICY_ORDER[0]
        at.session_state[f'expl_pol_{name}']=cfg.POLICY_GRID[name][-1]
        at.run()
        before=at.dataframe[0].value.select_dtypes('number').to_numpy()
        at.radio(key='ui_language').set_value('en').run()
        self.assert_ok(at)
        self.assertEqual(at.session_state[f'expl_pol_{name}'],cfg.POLICY_GRID[name][-1])
        self.assertEqual(list(at.dataframe[0].value.columns),['Indicator','Unit','P10','Median','P90'])
        self.assertTrue((before==at.dataframe[0].value.select_dtypes('number').to_numpy()).all())
        at.session_state['expl_subpage']='Migliori policy mix'
        at.run()
        at.slider(key='expl_w_pv_self_coverage').set_value(.7).run()
        before=at.dataframe[0].value.select_dtypes('number').to_numpy()
        weights=[s.value for s in at.slider]
        at.radio(key='ui_language').set_value('it').run()
        self.assert_ok(at)
        self.assertEqual(weights,[s.value for s in at.slider])
        self.assertTrue((before==at.dataframe[0].value.select_dtypes('number').to_numpy()).all())
        at.radio(key='ui_language').set_value('en').run()
        self.assert_ok(at)
        self.assertIn('Cumulative cantonal spending (CHF million)',at.dataframe[0].value.columns)

    def test_methodology_all_steps(self):
        at=page('0_Approccio_System_Dynamics.py')
        for step in ['1 · Definizione del problema','2 · Modello qualitativo','3 · Modello quantitativo','4 · Calibrazione']:
            at.session_state['sd_step']=step
            at.run()
            self.assert_ok(at)
            before=metric_values(at)
            at.radio(key='ui_language').set_value('en').run()
            self.assert_ok(at)
            self.assertEqual(at.session_state['sd_step'],step)
            self.assertEqual(at.title[0].value,'Methodology')
            self.assertEqual(before,metric_values(at))
            if step.startswith('3'):
                at.session_state['sd_quant_view']='Consumi'
                at.run()
                self.assert_ok(at)
                self.assertTrue(any('Residential sector' in m.value for m in at.subheader))
            at.radio(key='ui_language').set_value('it').run()

    def test_live_language_switch_does_not_run_engine_or_reset_inputs(self):
        with patch('sure_live.get_engine') as engine:
            at=page('9_Esplora_SURE_PySD.py')
            self.assert_ok(at)
            at.select_slider(key='exp_PV rebate cantonal').set_value(.2).run()
            at.radio(key='exp_Energy Community scenario').set_value('Sì').run()
            at.selectbox(key='exp_MuKEn scenario').set_value('MoPEC 2025').run()
            at.radio(key='ui_language').set_value('en').run()
            self.assert_ok(at)
            self.assertEqual(at.title[0].value,'Live simulation')
            self.assertEqual(at.select_slider(key='exp_PV rebate cantonal').value,.2)
            self.assertEqual(at.radio(key='exp_Energy Community scenario').value,'Sì')
            self.assertEqual(at.selectbox(key='exp_MuKEn scenario').value,'MoPEC 2025')
            self.assertIn('Yes',at.radio(key='exp_Energy Community scenario').options)
            engine.assert_not_called()

    def test_dynamic_labels_and_display_frames_preserve_originals(self):
        raw=pd.DataFrame({'Indicatore':['Spesa cantonale cumulata'],'Unità':['Mio CHF'],'Mediana':[12.34]})
        with patch.object(i18n,'language',return_value='en'):
            shown=i18n.display_frame(raw)
            self.assertEqual(i18n.chart_text('Preparazione dei risultati: anno 2025 (fase 3/4)'), 'Preparing results: year 2025 (stage 3/4)')
            self.assertEqual(i18n.chart_text("Elettricita' dispacciata | cumulato dal 2011 per supplier"),'Electricity dispatched | cumulative since 2011 by source')
        self.assertEqual(raw.iloc[0,0],'Spesa cantonale cumulata')
        self.assertEqual(shown.iloc[0,0],'Cumulative cantonal spending')
        self.assertEqual(shown['Median'][0],raw['Mediana'][0])

if __name__=='__main__':unittest.main()
