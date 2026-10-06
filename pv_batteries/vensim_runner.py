"""Harness ctypes riutilizzabile per il modello Vensim pubblicato SURE.vpmx.

Usa la DLL di Vensim DSS (vendll64.dll) per:
- caricare il modello pubblicato (.vpmx);
- impostare le costanti di input con SIMULATE>SETVAL;
- lanciare la simulazione (MENU>RUN|O);
- leggere le serie temporali per-elemento con vensim_get_data;
- enumerare le combinazioni di subscript di una variabile con vensim_get_varattrib.

Adattato/estratto da run_sure.ipynb. Un solo modello per processo (la DLL e'
stateful): per il parallelismo si usa un processo separato per worker.
"""
from __future__ import annotations

import ctypes
import os
import re
import struct
from pathlib import Path

# vensim_get_varattrib: 9 = combinazioni di subscript su cui la variabile e'
# calcolata (lista null-separated tipo "SFH,Low,Bellinzona").
_ATTRIB_SUBSCRIPT_COMBOS = 9

DEFAULT_DLL = r"C:\Windows\System32\vendll64.dll"


def _enc(text: str) -> bytes:
    """Vensim usa la codepage ANSI di Windows per comandi e nomi."""
    return text.encode("mbcs")


_PLAIN_NAME = re.compile(r"^[A-Za-z0-9_ ]+$")


def setval_name(var: str) -> str:
    """Nome di variabile nella forma accettata da SIMULATE>SETVAL.

    Vensim rifiuta i nomi con caratteri speciali se non sono fra virgolette
    (es. "Provvedimento 1.2", per via del punto). vensim_get_varattrib invece
    li accetta anche nudi, quindi la quotatura serve solo qui.
    """
    if var.startswith('"') or _PLAIN_NAME.match(var):
        return var
    return f'"{var}"'


class VensimModel:
    """Wrapper minimale attorno alla DLL di Vensim per un singolo modello."""

    def __init__(self, vpmx_path, dll_path=DEFAULT_DLL, work_dir=None):
        self.vpmx_path = Path(vpmx_path).resolve()
        self.dll_path = Path(dll_path)

        py_bits = struct.calcsize("P") * 8
        if py_bits != 64:
            raise RuntimeError(
                f"Python a {py_bits} bit: vendll64.dll richiede Python a 64 bit."
            )
        if not self.dll_path.exists():
            raise FileNotFoundError(f"DLL Vensim non trovata: {self.dll_path}")
        if not self.vpmx_path.exists():
            raise FileNotFoundError(
                f"Modello pubblicato non trovato: {self.vpmx_path}. "
                "La DLL carica solo .vpm/.vpmx (non i .mdl)."
            )

        self.dll = ctypes.WinDLL(str(self.dll_path))
        self._setup_prototypes()

        # I file .vdf vengono creati nella working dir: la impostiamo se richiesto.
        if work_dir is not None:
            work_dir = Path(work_dir)
            work_dir.mkdir(parents=True, exist_ok=True)
            os.chdir(work_dir)
        self.work_dir = Path(os.getcwd())

        self.cmd(f"SPECIAL>LOADMODEL|{self.vpmx_path}")

    # -- prototipi -------------------------------------------------------
    def _setup_prototypes(self):
        d = self.dll
        d.vensim_command.argtypes = [ctypes.c_char_p]
        d.vensim_command.restype = ctypes.c_int

        d.vensim_get_data.argtypes = [
            ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p,
            ctypes.POINTER(ctypes.c_float), ctypes.POINTER(ctypes.c_float),
            ctypes.c_int,
        ]
        d.vensim_get_data.restype = ctypes.c_int

        d.vensim_get_varattrib.argtypes = [
            ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_int,
        ]
        d.vensim_get_varattrib.restype = ctypes.c_int

        # Valore corrente (a fine run = FINAL TIME). Puo' mancare in alcune DLL.
        self._has_get_val = hasattr(d, "vensim_get_val")
        if self._has_get_val:
            d.vensim_get_val.argtypes = [
                ctypes.c_char_p, ctypes.POINTER(ctypes.c_float),
            ]
            d.vensim_get_val.restype = ctypes.c_int

    # -- comandi ---------------------------------------------------------
    def cmd(self, command: str) -> None:
        rc = self.dll.vensim_command(_enc(command))
        if rc != 1:
            raise RuntimeError(f"Comando Vensim fallito (rc={rc}):\n  {command}")

    def set_time(self, initial=2011, final=2050, step=1) -> None:
        self.cmd(f"SIMULATE>SETVAL|INITIAL TIME={initial}")
        self.cmd(f"SIMULATE>SETVAL|FINAL TIME={final}")
        self.cmd(f"SIMULATE>SETVAL|TIME STEP={step}")

    def clear_runs(self) -> None:
        try:
            self.cmd("SPECIAL>CLEARRUNS")
        except RuntimeError:
            pass

    def run(self, run_name: str, inputs: dict) -> None:
        """Imposta gli input (costanti) e lancia la simulazione (overwrite)."""
        self.cmd(f"SIMULATE>RUNNAME|{run_name}")
        for var, val in inputs.items():
            self.cmd(f"SIMULATE>SETVAL|{setval_name(var)}={val}")
        self.cmd("MENU>RUN|O")

    # -- lettura ---------------------------------------------------------
    def _buffers(self, maxn: int):
        """Buffer ctypes riutilizzati tra le chiamate (evita milioni di alloc)."""
        cur = getattr(self, "_buf_size", 0)
        if cur < maxn:
            self._vval = (ctypes.c_float * maxn)()
            self._tval = (ctypes.c_float * maxn)()
            self._buf_size = maxn
        return self._vval, self._tval

    def get_series(self, run_name: str, varname: str, maxn: int = 1_000_000):
        """Serie (tempi, valori) di 'varname' dal run indicato.

        'run_name' e' il NOME del run (senza .vdf/percorso): la DLL lo risolve
        dalla working directory.
        """
        vval, tval = self._buffers(maxn)
        n = self.dll.vensim_get_data(
            _enc(run_name), _enc(varname), b"Time", vval, tval, maxn)
        if n <= 0:
            raise RuntimeError(
                f"Nessun dato per '{varname}' nel run '{run_name}' (n={n}).")
        return list(tval[:n]), list(vval[:n])

    def get_year(self, run_name: str, varname: str, year: float,
                 maxn: int = 5000) -> float:
        """Valore di 'varname' all'anno indicato, senza materializzare la serie."""
        vval, tval = self._buffers(maxn)
        n = self.dll.vensim_get_data(
            _enc(run_name), _enc(varname), b"Time", vval, tval, maxn)
        if n <= 0:
            raise RuntimeError(
                f"Nessun dato per '{varname}' nel run '{run_name}' (n={n}).")
        target = float(year)
        for i in range(n):
            if abs(tval[i] - target) < 1e-6:
                return float(vval[i])
        return float("nan")

    def get_val(self, varname: str) -> float:
        """Valore corrente di 'varname' (dopo RUN e' l'ultimo TIME)."""
        if not getattr(self, "_has_get_val", False):
            raise RuntimeError("vensim_get_val non e' esportato da questa DLL.")
        val = ctypes.c_float()
        rc = self.dll.vensim_get_val(_enc(varname), ctypes.byref(val))
        if rc != 1:
            raise RuntimeError(
                f"vensim_get_val fallito per '{varname}' (rc={rc}).")
        return float(val.value)

    def subscript_combos(self, base_var: str, buflen: int = 8_000_000):
        """Combinazioni di subscript di 'base_var' (senza parentesi).

        Ritorna [] per variabili scalari. Ogni elemento e' la stringa interna
        alle parentesi, es. 'SFH' oppure 'Bellinzona,SFH,Low,...'.
        """
        buf = ctypes.create_string_buffer(buflen)
        n = self.dll.vensim_get_varattrib(
            _enc(base_var), _ATTRIB_SUBSCRIPT_COMBOS, buf, buflen)
        if n <= 0:
            return []
        raw = buf.raw[:buflen]
        combos = [b.decode("mbcs", errors="replace")
                  for b in raw.split(b"\x00") if b]
        return combos

    def expand_var(self, base_var: str):
        """Nomi completi leggibili con get_data per 'base_var'.

        Scalare -> [base_var]; subscripted -> ['base_var[combo]', ...].
        vensim_get_varattrib(9) restituisce i combo gia' fra parentesi
        (es. '[SFH]'), quindi qui evitiamo il doppio wrapping.
        """
        combos = [c.strip() for c in self.subscript_combos(base_var)]
        combos = [c for c in combos if c and c != base_var]
        if not combos:
            return [base_var]
        out = []
        for c in combos:
            out.append(f"{base_var}{c}" if c.startswith("[")
                       else f"{base_var}[{c}]")
        return out
