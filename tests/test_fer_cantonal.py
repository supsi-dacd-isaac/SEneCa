"""Evaluate the native FER equations in isolation, without running SURE scenarios.

PySD translates the actual Vensim blocks. Inputs are controlled and residential
arrays are reduced to one cell. The existing app runtime is deliberately untouched
until the corrected native model has been recalibrated.
"""
from pathlib import Path
import re
import tempfile
import unittest

import pysd


ROOT = Path(__file__).resolve().parents[1]
SOURCES = ("SURE.mdl", "SURE_pysd_v7.mdl")
CATEGORIES = ("30 - 100 kW", "> 100 kW")
RESIDENTIAL = "PV cantonal subsidy"
TARGETS = (RESIDENTIAL,) + tuple(f"PV cantonal subsidy {c} check" for c in CATEGORIES)


def block(source, name):
    """Return one equation, including units/comment, from the native source."""
    pattern = rf'(?m)^"?{re.escape(name)}"?(?:\[District,Type\])?\s*=.*?\|'
    matches = re.findall(pattern, source, re.S)
    if len(matches) != 1:
        raise ValueError(f"Expected one equation for {name}, found {len(matches)}")
    return matches[0]


def isolated_model(source, directory, stem):
    definitions = [block(source, name).replace("[District,Type]", "") for name in TARGETS]
    inputs = {
        "PV federal subsidy check": 9000,
        "PV initial cantonal subsidy": 1234,
        "Exploratory analysis": 0,
        "Cantonal PV support": 1,
        "PV rebate cantonal": 0.1,
    }
    for category in CATEGORIES:
        inputs.update({
            f"PV federal subsidy {category} check": 9000,
            f"Average power PV {category}": 60,
            f"PV {category} investment cost Time adj": 100000,
        })
    for name, value in inputs.items():
        lhs = f'"{name}"' if any(c in name for c in ">-") else name
        definitions.append(f"{lhs} = {value} ~~|")
    definitions += [f"{name} = {value} ~ year ~|" for name, value in {
        "INITIAL TIME": 2011, "FINAL TIME": 2050, "TIME STEP": 1, "SAVEPER": "TIME STEP",
    }.items()]
    path = Path(directory) / f"{stem}.mdl"
    path.write_text("{UTF-8}\n" + "\n".join(definitions), encoding="utf-8")
    return pysd.read_vensim(path)


def evaluate(model, year, power, ru, category=None, **controls):
    inputs = {"PV federal subsidy check": ru, **controls}
    for c in CATEGORIES:
        inputs[f"PV federal subsidy {c} check"] = ru
        inputs[f"Average power PV {c}"] = power
    namespace = {name.strip('"'): identifier for name, identifier in model.namespace.items()}
    model.set_components({namespace[name]: value for name, value in inputs.items()})
    model.time.update(year)
    model.clean_caches()
    name = RESIDENTIAL if category is None else f"PV cantonal subsidy {category} check"
    return float(getattr(model.components, namespace[name])())


class CantonalFERTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.models = []
        for i, name in enumerate(SOURCES):
            source = (ROOT / "Vensim" / name).read_bytes().decode("latin-1")
            cls.models.append(isolated_model(source, cls.temporary.name, f"fer_{i}"))

    def test_pre_change_includes_2021(self):
        for model in self.models:
            for year in (2011, 2020, 2021, 2021.999):
                for power in (20, 30, 60, 100, 300):
                    for category in ((None,) if power < 30 else (None, *CATEGORIES)):
                        with self.subTest(year=year, power=power, category=category):
                            self.assertAlmostEqual(evaluate(model, year, power, 12000, category), 4000)

    def test_2022_through_2025_rates_and_threshold(self):
        # Controlled RU = CHF 300/kW, not a change to the federal tariff model.
        cases = [(20, None, 3000), (30, None, 4500)]
        for c in CATEGORIES:
            cases += [(30, c, 4500), (60, c, 7500), (100, c, 11500), (300, c, 31500)]
        for model in self.models:
            for year in (2022, 2023, 2024, 2025, 2025.999):
                for power, category, expected in cases:
                    with self.subTest(year=year, power=power, category=category):
                        self.assertAlmostEqual(evaluate(model, year, power, 300 * power, category), expected)

    def test_continuity_with_the_same_federal_input(self):
        for model in self.models:
            for c in CATEGORIES:
                below = evaluate(model, 2022, 30 - 1e-6, 300 * (30 - 1e-6))
                at = evaluate(model, 2022, 30, 9000, c)
                above = evaluate(model, 2022, 30 + 1e-6, 300 * (30 + 1e-6), c)
                self.assertAlmostEqual(at, 4500)
                self.assertLess(abs(below - at), .001)
                self.assertLess(abs(above - at), .001)

    def test_historical_cap_only_for_target_nonresidential_equations(self):
        for model in self.models:
            for c in CATEGORIES:
                for year in (2020, 2021, 2022, 2025):
                    self.assertEqual(evaluate(model, year, 300, 2000000, c), 250000)
                    self.assertEqual(evaluate(model, year, 300, 0, c), 0)

    def test_2026_branch_is_not_capped_or_changed(self):
        for model in self.models:
            for year in (2026, 2030, 2050):
                self.assertEqual(evaluate(model, year, 20, 999999,
                                         **{"PV initial cantonal subsidy": 345678}), 345678)
                for c in CATEGORIES:
                    for exploratory, support, rebate, expected in (
                        (0, 7, .4, 400000), (1, 0, .4, 0), (1, 3, .4, 300000),
                    ):
                        actual = evaluate(model, year, 300, 999999, c, **{
                            "Exploratory analysis": exploratory,
                            "Cantonal PV support": support,
                            "PV rebate cantonal": rebate,
                            f"PV {c} investment cost Time adj": 1000000,
                        })
                        self.assertAlmostEqual(actual, expected)

    def test_both_native_sources_have_identical_fer_equations(self):
        sources = [(ROOT / "Vensim" / name).read_bytes().decode("latin-1") for name in SOURCES]
        for name in TARGETS:
            self.assertEqual(block(sources[0], name), block(sources[1], name))
            self.assertEqual(block(sources[0], name).split("~")[1].strip(), "CHF")


if __name__ == "__main__":
    unittest.main()
