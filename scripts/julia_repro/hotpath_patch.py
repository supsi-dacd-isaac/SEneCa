"""Preserve the current Python webapp's eight optimized HS normalizations.

The Python implementation zeros excluded HS cells before its axis-1 sum. The
original Vensim expressions sum all cells and subtract exclusions instead.
Those are algebraically equivalent but do not have the same Float64 rounding.
"""
from __future__ import annotations

HOTPATH_DIMS = ["District", "HS", "Performance", "Type", "PVpanel"]
HOTPATHS = {
    "Market Share HS": ("Utility HS exp 3", ()),
    "Market Share HS no incentives": ("Utility HS exp 3 no incentives", ()),
    "Market Share HS noGas": ("Market Share HS", ("WithGas",)),
    "Market Share HS noDH": ("Market Share HS", ("DH",)),
    "Market Share HS noDH noGas": ("Market Share HS noDH", ("WithGas",)),
    "Market Share HS no incentives noGas": ("Market Share HS no incentives", ("WithGas",)),
    "Market Share HS no incentives noDH": ("Market Share HS no incentives", ("DH",)),
    "Market Share HS no incentives noDH noGas": ("Market Share HS no incentives noDH", ("WithGas",)),
}


def apply():
    from pysd.builders.julia.julia_model_builder import JuliaSectionBuilder
    if getattr(JuliaSectionBuilder, "_seneca_hotpath_applied", False):
        return
    JuliaSectionBuilder._seneca_hotpath_applied = True
    original_process = JuliaSectionBuilder._process_element
    original_content = JuliaSectionBuilder._full_file_content

    def process(self, elem, identifier, is_control=False):
        if elem.name not in HOTPATHS:
            return original_process(self, elem, identifier, is_control)
        source_name, exclude = HOTPATHS[elem.name]
        source = self.namespace.get(source_name)
        dims = self._element_dims(elem)
        if is_control or [dim for dim, _ in dims] != HOTPATH_DIMS:
            raise ValueError(f"Unexpected Python HS hotpath dimensions: {elem.name}/{dims}")
        if source is None or self._var_dims.get(source) != HOTPATH_DIMS:
            raise ValueError(f"Unresolved/misaligned Python HS hotpath source: {source_name}")
        labels = self._subs_elems["HS"]
        excluded_labels = [label for group in exclude for label in self._subs_elems.get(group, [group])]
        if len(set(excluded_labels)) != len(excluded_labels) or not set(excluded_labels) <= set(labels):
            raise ValueError(f"Invalid Python HS exclusions: {elem.name}")
        excluded_indices = [labels.index(label)+1 for label in excluded_labels]
        self.aux_decls.append(f"@variables {identifier}(t)[{self._range_str(dims)}]")
        self._var_dims[identifier] = HOTPATH_DIMS.copy()
        if not hasattr(self, "_seneca_python_hotpaths"):
            self._seneca_python_hotpaths = []
        self._seneca_python_hotpaths.append({"name": elem.name, "source": source_name,
            "dimensions": HOTPATH_DIMS.copy(), "excluded_labels": excluded_labels,
            "semantics": "Python zero-before-HS-sequential-sum then divide"})
        indices = "Int[" + ", ".join(map(str, excluded_indices)) + "]"
        return [f"{identifier} ~ seneca_hotpath_ms_normalize({source}, {indices})"]

    def content(self, equations):
        from .common import CONFIG
        return (CONFIG / "hotpath.jl").read_text() + "\n" + original_content(self, equations)

    JuliaSectionBuilder._process_element = process
    JuliaSectionBuilder._full_file_content = content
