"""Preserve the pinned NumPy interpolation arithmetic for scalar lookup tables."""
from __future__ import annotations

import math


def interpolation_code(name, xs, ys, itp_type):
    from pysd.builders.julia.julia_expressions_builder import format_vector
    if itp_type not in {"interpolate", "extrapolate", "hold_backward"}:
        raise ValueError(f"Unverified lookup interpolation mode: {name}/{itp_type}")
    if (not xs or len(xs) != len(ys) or
            not all(math.isfinite(value) for value in (*xs, *ys)) or
            not all(a < b for a, b in zip(xs, xs[1:]))):
        raise ValueError(f"Invalid lookup grid: {name}")
    if itp_type == "extrapolate" and len(xs) < 2:
        raise ValueError(f"Linear extrapolation needs two points: {name}")
    return (
        f"const {name}_itp = SenecaNumpyLookup({format_vector(xs)}, "
        f"{format_vector(ys)}, :{itp_type})",
        f"{name}(x) = {name}_itp(x)",
        f"@register_symbolic {name}(x::Real)",
    )


def apply():
    from pysd.builders.julia import julia_model_builder as models
    from pysd.builders.julia import julia_expressions_builder as expressions
    if getattr(models.JuliaSectionBuilder, "_seneca_numpy_lookup_applied", False):
        return
    models.JuliaSectionBuilder._seneca_numpy_lookup_applied = True
    models.lookup_interpolation_code = interpolation_code
    expressions.lookup_interpolation_code = interpolation_code
    original = models.JuliaSectionBuilder._full_file_content

    def content(self, equations):
        from .common import CONFIG
        tables = [line.split()[1] for line in self.lookup_const_decls
                  if " = SenecaNumpyLookup(" in line]
        self._seneca_numpy_lookup = {
            "tables": tables, "count": len(tables),
            "semantics": "pinned NumPy interp: rounded slope, fused multiply-add, exact knots and constant boundaries",
        }
        return (CONFIG / "lookup.jl").read_text() + "\n" + original(self, equations)
    models.JuliaSectionBuilder._full_file_content = content
