"""Label-aware indexing and lexical SUM scopes for the experimental backend.

Never infer an axis from its size: several unrelated SURE axes have size two or
three. An aggregation shadows the corresponding outer index even when its name
also occurs on the element being defined.
"""
from __future__ import annotations

import re


def _clean(value):
    return re.sub(r"[^a-z0-9_]", "_", value.lower())


def _range(self, name):
    if name in self.subs_elems:
        return name
    matches = [r for r in self.subs_elems if _clean(r) == _clean(name)]
    if len(matches) != 1:
        raise ValueError(f"Unknown/ambiguous subscript range: {name}")
    return matches[0]


def _map_index(self, expression, source, target):
    source_labels, target_labels = self.subs_elems[source], self.subs_elems[target]
    if source_labels == target_labels:
        return expression
    # Zero denotes an invalid INDEX, never a substituted numeric value. Julia
    # bounds checks therefore reject a reference outside its explicit subgroup.
    mapping = [target_labels.index(label) + 1 if label in target_labels else 0 for label in source_labels]
    if not any(mapping):
        raise ValueError(f"Unrelated coordinate ranges: {source} -> {target}")
    if re.fullmatch(r"\d+", expression):
        index = int(expression)
        if not 1 <= index <= len(mapping) or mapping[index-1] == 0:
            raise ValueError(f"Coordinate outside subgroup: {source}[{expression}] -> {target}")
        return str(mapping[index-1])
    return f"[{', '.join(map(str, mapping))}][{expression}]"


def _index(self, spec, target):
    target = _range(self, target)
    if spec.endswith("!"):
        sub = _range(self, spec[:-1])
        binding = getattr(self, "_seneca_bang", {}).get(sub)
        if binding is None:
            raise ValueError(f"Aggregation subscript outside SUM/VMIN/VMAX/PROD: {spec}")
        return _map_index(self, binding, sub, target)
    if spec not in self.subs_elems and not any(_clean(spec) == _clean(s) for s in self.subs_elems):
        labels = self.subs_elems[target]
        matches = [i + 1 for i, label in enumerate(labels) if label.lower() == spec.lower()]
        if len(matches) != 1:
            raise ValueError(f"Unknown coordinate {spec} in {target}")
        return str(matches[0])
    sub = _range(self, spec)
    active = {k: v for k, v in self.active_subs.items() if k in self.subs_elems}
    if sub in active:
        expression = active[sub]
        # EXCEPT visitors annotate a subgroup with the parent loop's index.
        # Recover that index's actual label basis before mapping to a target.
        bases = [r for r, value in active.items() if value == expression
                 and set(self.subs_elems[sub]) <= set(self.subs_elems[r])]
        source = max(bases, key=lambda r: len(self.subs_elems[r]))
        return _map_index(self, expression, source, target)
    if target in active and set(self.subs_elems[sub]) <= set(self.subs_elems[target]):
        return active[target]
    candidates = [(r, value) for r, value in active.items()
                  if self.subs_elems[r] == self.subs_elems[sub]]
    if candidates:
        if len({v for _, v in candidates}) != 1:
            raise ValueError(f"Ambiguous active coordinate range: {sub}")
        source, expression = candidates[0]
        return _map_index(self, expression, source, target)
    # A genuinely unbound axis is an explicit labelled slice. It is never
    # aligned with an unrelated equally-sized axis.
    labels = self.subs_elems[target]
    selected = self.subs_elems[sub]
    if not set(selected) <= set(labels):
        raise ValueError(f"Unbound unrelated coordinates: {sub} -> {target}")
    return "[" + ", ".join(str(labels.index(v)+1) for v in selected) + "]"


def _reference(self, node, arguments=None):
    identifier = self.namespace.get(node.reference)
    dims = self.var_dims.get(identifier, [])
    specs = list(node.subscripts.subscripts) if node.subscripts is not None else []
    if not specs:
        specs = list(dims)
    if len(specs) != len(dims):
        raise ValueError(f"Reference rank mismatch: {node.reference} {specs} -> {dims}")
    indices = [_index(self, s, d) for s, d in zip(specs, dims)]
    if arguments is None and identifier not in self.lookup_names:
        return identifier + ("[" + ", ".join(indices) + "]" if indices else "")
    args = ["t"] if arguments is None else arguments
    unbound = [(i, expression) for i, expression in enumerate(indices) if expression.startswith("[") and "][" not in expression]
    if unbound:
        ranges = []
        for i, expression in unbound:
            index = f"_slice{i}"
            indices[i] = index
            ranges.append(f"{index} in {expression}")
        return f"[{identifier}({', '.join([*indices, *args])}) for {', '.join(ranges)}]"
    return f"{identifier}({', '.join([*indices, *args])})"


def _vector_expression_axes(self, node):
    """Prove an argument is a vector, without guessing N-D memory layout.

    Named non-reduced axes still exist in the Python array even when the
    Julia emitter is currently iterating a single cell of those axes.
    Individual coordinate labels remove an axis; scalar arithmetic preserves
    the union of its operands' axes. More complex calls stay unclassified.
    """
    from pysd.translators.structures.abstract_expressions import ReferenceStructure, ArithmeticStructure, LogicStructure
    if isinstance(node, (int, float)):
        return set()
    if isinstance(node, ReferenceStructure):
        identifier = self.namespace.get(node.reference)
        if identifier is None:
            return None
        specs = node.subscripts.subscripts if node.subscripts is not None else self.var_dims.get(identifier, [])
        axes = set()
        for spec in specs:
            if spec.endswith("!"):
                axes.add(_range(self, spec[:-1]))
            elif spec in self.subs_elems or any(_clean(spec) == _clean(dim) for dim in self.subs_elems):
                axes.add(_range(self, spec))
        return axes
    if isinstance(node, (ArithmeticStructure, LogicStructure)):
        axes = set()
        for argument in node.arguments:
            child = _vector_expression_axes(self, argument)
            if child is None:
                return None
            axes.update(child)
        return axes
    return None


def apply():
    import numpy as np
    from pysd.builders.julia.julia_model_builder import JuliaSectionBuilder
    from pysd.builders.julia.julia_expressions_builder import JuliaASTVisitor, BUILTIN_FUNCTIONS
    from pysd.builders.julia.namespace import JuliaNamespaceManager
    from pysd.translators.structures.abstract_expressions import ReferenceStructure, CallStructure, ArithmeticStructure, LogicStructure
    if getattr(JuliaASTVisitor, "_seneca_indexing_applied", False):
        return
    JuliaASTVisitor._seneca_indexing_applied = True
    original_reference, original_call = JuliaASTVisitor._reference, JuliaASTVisitor._call
    original_process = JuliaSectionBuilder._process_element
    original_add = JuliaNamespaceManager.add_to_namespace

    def reference_key(name):
        # This is the Python translator's reference normalization. Comparison
        # operators and punctuation INSIDE quoted names are part of identity.
        return name.lower().replace(" ", "_")

    def add_namespace(self, name):
        identifier = original_add(self, name)
        references = getattr(self, "_seneca_reference_names", None)
        if references is None:
            references = {reference_key(k): v for k, v in self.namespace.items()}
            self._seneca_reference_names = references
        key = reference_key(name)
        previous = references.get(key)
        if previous is not None and previous != identifier:
            raise ValueError(f"Ambiguous Vensim reference identity: {name}")
        references[key] = identifier
        return identifier

    def get_namespace(self, name):
        if name in self.namespace:
            return self.namespace[name]
        references = getattr(self, "_seneca_reference_names", None)
        if references is None:
            references = {reference_key(k): v for k, v in self.namespace.items()}
            self._seneca_reference_names = references
        return references.get(reference_key(name))

    def process(self, elem, identifier, is_control=False):
        from .reduction_policy import context
        previous = getattr(self.namespace, "_seneca_sum_context", {})
        self.namespace._seneca_sum_context = context(self, elem)
        if not hasattr(self.namespace, "_seneca_sum_policy_used"):
            self.namespace._seneca_sum_policy_used = {}
        try:
            if (len(elem.components) == 1 and isinstance(elem.components[0].ast, np.ndarray)
                    and self._element_dims(elem)):
                # Upstream repeats even a single multidimensional array literal
                # in every cell. Reuse the checked component-domain emitter.
                return self._process_except_element(elem, identifier, is_control)
            return original_process(self, elem, identifier, is_control)
        finally:
            self.namespace._seneca_sum_context = previous

    def reference(self, node):
        identifier = self.namespace.get(node.reference)
        if identifier is not None and (self.var_dims.get(identifier) or identifier in self.lookup_names):
            return _reference(self, node)
        return original_reference(self, node)

    def call(self, node):
        builtin = BUILTIN_FUNCTIONS.get(node.function.reference.upper())
        if builtin in {"sum", "prod", "minimum", "maximum"} and len(node.arguments) == 1:
            found = []
            def scan(value):
                if isinstance(value, ReferenceStructure):
                    for s in value.subscripts.subscripts if value.subscripts is not None else []:
                        if s.endswith("!") and s not in found:
                            found.append(s)
                elif isinstance(value, CallStructure):
                    if BUILTIN_FUNCTIONS.get(value.function.reference.upper()) in {"sum", "prod", "minimum", "maximum"}:
                        return
                    scan(value.function)
                    for argument in value.arguments:
                        scan(argument)
                elif isinstance(value, (ArithmeticStructure, LogicStructure)):
                    for argument in value.arguments:
                        scan(argument)
            scan(node.arguments[0])
            if found:
                child = self._with_extra_subs({})
                depth = getattr(self, "_seneca_aggregation_depth", 0)
                child._seneca_aggregation_depth = depth + 1
                child._seneca_bang = dict(getattr(self, "_seneca_bang", {}))
                ranges = []
                for i, spec in enumerate(found):
                    sub = _range(self, spec[:-1])
                    index = f"_sum{depth}_{i}"
                    child._seneca_bang[sub] = index
                    ranges.append(f"{index} in 1:{len(self.subs_elems[sub])}")
                expression = child.visit(node.arguments[0])
                # Last original axis varies fastest, matching Python label order.
                values = f"[{expression} for {', '.join(reversed(ranges))}]"
                policies = getattr(self.namespace, "_seneca_sum_context", {}).get(repr(node), []) if builtin == "sum" else []
                if policies:
                    plan = policies[0]["plan"]
                    by_range = {_range(self, spec[:-1]): clause for spec, clause in zip(found, ranges)}
                    def emit(reduction):
                        if set(by_range) != set(reduction["reduced_order"]) or any(
                                len(self.subs_elems[sub]) != reduction["reduced_sizes"][sub] for sub in by_range):
                            raise ValueError("SUM ranges differ from the audited NumPy layout")
                        ordered = [by_range[sub] for sub in reversed(reduction["reduced_order"])]
                        values = f"[{expression} for {', '.join(ordered)}]"
                        return f"seneca_numpy_reduce({values}, {reduction['blocksize']})"
                    if "initial_time" in plan:
                        result = (f"((t == {float(plan['initial_time'])!r}) ? {emit(plan['initial'])}"
                                  f" : {emit(plan['subsequent'])})")
                    else:
                        result = emit(plan)
                    for policy in policies:
                        self.namespace._seneca_sum_policy_used[policy["id"]] = policy["plan"]
                    return result
                if builtin == "sum" and len(found) == 1 and _vector_expression_axes(self, node.arguments[0]) == {_range(self, found[0][:-1])}:
                    # np.nansum copies a genuine vector to contiguous storage.
                    # Its ufunc accumulator adds the pairwise sum to +0.0.
                    return f"(0.0 + seneca_numpy_sum({values}))"
                return f"{builtin}({values})"
        identifier = self.namespace.get(node.function.reference)
        if builtin is None and identifier in self.lookup_names:
            return _reference(self, node.function, [self.visit(a) for a in node.arguments])
        return original_call(self, node)

    JuliaASTVisitor._reference = reference
    JuliaASTVisitor._call = call
    JuliaSectionBuilder._process_element = process
    JuliaNamespaceManager.add_to_namespace = add_namespace
    JuliaNamespaceManager.get = get_namespace
