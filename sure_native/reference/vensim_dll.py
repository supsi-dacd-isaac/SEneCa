"""Ponte minimo con la DLL di Vensim DSS (vendll64.dll), solo Windows."""
from __future__ import annotations

import ctypes
import os
from pathlib import Path

import numpy as np

DLL_PATH = r"C:\Windows\System32\vendll64.dll"


class VensimDLL:
    def __init__(self, model: Path):
        self.dll = d = ctypes.WinDLL(DLL_PATH)
        d.vensim_command.argtypes = [ctypes.c_char_p]
        d.vensim_command.restype = ctypes.c_int
        d.vensim_be_quiet.argtypes = [ctypes.c_int]
        d.vensim_get_data.argtypes = [
            ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p,
            ctypes.POINTER(ctypes.c_float), ctypes.POINTER(ctypes.c_float), ctypes.c_int]
        d.vensim_get_data.restype = ctypes.c_int
        d.vensim_get_varnames.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
        d.vensim_get_varnames.restype = ctypes.c_int
        d.vensim_get_varattrib.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
        d.vensim_get_varattrib.restype = ctypes.c_int
        d.vensim_be_quiet(2)
        self.model = Path(model).resolve()
        os.chdir(self.model.parent)
        self.cmd(f"SPECIAL>LOADMODEL|{self.model.name}")
        self._n = 8192
        self._v = (ctypes.c_float * self._n)()
        self._t = (ctypes.c_float * self._n)()

    def cmd(self, command: str) -> None:
        if self.dll.vensim_command(command.encode("mbcs")) != 1:
            raise RuntimeError(f"Comando Vensim fallito: {command}")

    def try_cmd(self, command: str) -> bool:
        return self.dll.vensim_command(command.encode("mbcs")) == 1

    @staticmethod
    def _split(raw: bytes) -> list[str]:
        return [s.decode("mbcs") for s in raw.split(b"\0") if s]

    def varnames(self, pattern: str = "*", vartype: int = 0) -> list[str]:
        size = self.dll.vensim_get_varnames(pattern.encode("mbcs"), vartype, None, 0)
        if size <= 0:
            return []
        buf = ctypes.create_string_buffer(size + 2)
        self.dll.vensim_get_varnames(pattern.encode("mbcs"), vartype, buf, size + 2)
        return self._split(buf.raw[:size])

    def attrib(self, name: str, attrib: int) -> list[str]:
        size = self.dll.vensim_get_varattrib(name.encode("mbcs"), attrib, None, 0)
        if size <= 0:
            return []
        buf = ctypes.create_string_buffer(size + 2)
        self.dll.vensim_get_varattrib(name.encode("mbcs"), attrib, buf, size + 2)
        return self._split(buf.raw[:size])

    def data(self, source: str, name: str) -> tuple[np.ndarray, np.ndarray] | None:
        n = self.dll.vensim_get_data(source.encode("mbcs"), name.encode("mbcs"), b"Time",
                                     self._v, self._t, self._n)
        if n <= 0:
            return None
        return (np.frombuffer(self._t, dtype=np.float32, count=n).copy(),
                np.frombuffer(self._v, dtype=np.float32, count=n).copy())
