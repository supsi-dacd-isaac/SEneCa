"""Calendar-dependent layouts require complete and unambiguous observations."""
from copy import deepcopy
import unittest

from scripts.julia_repro.reduction_policy import calendar_plan


def records():
    common = {"dims": ["District!", "Vehicle"], "shape": [8, 7],
              "reduce_axes": [0], "finite_input": True}
    return [{**common, "physical_axes_slow_to_fast": [1, 0],
             "observations": {"Initialization:2011": 1, "Run:2011": 1}},
            {**common, "physical_axes_slow_to_fast": [0, 1],
             "observations": {"Run:2012": 1, "Run:2013": 1}}]


class CalendarReductionTests(unittest.TestCase):
    def test_initial_and_remaining_annual_grid_are_bound_to_distinct_plans(self):
        plan = calendar_plan({"base": records(), "high": records()}, [2011, 2012, 2013])
        self.assertEqual(plan["initial_time"], 2011)
        self.assertEqual(plan["initial"]["blocksize"], 8)
        self.assertEqual(plan["subsequent"]["blocksize"], 1)

    def test_missing_year_is_rejected(self):
        value = records()
        del value[1]["observations"]["Run:2012"]
        with self.assertRaisesRegex(ValueError, "Incomplete"):
            calendar_plan({"base": value}, [2011, 2012, 2013])

    def test_different_layouts_at_same_year_are_rejected(self):
        value = records()
        value[1]["observations"]["Run:2011"] = 1
        with self.assertRaisesRegex(ValueError, "Ambiguous"):
            calendar_plan({"base": value}, [2011, 2012, 2013])

    def test_later_layout_change_is_rejected(self):
        value = records()
        del value[1]["observations"]["Run:2013"]
        extra = deepcopy(value[0])
        extra["observations"] = {"Run:2013": 1}
        value.append(extra)
        with self.assertRaisesRegex(ValueError, "after the first"):
            calendar_plan({"base": value}, [2011, 2012, 2013])

    def test_scenario_disagreement_is_rejected(self):
        value = records()
        value[0]["physical_axes_slow_to_fast"] = [0, 1]
        with self.assertRaisesRegex(ValueError, "between scenarios"):
            calendar_plan({"base": records(), "high": value}, [2011, 2012, 2013])


if __name__ == "__main__":
    unittest.main()
