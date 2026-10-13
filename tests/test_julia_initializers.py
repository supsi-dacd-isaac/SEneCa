"""Prove compact stock initialization keeps every original cell expression."""
import itertools
import unittest

from scripts.julia_repro.ode_patch import _initial_template, _stock_initializer


def cells(shape):
    return sorted(itertools.product(*(range(1, size + 1) for size in shape)),
                  key=lambda cell: tuple(reversed(cell)))


class InitializerTests(unittest.TestCase):
    def test_permuted_indices_and_constants_round_trip(self):
        entries = [(cell, f"source[{cell[1]}, {cell[0]}] * 0.5 + constant[2]") for cell in cells((3, 4))]
        template = _initial_template(entries)
        self.assertEqual(template, "source[__seneca_init_i1, __seneca_init_i0] * 0.5 + constant[2]")
        for cell, expression in entries:
            rebuilt = template.replace("__seneca_init_i0", str(cell[0])).replace("__seneca_init_i1", str(cell[1]))
            self.assertEqual(rebuilt, expression)

    def test_uniform_literal_uses_fill(self):
        entries = [(cell, "0.0") for cell in cells((8, 11, 5, 3, 2))]
        statements, helpers = _stock_initializer("stock", entries, (8, 11, 5, 3, 2), set())
        self.assertEqual(statements[-1], "fill!(stock, 0.0)")
        self.assertEqual(helpers, [])
        self.assertEqual(len(statements), 2)

    def test_uniform_function_preserves_per_cell_evaluation(self):
        entries = [(cell, "random_value()") for cell in cells((2, 3))]
        statements, helpers = _stock_initializer("stock", entries, (2, 3), set())
        self.assertIn("for __seneca_init_i1 in 1:3, __seneca_init_i0 in 1:2", statements)
        self.assertIn("    stock[__seneca_init_i0, __seneca_init_i1] = random_value()", statements)
        self.assertEqual(helpers, [])

    def test_irregular_values_use_bounded_exact_kernels(self):
        entries = [(cell, repr((index * index % 17) / 13.0)) for index, cell in enumerate(cells((12, 11)))]
        self.assertIsNone(_initial_template(entries))
        statements, helpers = _stock_initializer("stock", entries, (12, 11), set())
        self.assertEqual(len(statements), 4)
        text = "\n".join(helpers)
        kernels = text.split("@noinline function ")[1:]
        self.assertEqual(len(kernels), 3)
        self.assertEqual([kernel.count("    target[") for kernel in kernels], [64, 64, 4])
        for cell, expression in entries:
            self.assertIn(f"target[{', '.join(map(str, cell))}] = {expression}", text)


if __name__ == "__main__":
    unittest.main()
