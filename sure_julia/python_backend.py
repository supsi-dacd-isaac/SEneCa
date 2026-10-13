"""Independent pinned Python oracle with the accepted synchronous delay policy."""
import threading
import time
import warnings

import numpy as np

from .catalog import defaults, inventory, outputs as all_outputs, parameters
from .common import ROOT, YEARS, digest, identity, read
from .synchronous_delays import install


class PythonBackend:
    backend = "python"

    def __init__(self, outputs=None):
        import pysd
        import sure_paths
        import sure_pysd as sp
        if pysd.__version__ != "3.14.3":
            raise ValueError("Python backend requires PySD 3.14.3")
        sure_paths.set_variant("v4")
        self.outputs = list(outputs or all_outputs())
        self.lock = threading.Lock()
        self.warnings = []
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            self.model = sp.load_model(prune=True, outputs=self.outputs + ['"'+n+'"' if n.startswith("Provvedimento") else n for n in defaults()])
            self.constants = sp.build_constant_params(self.model)
            install(self.model)
        self._record(caught)
        self.identity = identity({"backend": "python", "model": digest(ROOT / "Vensim/SURE_pysd_v4.py"),
                                  "calibration": digest(ROOT / "constants_ref_v4.pkl"), "data": read(ROOT / "data-release.json")})
        self.variables, self.dimensions = inventory()

    def _record(self, caught):
        known = {(w["category"], w["message"]) for w in self.warnings}
        for w in caught:
            key = (w.category.__name__, str(w.message))
            if key not in known:
                self.warnings.append({"category": key[0], "message": key[1]})
                known.add(key)

    def run(self, scenario=None, outputs=None, flatten=True):
        import sure_pysd as sp
        params = parameters(scenario)
        names = list(outputs or self.outputs)
        if len(set(names)) != len(names) or set(names) - set(self.outputs):
            raise ValueError("Unknown or duplicate Python outputs")
        missing = [n for n in params if sp.namespace_key(self.model, n) is None]
        if missing:
            raise ValueError(f"Unapplied Python parameters: {missing}")
        with self.lock, warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            start = time.perf_counter()
            frame = sp.run_scenario(self.model, const_params=self.constants, scenario_inputs=params,
                                    timestamps=YEARS, flatten=flatten, return_columns=names)
            self.last_timing = {"seconds": time.perf_counter()-start}
        self._record(caught)
        if list(frame.index) != YEARS:
            raise ValueError("Incomplete Python years")
        return frame

    def run_arrays(self, scenario=None, outputs=None):
        frame = self.run(scenario, outputs, flatten=False)
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
