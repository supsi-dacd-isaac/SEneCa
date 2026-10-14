"""Streamlit server lifecycle: compile SURE before reporting readiness."""
from contextlib import asynccontextmanager
import logging
from pathlib import Path

import anyio
import streamlit as st

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app):
    # Import after Streamlit's runtime is started. The page imports this exact
    # cached factory, so it reuses the warmed worker across browser sessions.
    import sure_backend as backend
    from sure_live import get_engine

    try:
        await anyio.to_thread.run_sync(lambda: get_engine(backend.engine_identity()))
        yield
    finally:
        get_engine.clear()


app = st.App(Path(__file__).with_name("app.py"), lifespan=lifespan)
