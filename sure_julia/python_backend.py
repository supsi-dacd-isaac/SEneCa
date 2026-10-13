"""Independent pinned Python oracle with the accepted synchronous delay policy."""
import threading
import time
import warnings

import numpy as np

from .catalog import defaults, inventory, outputs as all_outputs, parameters
from .common import ROOT, YEARS, MODEL_PY, MODEL_VARIANT, MODEL_REVISION, model_sources, identity, read
from .synchronous_delays import install
from .physical import OUTPUTS as PHYSICAL_OUTPUTS, check as physical_check


class PythonBackend:
    backend = "python"

    def __init__(self, outputs=None):
        import pysd
        import sure_paths
        import sure_pysd as sp
        if pysd.__version__ != "3.14.3":
            raise ValueError("Python backend requires PySD 3.14.3")
        sure_paths.set_variant(MODEL_VARIANT)
        self.outputs = list(outputs or all_outputs())
        self.lock = threading.Lock()
        self.warnings = []
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            self.model = sp.load_model(prune=True, model_path=MODEL_PY,
                                       outputs=list(dict.fromkeys(self.outputs+PHYSICAL_OUTPUTS)) + ['"'+n+'"' if n.startswith("Provvedimento") else n for n in defaults()])
            self.constants = sp.build_constant_params(self.model)
            install(self.model)
        self._record(caught)
        self.identity = identity({"backend": "python", "sources": model_sources(),
                                  "model_revision": MODEL_REVISION, "data": read(ROOT / "data-release.json")})
        self.variables, self.dimensions = inventory()

    def _record(self, caught):
        known = {(w["category"], w["message"]) for w in self.warnings}
        for w in caught:
            key = (w.category.__name__, str(w.message))
            if key not in known:
                self.warnings.append({"category": key[0], "message": key[1]})
                known.add(key)

    def run(self, scenario=None, outputs=None, flatten=True):
        from .runtime import frame_from_arrays
        arrays = self.run_arrays(scenario, outputs)
        export = [{"name": n, "dims": self.variables[n].get("subscripts", []),
                   "coords": {d: self.dimensions[d] for d in self.variables[n].get("subscripts", [])}} for n in arrays]
        return frame_from_arrays(arrays, export, flatten=flatten)

    def run_arrays(self, scenario=None, outputs=None):
        import sure_pysd as sp
        params = parameters(scenario)
        names = list(outputs or self.outputs)
        if len(set(names)) != len(names) or set(names) - set(self.outputs):
            raise ValueError("Unknown or duplicate Python outputs")
        missing = [n for n in params if sp.namespace_key(self.model, n) is None]
        if missing:
            raise ValueError(f"Unapplied Python parameters: {missing}")
        internal = list(dict.fromkeys(names + PHYSICAL_OUTPUTS))
        with self.lock, warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            start = time.perf_counter()
            frame = sp.run_scenario(self.model, const_params=self.constants, scenario_inputs=params,
                                    timestamps=YEARS, flatten=False, return_columns=internal)
            result = self._arrays(frame)
            self.last_physical = physical_check(result)
            if not self.last_physical["pass"]:
                raise ValueError(f"Housing stock or transfer invariant failed: {self.last_physical}")
            self.last_timing = {"seconds": time.perf_counter()-start}
        self._record(caught)
        if list(frame.index) != YEARS:
            raise ValueError("Incomplete Python years")
        return {n: result[n] for n in names}

    def _arrays(self, frame):
        result = {}
        for name in frame.columns:
            dims = self.variables[name].get("subscripts", [])
            values = []
            for value in frame[name]:
                if dims and (list(value.dims) != dims or any(list(value.coords[d].values) != self.dimensions[d] for d in dims)):
                    raise ValueError(f"Python coordinates differ: {name}")
                values.append(np.asarray(value, dtype=np.float64))
            array = np.stack(values)
            if not np.isfinite(array).all():
                raise ValueError(f"Nonfinite Python output: {name}")
            result[name] = array
        return result

    def close(self):
        pass
