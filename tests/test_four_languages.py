from pathlib import Path
import sys, unittest, string, gettext
from unittest.mock import patch
from babel.messages.pofile import read_po
from streamlit.testing.v1 import AppTest
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'pv_batteries')]
from pv_batteries import i18n

class FourLanguageTests(unittest.TestCase):
    def test_catalogs_cover_the_same_messages_and_preserve_placeholders(self):
        catalogs={}
        for lang in ('en','fr','de'):
            with (ROOT/f'locales/{lang}/LC_MESSAGES/seneca.po').open('rb') as f:catalogs[lang]=read_po(f)
        expected={m.id for m in catalogs['en'] if m.id}
        for lang,c in catalogs.items():
            self.assertEqual(expected,{m.id for m in c if m.id})
            for m in c:
                if not m.id:continue
                self.assertTrue(m.string,(lang,m.id))
                self.assertNotIn('fuzzy',m.flags)
                fields=lambda v:{name for _,name,_,_ in string.Formatter().parse(v) if name is not None}
                self.assertEqual(fields(m.id),fields(m.string),(lang,m.id))
                self.assertFalse(any(ord(x)<32 and x!='\n' for x in m.string),(lang,m.id))
            translator=gettext.translation('seneca',ROOT/'locales',languages=[lang])
            self.assertNotEqual(translator.gettext('Veicoli'),'Veicoli')

    def test_every_page_renders_in_french_and_german(self):
        for file in sorted((ROOT/'pages').glob('*.py')):
            for lang in ('fr','de'):
                with self.subTest(page=file.name,language=lang),patch('sure_live.get_engine') as engine:
                    script=f"import streamlit as st\nimport runpy\nst.session_state['ui_language']={lang!r}\nrunpy.run_path({str(file)!r})"
                    app=AppTest.from_string(script,default_timeout=90).run()
                    self.assertFalse(app.exception,[x.message for x in app.exception])
                    self.assertFalse(app.error,[x.value for x in app.error])
                    engine.assert_not_called()

    def test_live_switch_preserves_inputs_without_running_engine(self):
        script=f"import runpy\nfrom pv_batteries.i18n import language_selector\nlanguage_selector()\nrunpy.run_path({str(ROOT/'pages/9_Esplora_SURE_PySD.py')!r})"
        with patch('sure_live.get_engine') as engine:
            app=AppTest.from_string(script,default_timeout=60).run()
            app.select_slider(key='exp_PV rebate cantonal').set_value(.2).run()
            for lang in ('fr','de','it','en'):
                app.radio(key='ui_language').set_value(lang).run()
                self.assertFalse(app.exception)
                self.assertEqual(app.select_slider(key='exp_PV rebate cantonal').value,.2)
                engine.assert_not_called()
