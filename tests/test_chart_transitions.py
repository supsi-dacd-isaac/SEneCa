"""Regressions for transitions between Streamlit chart reruns."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pv_batteries"))

from echarts_charts import (  # noqa: E402
    _transition_compatible,
    build_line_options,
    build_pie_options,
    build_radar_options,
    render_echarts,
)


class ChartTransitionTests(unittest.TestCase):
    def test_changed_values_with_same_axes_can_transition(self) -> None:
        previous = build_line_options([2030, 2040], {"PV": [1, 2]}, unit="GWh")
        current = build_line_options([2030, 2040], {"PV": [3, 4]}, unit="GWh")
        self.assertTrue(_transition_compatible(previous, current))

    def test_changed_categories_or_series_cannot_transition(self) -> None:
        previous = build_line_options([2030, 2040], {"PV": [1, 2]}, unit="GWh")
        changed_years = build_line_options([2030, 2050], {"PV": [3, 4]}, unit="GWh")
        changed_series = build_line_options([2030, 2040], {"Hydro": [3, 4]}, unit="GWh")
        self.assertFalse(_transition_compatible(previous, changed_years))
        self.assertFalse(_transition_compatible(previous, changed_series))

    def test_pie_values_transition_but_changed_slices_do_not(self) -> None:
        previous = build_pie_options(["PV", "Hydro"], [1, 2])
        changed_values = build_pie_options(["PV", "Hydro"], [3, 4])
        changed_slices = build_pie_options(["PV", "Wind"], [3, 4])
        self.assertTrue(_transition_compatible(previous, changed_values))
        self.assertFalse(_transition_compatible(previous, changed_slices))

    def test_radar_values_transition_but_changed_indicators_do_not(self) -> None:
        previous = build_radar_options(["Costi", "PV", "CO2"], [1, 2, 3], [1, 1, 1])
        changed_values = build_radar_options(["Costi", "PV", "CO2"], [2, 3, 4], [1, 1, 1])
        changed_axes = build_radar_options(["Costi", "PV", "Import"], [2, 3, 4], [1, 1, 1])
        self.assertTrue(_transition_compatible(previous, changed_values))
        self.assertFalse(_transition_compatible(previous, changed_axes))

    def test_renderer_reuses_last_values_only_for_a_changed_chart(self) -> None:
        state: dict = {}
        previous = build_line_options([2030, 2040], {"PV": [1, 2]}, unit="GWh")
        current = build_line_options([2030, 2040], {"PV": [3, 4]}, unit="GWh")
        with (
            patch("echarts_charts.st.session_state", state),
            patch("echarts_charts.st.iframe") as iframe,
        ):
            render_echarts(previous, chart_key="test")
            self.assertIn("const previousOptions = null;", iframe.call_args.args[0])
            render_echarts(current, chart_key="test")
            self.assertNotIn("const previousOptions = null;", iframe.call_args.args[0])
            render_echarts(current, chart_key="test")
            self.assertIn("const previousOptions = null;", iframe.call_args.args[0])
            changed_years = build_line_options([2030, 2050], {"PV": [3, 4]}, unit="GWh")
            render_echarts(changed_years, chart_key="test")
            self.assertIn("const previousOptions = null;", iframe.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
