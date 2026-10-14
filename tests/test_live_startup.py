"""Process startup and UI must own the same compiled engine."""
from concurrent.futures import ThreadPoolExecutor
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch

from sure_julia.common import ROOT
from sure_live import get_engine


def fake_engine(backend="julia"):
    return Mock(backend=backend, process=Mock(pid=1234),
                last_timing={"compilation_seconds": 5.})


class LiveStartupTests(unittest.TestCase):
    def setUp(self):
        get_engine.clear()

    def tearDown(self):
        get_engine.clear()

    def test_concurrent_sessions_share_one_warmed_worker(self):
        engine = fake_engine()
        with patch("sure_live.backend.load_model", return_value=engine) as load:
            with ThreadPoolExecutor(4) as pool:
                results = list(pool.map(get_engine, ["model-and-data-identity"]*4))
            self.assertTrue(all(result is engine for result in results))
            load.assert_called_once()
            engine.run.assert_called_once()
            self.assertEqual(engine.warmup["worker_pid"], 1234)
            self.assertIs(get_engine("model-and-data-identity"), engine)
            get_engine.clear()
            engine.close.assert_called_once()

    def test_failed_warmup_is_closed_and_not_cached(self):
        failed, recovered = fake_engine(), fake_engine()
        failed.run.side_effect = RuntimeError("Compilation failed")
        with patch("sure_live.backend.load_model", side_effect=[failed, recovered]):
            with self.assertRaisesRegex(RuntimeError, "Compilation failed"):
                get_engine("identity")
            failed.close.assert_called_once()
            self.assertIs(get_engine("identity"), recovered)
            recovered.run.assert_called_once()

    def test_python_does_not_run_julia_warmup(self):
        engine = fake_engine("python")
        with patch("sure_live.backend.load_model", return_value=engine):
            self.assertIs(get_engine("python-identity"), engine)
            engine.run.assert_not_called()

    def test_actual_server_lifespan_precedes_health_without_browser_session(self):
        # A separate process gives st.App its own real Streamlit runtime.
        # TestClient drives ASGI startup, without opening a browser session.
        script = '''
import threading
from unittest.mock import Mock, patch
from starlette.testclient import TestClient
from server import app
from sure_live import get_engine
started, release, ready = threading.Event(), threading.Event(), threading.Event()
engine = Mock(backend="julia", process=Mock(pid=1234), last_timing={"compilation_seconds": 5.})
def run(**kwargs):
    started.set()
    assert release.wait(10)
engine.run.side_effect = run
errors = []
def serve():
    try:
        with TestClient(app) as client:
            assert engine.run.call_count == 1
            assert get_engine("identity") is engine
            assert client.get("/_stcore/health").status_code == 200
            ready.set()
    except BaseException as error:
        errors.append(error)
with patch("sure_live.backend.load_model", return_value=engine), patch("sure_backend.engine_identity", return_value="identity"):
    thread = threading.Thread(target=serve)
    thread.start()
    assert started.wait(10)
    assert not ready.is_set()
    release.set()
    thread.join(15)
    assert not thread.is_alive()
    assert not errors, errors
    assert ready.is_set()
    engine.close.assert_called_once()
'''
        result = subprocess.run([sys.executable, "-c", script], cwd=ROOT, capture_output=True, text=True, timeout=40)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
