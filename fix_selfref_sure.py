"""Fase 4 - Corregge le equazioni subscript auto-referenziali nel modello
pysd tradotto (Vensim/SURE_pysd.py).

Vensim permette a un'equazione di definire alcuni elementi di un array in
funzione di altri elementi dello STESSO array, es.

    Coeff High[DFH] = Coeff High[SFH]

Vensim le valuta simultaneamente. pysd invece emette, dentro la funzione
`coeff_high()`, una chiamata a `coeff_high()` stessa:

    value.loc[["DFH"], :] = coeff_high().loc["SFH", :]...

che ricorre all'infinito (la cache e' vuota mentre la funzione gira).

Per ogni funzione top-level generata che chiama se stessa, questo script:
  * raggruppa il corpo in statement (bilanciando parentesi/graffe),
  * sposta gli statement auto-referenzianti dopo quelli non auto-referenzianti,
  * riscrive la self-call `NOME()` -> la locale `value`.

Idempotente: eseguirlo due volte e' un no-op.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import sure_paths as paths  # noqa: E402

PY = paths.pysd_py()


def self_call_re(name):
    # NOME() non preceduto da '.' o da un word char (esclude chiamate a metodo)
    return re.compile(r"(?<![.\w])" + re.escape(name) + r"\(\)")


def group_statements(body_lines):
    """Raggruppa le righe indentate del corpo in statement bilanciando le parentesi."""
    stmts, cur, depth = [], [], 0
    for ln in body_lines:
        cur.append(ln)
        depth += ln.count("(") + ln.count("[") + ln.count("{")
        depth -= ln.count(")") + ln.count("]") + ln.count("}")
        if depth <= 0 and ln.strip():
            stmts.append("".join(cur))
            cur, depth = [], 0
    if cur:
        stmts.append("".join(cur))
    return stmts


def fix_function(name, body):
    scr = self_call_re(name)
    if not scr.search(body):
        return body, False

    lines = body.splitlines(keepends=True)
    stmts = group_statements(lines)
    if not stmts:
        return body, False

    # Mantiene l'init `value = ...` in testa e un eventuale `return ...` in coda.
    prefix, middle, suffix = [], [], []
    for st in stmts:
        stripped = st.strip()
        if not middle and (stripped.startswith("value =") or not stripped):
            prefix.append(st)
        elif stripped.startswith("return "):
            suffix.append(st)
        else:
            middle.append(st)

    if not any(scr.search(st) for st in middle):
        # la self-call non e' in uno statement riordinabile; fallback: rewrite semplice
        return scr.sub("value", body), True

    base = [st for st in middle if not scr.search(st)]
    selfref = [scr.sub("value", st) for st in middle if scr.search(st)]

    new_body = "".join(prefix + base + selfref + suffix)
    return new_body, True


def main():
    print(f"Fix self-ref su {PY.name}")
    src = PY.read_text(encoding="utf-8")
    lines = src.splitlines(keepends=True)

    def_idx = [
        (i, re.match(r"^def ([a-zA-Z_][a-zA-Z0-9_]*)\(\):\s*$", ln).group(1))
        for i, ln in enumerate(lines)
        if re.match(r"^def ([a-zA-Z_][a-zA-Z0-9_]*)\(\):\s*$", ln)
    ]

    names_by_pos = {i: n for i, n in def_idx}
    fixed = []
    result = []
    i = 0
    while i < len(lines):
        if i in names_by_pos:
            name = names_by_pos[i]
            result.append(lines[i])  # riga def
            j = i + 1
            while j < len(lines) and (lines[j].startswith((" ", "\t")) or not lines[j].strip()):
                j += 1
            body = "".join(lines[i + 1:j])
            new_body, changed = fix_function(name, body)
            result.append(new_body)
            if changed:
                fixed.append(name)
            i = j
        else:
            result.append(lines[i])
            i += 1

    PY.write_text("".join(result), encoding="utf-8")
    print(f"Funzioni auto-referenziali corrette: {len(fixed)}")
    for n in fixed:
        print("  ", n)


if __name__ == "__main__":
    main()
