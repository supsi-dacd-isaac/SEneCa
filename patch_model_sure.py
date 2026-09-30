"""Fase 2 - Genera una copia pysd-compatibile di SURE.mdl.

SURE.mdl legge i suoi input tramite GET VDF DATA(...) da file .vdfx binari, che
pysd non sa leggere. Il supporto CSV di pysd funziona solo in modalita'
posizionale ("row") che:
  * assegna le righe ai subscript PER ORDINE (non per etichetta), e
  * supporta al massimo UNA dimensione subscript di taglia > 1 per lettura.

Questo script, per ogni GET VDF DATA('FILE.vdfx', 'Serie[sig]', ...):
  1. Parsea le famiglie di subscript da SURE.mdl.
  2. Spezza le serie multi-dimensionali in piu' letture 1-D, fissando tutte le
     dimensioni tranne la piu' grande (la dimensione "libera").
  3. Ricostruisce le righe referenziate nell'ordine esatto in cui pysd le legge
     (dim libera contigua), accoppiando le righe sorgente PER ETICHETTA
     (case-insensitive) -> indipendente dall'ordine del CSV sorgente.
  4. Scrive un CSV riordinato per file di input (<nome>_pysd.csv).
  5. Riscrive ogni equazione in una o piu'
        Var[...]:= GET DIRECT DATA('<nome>_pysd.csv', '', '1', 'B<primariga>')
     e scrive SURE_pysd.mdl (l'originale resta intatto).

Sorgenti CSV attese: <nome>.csv (comma-delimited, etichette quotate), prodotte
da pysd_export_vdf.py.
"""
import re
import csv
import itertools
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import sure_paths as paths  # noqa: E402

MODEL_DIR = paths.VENSIM
SRC_MDL = paths.SRC_MDL
ENC = "latin-1"


def join_continuations(text: str) -> str:
    return re.sub(r"\\\s*\n\s*", " ", text)


def parse_families(text: str) -> dict:
    joined = join_continuations(text)
    families = {}
    pat = re.compile(r"(?m)^([A-Za-z][A-Za-z0-9 _]*?)\s*:\s*([^~]+?)\s*~")
    for name, body in pat.findall(joined):
        name = name.strip()
        if any(tok in body for tok in ("=", "(", "GET ", "[")):
            continue
        elems = [e.strip() for e in body.split(",") if e.strip()]
        if not elems:
            continue
        if len(elems) == 1 and elems[0].upper() in {"INTERPOLATE", "RAW", "LOOKUP"}:
            continue
        families[name] = elems
    return families


# Full equation:  Name [subs] <op>  GET VDF DATA(...)  ~ units ~ comment |
NAME = r"(?P<name>[A-Za-z][^\n|~=\[]*?)"
SUBS = r"(?P<subs>\[[^\]]*\])?"
OP = r"(?P<op>(?::[A-Z][A-Za-z ]*)?:{0,2}=)"
VDF = (r"GET VDF DATA\(\s*'(?P<file>[^']+\.vdfx)'[\s\\]*,[\s\\]*"
       r"'(?P<series>[^']+)'[\s\\]*,[\s\\0-9,]*?\)")
TAIL = r"(?P<tail>~[^|]*\|)"
EQ_PAT = re.compile(NAME + r"\s*" + SUBS + r"\s*" + OP + r"\s*" + VDF + r"\s*" + TAIL, re.S)


def split_series(series: str):
    m = re.match(r"^(.*?)\[(.*)\]$", series.strip())
    if m:
        return m.group(1).strip(), [s.strip() for s in m.group(2).split(",")]
    return series.strip(), []


def load_csv(path: Path):
    header = None
    rows = {}
    with open(path, "r", encoding=ENC, newline="") as f:
        for i, row in enumerate(csv.reader(f)):
            if not row:
                continue
            label = row[0].strip().strip('"')
            if i == 0 and label.lower() == "time":
                header = row
                continue
            rows[label.lower()] = row
    if header is None:
        raise SystemExit(f"Nessuna riga header 'Time' trovata in {path}")
    return header, rows


def plan_blocks(sig, families):
    """
    Ritorna lista di (subs_tokens, combos):
      subs_tokens: token subscript per il LHS dell'equazione (nome famiglia per
                   la dim libera, elemento per le dim fisse).
      combos:      lista ordinata di tuple di elementi (righe CSV per il blocco).
    """
    if not sig:
        return [([], [()])]
    dims = []
    for tok in sig:
        if tok in families:
            dims.append((tok, families[tok]))
        else:
            dims.append((tok, [tok]))  # elemento fisso (taglia 1)
    big = [i for i, (t, e) in enumerate(dims) if len(e) > 1]

    if len(big) <= 1:
        subs = [t for (t, e) in dims]
        combos = list(itertools.product(*[e for (t, e) in dims]))
        return [(subs, combos)]

    free = max(big, key=lambda i: len(dims[i][1]))
    fixed_idx = [i for i in range(len(dims)) if i != free]
    blocks = []
    for combo_fixed in itertools.product(*[dims[i][1] for i in fixed_idx]):
        subs = [None] * len(dims)
        for pos, i in enumerate(fixed_idx):
            subs[i] = combo_fixed[pos]
        subs[free] = dims[free][0]
        combos = []
        for fe in dims[free][1]:
            elems = [None] * len(dims)
            for pos, i in enumerate(fixed_idx):
                elems[i] = combo_fixed[pos]
            elems[free] = fe
            combos.append(tuple(elems))
        blocks.append((subs, combos))
    return blocks


def main():
    out_mdl = paths.pysd_mdl()
    print(paths.describe())
    text = SRC_MDL.read_text(encoding=ENC)
    families = parse_families(text)
    print("Famiglie parseate (taglie):")
    for fam in ["District", "HS", "Type", "Performance", "PVpanel", "Vechicle",
                "Month", "Hour"]:
        print(f"  {fam}: {len(families.get(fam, []))}")

    src_cache = {}          # csv_name -> (header, rows)
    out_bodies = {}         # out_name -> list of rows
    out_headers = {}        # out_name -> header
    problems = []
    stats = {"matches": 0, "eqs": 0}

    def repl(m):
        stats["matches"] += 1
        vdfx, series = m.group("file"), m.group("series")
        name, op, tail = m.group("name").strip(), m.group("op"), m.group("tail")
        csv_name = vdfx[:-5] + ".csv"
        out_name = paths.data_csv(vdfx)
        src_path = MODEL_DIR / csv_name
        if not src_path.is_file():
            problems.append(f"CSV sorgente mancante: {csv_name} (per '{series}')")
            return m.group(0)
        if csv_name not in src_cache:
            src_cache[csv_name] = load_csv(src_path)
        header, rows = src_cache[csv_name]
        out_bodies.setdefault(out_name, [])
        out_headers[out_name] = header

        series_base, series_sig = split_series(series)
        blocks = plan_blocks(series_sig, families)

        eqs = []
        for subs, combos in blocks:
            labels = [series_base if not c else f"{series_base}[{','.join(c)}]"
                      for c in combos]
            missing = [lb for lb in labels if lb.lower() not in rows]
            if missing:
                problems.append(
                    f"{csv_name}: '{series}' -> mancano {len(missing)}/{len(labels)}"
                    f" etichette (es. {missing[:3]})")
                continue
            start = len(out_bodies[out_name]) + 2  # +1 header, prossima riga 1-indexed
            for lb in labels:
                out_bodies[out_name].append(rows[lb.lower()])
            subs_str = "" if not subs else "[" + ",".join(subs) + "]"
            eqs.append(
                f"{name}{subs_str}{op} GET DIRECT DATA('{out_name}', '', '1', "
                f"'B{start}') {tail}")
        stats["eqs"] += len(eqs)
        return "\n\n".join(eqs) if eqs else m.group(0)

    new_text, n = EQ_PAT.subn(repl, text)

    print(f"\nEquazioni GET VDF DATA trovate: {stats['matches']}")
    print(f"Equazioni GET DIRECT DATA generate: {stats['eqs']}")

    print("\nScrittura CSV riordinati:")
    for out_name, body in out_bodies.items():
        p = MODEL_DIR / out_name
        with open(p, "w", encoding=ENC, newline="") as f:
            w = csv.writer(f)
            w.writerow(out_headers[out_name])
            w.writerows(body)
        print(f"  {out_name}: {len(body)} righe dati")

    if problems:
        print("\nPROBLEMI:")
        for pr in problems[:40]:
            print("  -", pr)
        if len(problems) > 40:
            print(f"  ... e altri {len(problems) - 40}")
        raise SystemExit("Interrotto: risolvere i problemi sopra prima di tradurre.")

    remaining = new_text.count("GET VDF DATA")
    out_mdl.write_text(new_text, encoding=ENC)
    print(f"\nScritto {out_mdl}")
    print(f"Occorrenze 'GET VDF DATA' rimaste: {remaining}")
    if remaining:
        raise SystemExit("Inaspettato: non tutte le GET VDF DATA sono state riscritte.")


if __name__ == "__main__":
    main()
