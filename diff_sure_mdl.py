"""Diff strutturale fra due .mdl Vensim: equazioni aggiunte, rimosse, modificate.

Serve a capire cosa e' cambiato quando arriva una nuova versione di SURE.mdl,
prima di lanciare la ritraduzione.

Uso:
    # nuova versione vs traduzione corrente
    .\\.venv\\Scripts\\python.exe diff_sure_mdl.py Vensim/SURE_pysd.mdl Vensim/SURE.mdl

    # ignora le equazioni di lettura dati (GET VDF/DIRECT DATA), che differiscono
    # sempre fra sorgente e copia pysd-compatibile
    .\\.venv\\Scripts\\python.exe diff_sure_mdl.py A.mdl B.mdl --nodata
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

ENC = "latin-1"
DATA_FNS = ("GET DIRECT DATA", "GET VDF DATA")


def join_continuations(text: str) -> str:
    return re.sub(r"\\\s*\n\s*", " ", text)


def split_equations(text: str) -> dict[str, str]:
    """nome variabile -> corpo dell'equazione (senza unita' e commento)."""
    text = text.split("\\\\\\---///")[0]  # scarta lo sketch
    text = join_continuations(text)
    eqs: dict[str, list[str]] = {}
    for chunk in text.split("|"):
        chunk = chunk.strip()
        if not chunk or chunk.startswith("{"):
            continue
        body = chunk.split("~")[0].strip()
        if not body:
            continue
        m = re.match(r"^([^=:]+?)\s*(?::[A-Z][A-Za-z ]*:|:=|==|=|:)", body)
        if not m:
            continue
        name = re.sub(r"\s+", " ", re.sub(r"\[.*", "", m.group(1)).strip())
        eqs.setdefault(name, []).append(re.sub(r"\s+", " ", body))
    return {k: "\n".join(v) for k, v in eqs.items()}


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("a", help="mdl di riferimento (vecchio)")
    ap.add_argument("b", help="mdl nuovo")
    ap.add_argument("--nodata", action="store_true",
                    help="Ignora le equazioni GET VDF DATA / GET DIRECT DATA")
    ap.add_argument("--chars", type=int, default=300,
                    help="Caratteri di equazione da mostrare per le modifiche")
    args = ap.parse_args()

    ea = split_equations(Path(args.a).read_text(encoding=ENC, errors="replace"))
    eb = split_equations(Path(args.b).read_text(encoding=ENC, errors="replace"))

    only_a = sorted(set(ea) - set(eb))
    only_b = sorted(set(eb) - set(ea))
    changed = [k for k in sorted(set(ea) & set(eb)) if ea[k] != eb[k]]
    if args.nodata:
        changed = [k for k in changed
                   if not any(fn in ea[k] or fn in eb[k] for fn in DATA_FNS)]

    print(f"A={args.a}: {len(ea)} equazioni")
    print(f"B={args.b}: {len(eb)} equazioni")
    print(f"\nRimosse in B ({len(only_a)}):")
    for k in only_a:
        print("  -", k)
    print(f"\nNuove in B ({len(only_b)}):")
    for k in only_b:
        print("  +", k)
    print(f"\nModificate ({len(changed)}):")
    for k in changed:
        print("  ~", k)
        print("      A:", ea[k][:args.chars])
        print("      B:", eb[k][:args.chars])


if __name__ == "__main__":
    main()
