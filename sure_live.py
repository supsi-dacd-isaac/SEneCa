"""One shared live engine, warmed before the server accepts user sessions."""
import logging
import time
from contextvars import copy_context

import streamlit as st

import sure_backend as backend
from sure_pysd import LIVE_OUTPUTS as OUTPUTS

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
            engine.run(outputs=OUTPUTS, flatten=True, on_progress=lambda event: None)
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


def run_with_progress(operation, scenario="Scenario"):
    """Keep transient UI updates outside the cached result's replay context."""
    from sure_julia.progress import label
    bar = st.progress(0., text=f"{scenario}: in attesa della simulazione…")
    context = copy_context()
    def update(event):
        bar.progress(event["value"], text=f"{scenario}: {label(event)}")
    try:
        return operation(lambda event: context.run(update, event))
    finally:
        bar.empty()
