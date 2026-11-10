"""Riferimento Vensim in doppia precisione da una corsa .vdfx e dal suo export .tab.

Vensim esporta i dataset (VDF2TAB, VDF2CSV, VDF2DAT) con 6 cifre significative,
ma il .vdfx salva le serie in Float64. Il formato non è documentato. Ogni serie
è un blocco:

    uint16 n | bitmap di ceil(T/8) byte (LSB first, un bit per istante) | n Float64

Un bit a 1 indica un valore salvato; un bit a 0 ripete il valore precedente.

Questo modulo non interpreta l'indice dei nomi del .vdfx. Cerca i blocchi validi
e li abbina alle righe del .tab esportato da Vensim: una serie è accettata solo
se tutti i suoi valori Float64, scritti con 6 cifre significative, coincidono
con quelli che Vensim stesso ha esportato. Le serie senza un blocco univoco
restano con i valori a 6 cifre del .tab e sono marcate.

Uscita, nella cartella <out>:
    names.txt     un nome di serie per riga, come nel .tab (Var[elem,...])
    times.f64     istanti (T)
    values.f64    matrice row-major (serie × T), NaN dove il .tab è vuoto
    status.u8     0 = Float64 dal .vdfx; 1 = 6 cifre (blocco ambiguo);
                  2 = 6 cifre (nessun blocco)
    meta.json     conteggi, checksum dei sorgenti
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

LUT = np.array([bin(i).count("1") for i in range(256)], dtype=np.uint8)


def g6(x: float) -> str:
    return "%.6g" % x


def read_tab(path: Path):
    names, rows = [], []
    with open(path, encoding="utf-8", errors="strict", newline="") as f:
        header = f.readline().rstrip("\r\n").split("\t")
        times = np.array([float(t) for t in header[1:]])
        for line in f:
            parts = line.rstrip("\r\n").split("\t")
            if not parts[0]:
                continue
            names.append(parts[0])
            rows.append(parts[1:])
    return times, names, rows


def scan_blocks(raw: bytes, T: int):
    """Tutti gli offset che hanno l'aspetto di un blocco serie (n, bitmap, bit 0 a 1)."""
    nb = (T + 7) // 8
    b = np.frombuffer(raw, dtype=np.uint8)
    N = len(b) - (2 + nb)
    n = b[:N].astype(np.uint16) | (b[1:N + 1].astype(np.uint16) << 8)
    pc = np.zeros(N, dtype=np.uint16)
    for k in range(nb):
        pc += LUT[b[2 + k:2 + k + N]]
    ok = (n >= 1) & (n <= T) & (pc == n) & ((b[2:2 + N] & 1) == 1)
    if T % 8:  # i bit oltre T devono essere a zero
        ok &= (b[1 + nb:1 + nb + N] >> (T % 8)) == 0
    idx = np.nonzero(ok)[0]
    idx = idx[idx + 2 + nb + 8 * n[idx].astype(np.int64) <= len(b)]
    return idx, n[idx].astype(np.int64), nb


def decode(raw: bytes, off: int, n: int, nb: int, T: int) -> np.ndarray:
    bits = np.unpackbits(np.frombuffer(raw, dtype=np.uint8, count=nb, offset=off + 2),
                         bitorder="little")[:T].astype(bool)
    vals = np.frombuffer(raw, dtype=np.float64, count=n, offset=off + 2 + nb)
    pos = np.cumsum(bits) - 1          # indice del valore salvato più recente
    return vals[pos]


def build(vdfx: Path, tab: Path, out: Path) -> dict:
    times, names, rows = read_tab(tab)
    T = len(times)
    raw = vdfx.read_bytes()
    idx, ns, nb = scan_blocks(raw, T)

    # Chiave: la serie su T istanti con 6 cifre; il .tab può avere celle vuote
    # (istanti senza valore) e le costanti hanno un solo valore.
    def row_key(r):
        if len(r) == 1:
            r = r * T
        r = (r + [""] * T)[:T]
        filled, last = [], None
        for s in r:
            if s != "":
                last = g6(float(s))
            filled.append(last)
        return tuple(filled), tuple(s == "" for s in r)

    keys = [row_key(r) for r in rows]
    wanted = {k for k, _ in keys}

    # candidati: chiave a 6 cifre -> lista di (offset, valori Float64)
    cand: dict[tuple, list[tuple[int, np.ndarray]]] = {}
    for off, n in zip(idx.tolist(), ns.tolist()):
        v = decode(raw, off, n, nb, T)
        k = tuple(g6(x) for x in v)
        if k in wanted:
            lst = cand.setdefault(k, [])
            # valori distinti per chiave, ciascuno con i propri offset
            for entry in lst:
                if np.array_equal(entry[1], v):
                    entry[0].append(off)
                    break
            else:
                lst.append(([off], v))


    values = np.full((len(names), T), np.nan)
    status = np.zeros(len(names), dtype=np.uint8)
    pos = [None] * len(names)          # offset del blocco usato, per le righe univoche
    chosen = [None] * len(names)
    for i, (k, _) in enumerate(keys):
        lst = cand.get(k)
        if lst is None:
            status[i] = 2
        elif len(lst) == 1:
            chosen[i] = lst[0][1]
            if len(lst[0][0]) == 1:
                pos[i] = lst[0][0][0]
        else:
            status[i] = 1
    # Blocchi ambigui: Vensim scrive le serie nell'ordine delle righe (crescente o
    # decrescente). Si sceglie il candidato compreso tra i blocchi univoci vicini.
    resolved = 0
    import bisect
    progress = True
    while progress:            # i blocchi risolti diventano a loro volta riferimenti
        progress = False
        known = [i for i in range(len(names)) if pos[i] is not None]
        for i in range(len(names)):
            if status[i] != 1:
                continue
            j = bisect.bisect_left(known, i)
            if j == 0 or j == len(known):
                continue
            a, b = pos[known[j - 1]], pos[known[j]]
            lo, hi = min(a, b), max(a, b)
            inside = [([o for o in offs if lo < o < hi], v) for offs, v in cand[keys[i][0]]]
            inside = [(o, v) for o, v in inside if o]
            if len(inside) == 1:
                chosen[i] = inside[0][1]
                status[i] = 0
                if len(inside[0][0]) == 1:
                    pos[i] = inside[0][0][0]
                    progress = True
                resolved += 1
    for i, ((k, blank), r) in enumerate(zip(keys, rows)):
        if chosen[i] is not None:
            values[i] = chosen[i]
        else:
            values[i] = [np.nan if s is None else float(s) for s in k]
        values[i, list(blank)] = np.nan

    out.mkdir(parents=True, exist_ok=True)
    # candidati Float64 delle serie rimaste ambigue, per la scelta con il modello
    amb = {names[i]: [v.tolist() for _, v in cand[keys[i][0]]] for i in range(len(names)) if status[i] == 1}
    (out / "ambiguous.json").write_text(json.dumps(amb), encoding="utf-8")
    (out / "names.txt").write_text("\n".join(names) + "\n", encoding="utf-8")
    times.astype("<f8").tofile(out / "times.f64")
    values.astype("<f8").tofile(out / "values.f64")
    status.tofile(out / "status.u8")
    meta = {
        "vdfx": vdfx.name, "tab": tab.name,
        "vdfx_sha256": hashlib.sha256(raw).hexdigest(),
        "series": len(names), "times": [times[0], times[-1], T],
        "float64": int((status == 0).sum()),
        "six_digits_ambiguous": int((status == 1).sum()),
        "six_digits_unmatched": int((status == 2).sum()),
        "block_candidates": int(len(idx)),
        "resolved_by_position": resolved,
    }
    (out / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("vdfx", type=Path)
    ap.add_argument("tab", type=Path)
    ap.add_argument("out", type=Path)
    a = ap.parse_args()
    print(json.dumps(build(a.vdfx, a.tab, a.out), indent=2))
