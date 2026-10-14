"""Persistent isolated Julia process, with bounded requests and labelled outputs."""
import atexit
import itertools
import json
import os
import queue
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

from .catalog import parameters
from .common import CONFIG, ROOT, YEARS, MODEL_REVISION, digest, identity, read


def frame_from_arrays(arrays, export, *, flatten=True):
    if flatten:
        columns, blocks = [], []
        for item in export:
            value = arrays[item["name"]]
            columns.extend([item["name"]] if not item["dims"] else [item["name"] + "[" + ",".join(labels) + "]"
                for labels in itertools.product(*(item["coords"][d] for d in item["dims"]))])
            blocks.append(value.reshape(len(YEARS), -1))
        return pd.DataFrame(np.concatenate(blocks, axis=1), index=pd.Index(YEARS, dtype=float, name="Time"), columns=columns)
    data = {}
    for item in export:
        values = arrays[item["name"]]
        data[item["name"]] = list(values) if not item["dims"] else [xr.DataArray(v, dims=item["dims"], coords=item["coords"]) for v in values]
    return pd.DataFrame(data, index=pd.Index(YEARS, dtype=float, name="Time"))


class JuliaBackend:
    backend = "julia"

    def __init__(self, directory=None, timeout=300):
        self.directory = Path(directory or os.environ.get("SURE_JULIA_MODEL", ROOT / "sure_julia/generated")).resolve()
        self.metadata = read(self.directory / "build.json")
        if not self.metadata.get("complete"):
            raise ValueError("Incomplete Julia build")
        if self.metadata.get("model_revision") != MODEL_REVISION:
            raise ValueError(f"Julia build must use {MODEL_REVISION}")
        for name, expected in self.metadata["artifacts"].items():
            if digest(self.directory / name) != expected:
                raise ValueError(f"Julia artifact checksum differs: {name}")
        self.identity = identity({"backend": "julia", "build": self.metadata, "data": read(ROOT / "data-release.json")})
        self.export = read(self.directory / "export.json")
        self.lock, self.timeout = threading.Lock(), timeout
        self.process = None
        self.messages = None
        self.request_id = 0
        self.log = None
        self.last_timing = None
        atexit.register(self.close)

    def _receive(self):
        try:
            value = self.messages.get(timeout=self.timeout)
        except queue.Empty:
            self.close()
            raise TimeoutError(f"Julia request exceeded {self.timeout} seconds") from None
        if value is None:
            diagnostic = self.log_path
            self.close()
            raise RuntimeError(f"Julia worker exited; diagnostic log: {diagnostic}")
        if isinstance(value, Exception):
            self.close()
            raise value
        return value

    def _start(self):
        if self.process is not None and self.process.poll() is None:
            return
        self.close()
        messages = self.messages = queue.Queue()
        env = {**os.environ, **{k: "1" for k in ["JULIA_NUM_THREADS", "OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"]}}
        binary = os.environ.get("SURE_JULIA_BIN", "julia")
        self.log = tempfile.NamedTemporaryFile(prefix="sure-julia-", suffix=".log", mode="w+", delete=False)
        self.log_path = self.log.name
        self.process = subprocess.Popen([binary, "--startup-file=no", f"--project={CONFIG}", str(CONFIG / "worker.jl"),
                                        str(self.directory / self.metadata["model"]), str(self.directory / "export.json")],
                                       stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.log, text=True, bufsize=1, env=env)
        process = self.process
        def consume():
            try:
                for line in process.stdout:
                    messages.put(json.loads(line))
            except Exception as exc:
                messages.put(exc)
            finally:
                messages.put(None)
        threading.Thread(target=consume, daemon=True).start()
        ready = self._receive()
        if not ready.get("ready"):
            self.close()
            raise RuntimeError(f"Julia initialization failed: {ready}")
        self.load_timing = ready

    def run_arrays(self, scenario=None, outputs=None):
        params = parameters(scenario)
        catalog = {v["name"]: v for v in self.export}
        names = list(outputs or catalog)
        if len(set(names)) != len(names) or set(names) - set(catalog):
            raise ValueError("Unknown or duplicate requested outputs")
        requested = list(names)
        from .physical import OUTPUTS as PHYSICAL_OUTPUTS
        names = list(dict.fromkeys(names + PHYSICAL_OUTPUTS))
        with self.lock, tempfile.TemporaryDirectory(prefix="sure-result-") as temporary:
            self._start()
            self.request_id += 1
            job = {"id": self.request_id, "parameters": params, "outputs": names, "directory": temporary}
            try:
                self.process.stdin.write(json.dumps(job, allow_nan=False) + "\n")
                self.process.stdin.flush()
            except (BrokenPipeError, OSError):
                self.close()
                raise RuntimeError("Julia worker exited before accepting request") from None
            result = self._receive()
            if result.get("id") != self.request_id or not result.get("ok"):
                self.close()
                raise RuntimeError(f"Julia simulation failed: {result}")
            if result["years"] != YEARS:
                raise ValueError("Julia returned incomplete years")
            arrays = {}
            for i, name in enumerate(names):
                item = catalog[name]
                shape = (len(YEARS), *(len(item["coords"][d]) for d in item["dims"]))
                values = np.fromfile(Path(temporary) / f"v{i:04d}.bin", dtype="<f8")
                if values.size != np.prod(shape) or not np.isfinite(values).all():
                    raise ValueError(f"Invalid Julia output: {name}")
                arrays[name] = values.reshape(shape)
            self.last_timing = result
            from .physical import check, PhysicalInvariantError
            self.last_physical = check(arrays)
            if not self.last_physical["pass"]:
                raise PhysicalInvariantError(self.last_physical, arrays)
            return {name: arrays[name] for name in requested}

    def run(self, scenario=None, outputs=None, flatten=True):
        arrays = self.run_arrays(scenario, outputs)
        catalog = {v["name"]: v for v in self.export}
        return frame_from_arrays(arrays, [catalog[n] for n in arrays], flatten=flatten)

    def close(self):
        process, self.process = self.process, None
        if process is not None:
            if process.stdin:
                try:
                    process.stdin.close()
                except BrokenPipeError:
                    pass
            if process.poll() is None:
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
            if process.stdout:
                process.stdout.close()
        if self.log is not None:
            self.log.close()
            self.log = None
