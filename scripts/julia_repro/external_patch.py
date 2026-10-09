"""Strict, rank-independent external inputs for the experimental Julia backend.

Loading uses the pinned PySD external reader, then serializes each labelled cell
explicitly. Julia never infers coordinate order from an array's storage layout.
"""
from __future__ import annotations

import itertools
import json
import re

import numpy as np


def _coordinates(builder, elem, components):
    dims = builder._element_dims(elem)
    final = {name: list(builder._subs_elems[name]) for name, _ in dims}
    covered = set()
    coordinates = []
    for comp in components:
        specs, excluded = comp.subscripts
        if excluded:
            raise ValueError(f"External input EXCEPT needs explicit file cell mapping: {elem.name}")
        if len(specs) != len(final):
            raise ValueError(f"External input rank mismatch: {elem.name}")
        coords = {}
        for (dim, labels), spec in zip(final.items(), specs):
            selected = list(builder._subs_elems.get(spec, [spec]))
            if not selected or not set(selected) <= set(labels):
                raise ValueError(f"Unknown external coordinates: {elem.name}/{dim}/{spec}")
            coords[dim] = selected
        cells = set(itertools.product(*coords.values()))
        if covered & cells:
            raise ValueError(f"Overlapping external input cells: {elem.name}")
        covered.update(cells)
        coordinates.append(coords)
    if covered != set(itertools.product(*final.values())):
        raise ValueError(f"Unassigned external input cells: {elem.name}")
    return final, coordinates


def _serialize(builder, identifier, data, axis, final, mode):
    """Serialize a grid as explicit 1-based coordinate tuples and series."""
    if mode not in {"interpolate", "hold_backward", "look_forward", "raw", "extrapolate"}:
        raise ValueError(f"Unsupported interpolation {mode!r}: {identifier}")
    if set(data.dims) != {axis, *final}:
        raise ValueError(f"Unexpected external input dimensions: {identifier}/{data.dims}")
    data = data.transpose(axis, *final).sel(final)
    xs = np.asarray(data.coords[axis], dtype=np.float64)
    if not len(xs) or not np.isfinite(xs).all() or not np.all(np.diff(xs) > 0):
        raise ValueError(f"Invalid external input grid: {identifier}")
    arr = np.asarray(data.values, dtype=np.float64)
    if not np.isfinite(arr).all():
        raise ValueError(f"Nonfinite/unassigned external input values: {identifier}")
    records = []
    for cell in itertools.product(*(range(len(labels)) for labels in final.values())):
        records.append({"indices": [i + 1 for i in cell],
                        "values": arr[(slice(None), *cell)].tolist()})
    spec = {"dimensions": list(final), "coordinates": final, "time": xs.tolist(),
            "interpolation": mode, "series": records}
    builder._json_data.setdefault("external", {})[identifier] = spec
    if builder.data_format != "json":
        raise ValueError("The verified external input patch requires data_format='json'")
    quoted = json.dumps(identifier)
    builder.lookup_const_decls.append(
        f"const {identifier}_external = seneca_external_grid(_model_data[\"external\"][{quoted}])")
    indices = [f"i{k}::Integer" for k in range(len(final))]
    arguments = [f"i{k}" for k in range(len(final))]
    tuple_expr = "(" + ", ".join(arguments) + ("," if len(arguments) == 1 else "") + ")"
    signature = ", ".join([*indices, "x::Real"])
    builder.lookup_func_decls.append(
        f"{identifier}({signature}) = seneca_external_value({identifier}_external, x, {tuple_expr})")
    builder.lookup_register_decls.append(f"@register_symbolic {identifier}({signature})")
    builder.lookup_identifiers.add(identifier)
    builder._lookup_func_names.add(identifier)
    builder._var_dims[identifier] = list(final)
    return []


def _data(self, elem, identifier, comp):
    from pysd.py_backend.external import ExtData
    from pysd.translators.structures.abstract_expressions import GetDataStructure
    if not all(isinstance(c.ast, GetDataStructure) for c in elem.components):
        raise ValueError(f"Mixed external input/equation definitions: {elem.name}")
    final, coordinates = _coordinates(self, elem, elem.components)
    first = elem.components[0]
    mode = getattr(first, "keyword", None) or "interpolate"
    ast = first.ast
    ext = ExtData(ast.file, ast.tab, ast.time_row_or_col, ast.cell, mode,
                  coordinates[0], self.root, final, identifier)
    for item, coords in zip(elem.components[1:], coordinates[1:]):
        ast = item.ast
        ext.add(ast.file, ast.tab, ast.time_row_or_col, ast.cell,
                getattr(item, "keyword", None) or "interpolate", coords)
    ext.initialize()
    return _serialize(self, identifier, ext.data, "time", final, mode)


def _lookups(self, elem, identifier):
    from pysd.py_backend.external import ExtLookup
    final, coordinates = _coordinates(self, elem, elem.components)
    ast = elem.components[0].ast
    ext = ExtLookup(ast.file, ast.tab, ast.x_row_or_col, ast.cell,
                    coordinates[0], self.root, final, identifier)
    for item, coords in zip(elem.components[1:], coordinates[1:]):
        ast = item.ast
        ext.add(ast.file, ast.tab, ast.x_row_or_col, ast.cell, coords)
    ext.initialize()
    return _serialize(self, identifier, ext.data, "lookup_dim", final, "interpolate")


def _inline(self, elem, identifier):
    from pysd.py_backend.lookups import HardcodedLookups
    final, coordinates = _coordinates(self, elem, elem.components)
    ast = elem.components[0].ast
    ext = HardcodedLookups(list(ast.x), list(ast.y), coordinates[0], ast.type, final, identifier)
    for item, coords in zip(elem.components[1:], coordinates[1:]):
        ast = item.ast
        if ast.type != ext.interp:
            raise ValueError(f"Mixed inline lookup interpolation: {elem.name}")
        ext.add(list(ast.x), list(ast.y), coords)
    ext.initialize()
    return _serialize(self, identifier, ext.data, "lookup_dim", final, ext.interp)


def apply():
    from pysd.builders.julia.julia_model_builder import JuliaSectionBuilder
    from pysd.builders.julia.julia_expressions_builder import JuliaASTVisitor
    if getattr(JuliaSectionBuilder, "_seneca_external_applied", False):
        return
    JuliaSectionBuilder._seneca_external_applied = True
    original_content = JuliaSectionBuilder._full_file_content
    original_reference = JuliaASTVisitor._reference

    def content(self, equations):
        from .common import CONFIG
        return (CONFIG / "external_data.jl").read_text() + "\n" + original_content(self, equations)

    def lookup_block(self):
        # Upstream JSON mode discards subscript dispatch and interpolation modes.
        # All declarations already have valid constructors; external grids alone
        # read their explicit labelled values from the adjacent JSON file.
        lines = [*self.lookup_const_decls, *self.lookup_func_decls]
        if self.backend == "mtk":
            lines += self.lookup_register_decls
        return "\n".join(lines) + "\n\n" if lines else ""

    def reference(self, node):
        expression = original_reference(self, node)
        name = self.namespace.get(node.reference)
        if name in self.lookup_names:
            # The upstream bang/SUM branch emits data[i,j], although these are
            # input functions. Keep its resolved indices and supply current time.
            expression = re.sub(rf"\b{re.escape(name)}\[([^\[\]]+)\]",
                                lambda m: f"{name}({m[1]}, t)", expression)
        return expression

    JuliaSectionBuilder._process_get_data = _data
    JuliaSectionBuilder._process_get_lookups = _lookups
    JuliaSectionBuilder._process_subscripted_inline_lookup = _inline
    JuliaSectionBuilder._lookup_block = lookup_block
    JuliaSectionBuilder._full_file_content = content
    JuliaASTVisitor._reference = reference
