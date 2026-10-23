"""Presentation-only wrapping layouts for KPI cards and chart panels."""
import streamlit as st


def apply_responsive_styles():
    st.html("""<style>
    [class*="st-key-responsive_charts_"] > [data-testid="stLayoutWrapper"] {
        flex: 1 1 420px; min-width: min(420px, 100%); width: auto;
    }
    [class*="st-key-responsive_metrics_"] > [data-testid="stLayoutWrapper"] {
        flex: 1 1 250px; min-width: min(250px, 100%); width: auto;
    }
    [data-testid="stMetricLabel"] p, [data-testid="stMetricDelta"] > div {
        white-space: normal; overflow: visible; text-overflow: clip;
        overflow-wrap: anywhere;
    }
    [data-testid="stMetricValue"] {
        font-size: clamp(1.5rem, 2.3vw, 2rem);
        white-space: normal; overflow-wrap: anywhere; text-overflow: clip;
    }
    @media (max-width: 900px) {
        .stMainBlockContainer { padding-left: 1.25rem; padding-right: 1.25rem; }
    }
    </style>""")


def wrapping_columns(count, *, key, metrics=False):
    """Native containers wrap based on available panel width, including zoom."""
    kind = "metrics" if metrics else "charts"
    with st.container(horizontal=True, key=f"responsive_{kind}_{key}"):
        return [st.container(width="stretch") for _ in range(count)]
