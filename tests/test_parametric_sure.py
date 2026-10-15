"""Parameter name and generated source boundaries are explicit and fail closed."""
import unittest

from sure_julia.translator.parameterize import resolve_name, rewrite_identifiers, replace_once


class ParameterTests(unittest.TestCase):
    def test_quoted_vensim_names_resolve_without_dropping_controls(self):
        self.assertEqual(resolve_name("Provvedimento 1.2", {'"Provvedimento 1.2"': 'provvedimento_12'}), '"Provvedimento 1.2"')
        self.assertEqual(resolve_name("pv rebate", {"PV rebate": "pv_rebate"}), "PV rebate")

    def test_unknown_and_ambiguous_controls_raise(self):
        for namespace in ({}, {"P": "one", '"P"': "two"}):
            with self.assertRaises(ValueError):
                resolve_name("p", namespace)

    def test_exact_name_has_precedence(self):
        self.assertEqual(resolve_name("P", {"P": "one", '"P"': "two"}), "P")

    def test_rewrite_does_not_change_labels_comments_or_longer_identifiers(self):
        source = '"fit" => c -> fit + fit_cost # fit\ntext = "escaped \\" fit"\n'
        expected = '"fit" => c -> c.parameters.fit + fit_cost # fit\ntext = "escaped \\" fit"\n'
        self.assertEqual(rewrite_identifiers(source, {"fit": "c.parameters.fit"}), expected)

    def test_source_contract_must_be_unique(self):
        self.assertEqual(replace_once("abc", "b", "X"), "aXc")
        for source in ("ac", "abbc"):
            with self.assertRaises(ValueError):
                replace_once(source, "b", "X")


if __name__ == "__main__":
    unittest.main()
