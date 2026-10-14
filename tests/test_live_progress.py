"""Stream progress without weakening request isolation, caching or timeouts."""
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import numpy as np
import streamlit as st
from streamlit.testing.v1 import AppTest

from sure_julia.common import MODEL_REVISION, digest, dump
from sure_julia.progress import worker_event, label
from sure_julia.runtime import JuliaBackend


WORKER = '''
import json, pathlib, struct, time
print(json.dumps({'ready': True}), flush=True)
for line in __import__('sys').stdin:
    job=json.loads(line)
    def event(phase, completed=0, total=1, year=0):
        print(json.dumps({'event':'progress','id':job['id'],'phase':phase,
                          'completed':completed,'total':total,'year':year}),flush=True)
    if job.get('progress'):
        event('initialize')
        {extra}
        event('integrate')
        event('extract', total=40)
        for n in range(1,41): event('extract', n, 40, 2010+n)
    pathlib.Path(job['directory'], 'v0000.bin').write_bytes(struct.pack('<40d', *range(40)))
    print(json.dumps({'id':job['id'],'ok':True,'years':list(range(2011,2051))}),flush=True)
'''


class ProgressTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root/'model.jl').write_text('')
        dump(self.root/'build.json', {'complete':True, 'model':'model.jl', 'model_revision':MODEL_REVISION,
                                     'artifacts':{'model.jl':digest(self.root/'model.jl')}})
        dump(self.root/'export.json', [{'name':'X','dims':[],'coords':{}}])
        self.worker = self.root/'worker'
        self.make_worker()
        self.engine = JuliaBackend(self.root, timeout=2)
        self.env = patch.dict(os.environ, {'SURE_JULIA_BIN':str(self.worker)})
        self.env.start()
        self.outputs = patch('sure_julia.physical.OUTPUTS', [])
        self.outputs.start()
        self.physical = patch('sure_julia.physical.check', return_value={'pass':True})
        self.physical.start()

    def tearDown(self):
        self.engine.close()
        self.physical.stop()
        self.outputs.stop()
        self.env.stop()
        self.temporary.cleanup()
        st.cache_data.clear()

    def make_worker(self, extra='pass'):
        self.worker.write_text(f'#!{sys.executable}\n' + WORKER.replace('{extra}', extra))
        self.worker.chmod(0o700)

    def test_events_leave_results_and_following_requests_unchanged(self):
        events = []
        first = self.engine.run_arrays(on_progress=events.append)
        pid = self.engine.process.pid
        second = self.engine.run_arrays()
        np.testing.assert_array_equal(first['X'], second['X'])
        self.assertEqual(pid, self.engine.process.pid)
        self.assertEqual(len(events), 45)
        self.assertEqual(events[-1], {'phase':'complete','value':1.})
        self.assertEqual([e['value'] for e in events], sorted(e['value'] for e in events))
        self.assertEqual([e['year'] for e in events if e.get('year')], list(range(2011,2051)))

    def test_callback_failure_discards_worker_and_next_request_recovers(self):
        def fail(event):
            raise RuntimeError('Cancelled UI')
        with self.assertRaisesRegex(RuntimeError, 'Cancelled UI'):
            self.engine.run_arrays(on_progress=fail)
        self.assertIsNone(self.engine.process)
        np.testing.assert_array_equal(self.engine.run_arrays()['X'], np.arange(40))

    def test_concurrent_requests_keep_their_own_progress_streams(self):
        events = [[], []]
        with ThreadPoolExecutor(2) as pool:
            futures = [pool.submit(self.engine.run_arrays, on_progress=stream.append) for stream in events]
            results = [future.result() for future in futures]
        self.assertEqual([len(stream) for stream in events], [45, 45])
        self.assertTrue(all(stream[-1]['phase'] == 'complete' for stream in events))
        np.testing.assert_array_equal(results[0]['X'], results[1]['X'])

    def test_continuous_progress_cannot_extend_request_timeout(self):
        self.make_worker("while True: event('initialize'); time.sleep(.005)")
        self.engine._start()
        self.engine.timeout = .05
        started = time.monotonic()
        with self.assertRaises(TimeoutError):
            self.engine.run_arrays(on_progress=lambda event: None)
        self.assertLess(time.monotonic()-started, 6.)  # Includes worker cleanup.
        self.assertIsNone(self.engine.process)

    def test_bad_events_fail_instead_of_displaying_invented_progress(self):
        valid = {'phase':'extract','completed':1,'total':40,'year':2011}
        self.assertEqual(worker_event(valid)['value'], .50625)
        for changes in [{'phase':'unknown'}, {'year':2012}, {'total':39}, {'completed':1.5}, {'completed':41}]:
            with self.assertRaises(RuntimeError):
                worker_event({**valid, **changes})
        self.make_worker("job['id'] += 1")
        with self.assertRaisesRegex(RuntimeError, 'request identifier'):
            self.engine.run_arrays(on_progress=lambda event: None)
        self.assertIsNone(self.engine.process)

    def test_cached_results_do_not_replay_transient_progress_ui(self):
        script = '''
import streamlit as st
from sure_live import run_with_progress
@st.cache_data(show_spinner=False)
def compute(value, _progress):
    _progress({'phase':'integrate','value':.25})
    _progress({'phase':'complete','value':1.})
    return value
result=run_with_progress(lambda progress: compute(7, progress))
st.write(result)
'''
        with patch('sure_julia.progress.label', wraps=label) as render:
            app = AppTest.from_string(script).run()
            self.assertFalse(app.exception)
            self.assertEqual(render.call_count, 2)
            app.run()
            self.assertFalse(app.exception)
            self.assertEqual(render.call_count, 2)
            self.assertFalse(app.get('progress'))


if __name__ == '__main__':
    unittest.main()
