"""One shared live engine, warmed before the server accepts user sessions."""
import logging
import time

import streamlit as st

import sure_backend as backend
from sure_pysd import OUTPUTS

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


@st.cache_resource(show_spinner=False, max_entries=1,
                   on_release=lambda engine: engine.close())
def get_engine(engine_id: str):
    engine = backend.load_model()
    try:
        if engine.backend == "julia":
            logger.info("Warming the Julia worker before accepting simulations")
            started = time.perf_counter()
            # Exercise the complete live path, including initialization, annual
            # integration, physical checks and labelled output extraction. The
            # next request resets the model and keeps this compiled process.
            engine.run(outputs=OUTPUTS, flatten=True)
            engine.warmup = {"seconds": time.perf_counter()-started,
                             "worker_pid": engine.process.pid,
                             "timing": dict(engine.last_timing)}
            logger.info("Julia worker ready: pid=%s, warmup=%.3fs, compilation=%.3fs",
                        engine.warmup["worker_pid"], engine.warmup["seconds"],
                        engine.last_timing["compilation_seconds"])
        return engine
    except BaseException:
        engine.close()
        raise
