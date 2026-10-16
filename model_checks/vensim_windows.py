"""Optional Windows Vensim DLL bridge for the strict dispatch handoff."""
import ctypes
import os
import numpy as np
import pandas as pd
import sure_paths as paths


class Vensim:
    def __init__(self, model_path):
        self.dll = ctypes.WinDLL(paths.DLL_PATH)
        d = self.dll
        d.vensim_command.argtypes = [ctypes.c_char_p]
        d.vensim_command.restype = ctypes.c_int
        d.vensim_get_data.argtypes = [
            ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p,
            ctypes.POINTER(ctypes.c_float), ctypes.POINTER(ctypes.c_float),
            ctypes.c_int]
        d.vensim_get_data.restype = ctypes.c_int
        d.vensim_be_quiet.argtypes = [ctypes.c_int]
        d.vensim_be_quiet.restype = ctypes.c_int
        d.vensim_be_quiet(2)
        os.chdir(paths.VENSIM)
        self._cmd(f"SPECIAL>LOADMODEL|{model_path}")
        self._maxn = 4096
        self._vv = (ctypes.c_float * self._maxn)()
        self._tt = (ctypes.c_float * self._maxn)()

    def _cmd(self, command: str):
        if self.dll.vensim_command(command.encode("mbcs")) != 1:
            raise RuntimeError(f"Comando Vensim fallito: {command}")

    def run(self, run_name: str, inputs: dict[str, float]) -> tuple[list[str], float]:
        self._cmd(f"SIMULATE>RUNNAME|{run_name}")
        skipped = []
        for var, val in inputs.items():
            # I nomi con virgolette in Vensim (Provvedimento 1.x) vanno quotati.
            quoted = f'"{var}"' if var.startswith("Provvedimento") else var
            cmd = f"SIMULATE>SETVAL|{quoted}={val}"
            if self.dll.vensim_command(cmd.encode("mbcs")) != 1:
                skipped.append(var)
        self._cmd("MENU>RUN|O")
        return skipped, self._horizon(run_name)

    def _horizon(self, run_name: str) -> float:
        n = self.dll.vensim_get_data(
            run_name.encode("mbcs"), b"Levy Evolution", b"Time",
            self._vv, self._tt, self._maxn)
        return float(self._tt[n - 1]) if n > 0 else float("nan")

    def series(self, run_name: str, label: str, years):
        n = self.dll.vensim_get_data(
            run_name.encode("mbcs"), label.encode("mbcs"), b"Time",
            self._vv, self._tt, self._maxn)
        if n <= 0:
            return None
        t = np.round(np.asarray(self._tt[:n], dtype=float)).astype(int)
        v = np.asarray(self._vv[:n], dtype=float)
        return pd.Series(v, index=t).reindex(years).to_numpy(dtype=float)

