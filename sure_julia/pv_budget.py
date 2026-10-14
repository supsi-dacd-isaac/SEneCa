"""One source correction shared by native Vensim, Python and Julia.

Only the six PV adoption definitions change: their original clauses become
Requested helpers, and the accepted flows share one source-availability cap.
The upstream v6 files and all other equations/sketch records remain intact.
Run with Python 3.11.8 / PySD 3.14.3: python -m sure_julia.pv_budget.
"""
import argparse
import ast
from collections import Counter
import contextlib
import io
import re
import shutil
import tempfile
import warnings
from pathlib import Path

from .common import ROOT, digest, dump

REVISION = "sure-v6-pv-budget-2"
FLOWS = [f"{owner} adopting {kind}" for owner in ("Owners", "Renters")
         for kind in ("PV", "RCP", "RCPv")]
DIMS = "[District,HS,Performance,Type]"
SOURCE_DIMS = "[District,HS,Performance,Type,PVno,Bno]"
STEM = "SURE_pysd_v6_pvbounded"
NATIVE = "SURE_v6_pvbounded.mdl"
MARKER = "\\\\\\---///"


def equations():
    available = (f"MAX(0, Heating Solution{SOURCE_DIMS}/TIME STEP"
                 f" - MAX(0, Building demolition by archetype{SOURCE_DIMS})"
                 f" - MAX(0, Buildings HS Renovation From{SOURCE_DIMS}))")
    demand = " + ".join(f"MAX(0, Requested {name}{DIMS})" for name in FLOWS)
    total, budget = "Total PV request" + DIMS, "Available PV adoption" + DIMS
    # Export the continuous accepted amount, not a discontinuous 0/0 factor.
    # Both branches may be evaluated for arrays; keep the denominator nonzero.
    accepted = "Accepted PV adoption" + DIMS
    factor = f"({accepted}/IF THEN ELSE({total}>0, {total}, 1))"
    return {"Available PV adoption": available, "Total PV request": demand,
            "Accepted PV adoption": f"MIN({budget}, {total})",
            **{name: f"MAX(0, Requested {name}{DIMS}) * {factor}" for name in FLOWS}}


def corrected_source(source):
    model, marker, trailer = source.partition(MARKER)
    if not marker or "Requested Owners adopting PV[" in model:
        raise ValueError("Expected an unmodified v6 model with a sketch boundary")
    counts, originals, blocks = Counter(), {}, []
    # Match the LHS only, including the first equation after the encoding header.
    for block in model.split("|"):
        match = re.match(r"(?:\{[^}]+\})?\s*(?P<name>[^\[=]+?)(?=\[|=)", block)
        name = match.group("name").strip() if match else None
        if name in FLOWS:
            counts[name] += 1
            originals.setdefault(name, []).append(block[match.end("name"):].strip())
            block = block[:match.start("name")] + "Requested " + block[match.start("name"):]
        blocks.append(block)
    expected = {name: 1 if name.endswith("RCPv") else 2 for name in FLOWS}
    if dict(counts) != expected:
        raise ValueError(f"Unexpected v6 adoption clauses: {dict(counts)}")
    additions = []
    for name, expression in equations().items():
        additions.append(f"\n{name}{DIMS} =\n\t{expression}\n~ building/year\n~ {REVISION}: shared PV source budget.\n|")
    return "|".join(blocks[:-1]) + "|\n" + "\n".join(additions) + blocks[-1] + marker + trailer, originals


def component_asts(path):
    """Ignore docstrings/formatting; compare executable component definitions."""
    class OrderedMetadata(ast.NodeTransformer):
        def visit_Dict(self, node):
            self.generic_visit(node)
            if all(isinstance(k, ast.Constant) and isinstance(k.value, str) for k in node.keys):
                pairs = sorted(zip(node.keys, node.values), key=lambda pair: pair[0].value)
                node.keys, node.values = map(list, zip(*pairs)) if pairs else ([], [])
            return node
    result = {}
    for node in ast.parse(path.read_text()).body:
        if isinstance(node, ast.FunctionDef) and node.decorator_list:
            if node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant):
                node.body.pop(0)
            result[node.name] = ast.dump(OrderedMetadata().visit(node), include_attributes=False)
    return result


def prepare(check=False):
    import pysd
    if pysd.__version__ != "3.14.3":
        raise ValueError("Generate the Python reference with PySD 3.14.3")
    vensim = ROOT / "Vensim"
    sources = [vensim / "SURE_pysd_v6.mdl", vensim / "SURE.mdl"]
    audit = {"revision": REVISION, "sources": {str(p.relative_to(ROOT)): digest(p) for p in sources},
             "equations": equations(), "native_engine_checked": False}
    with tempfile.TemporaryDirectory() as temporary:
        directory = Path(temporary)
        clauses = []
        for original, name in zip(sources, [STEM + ".mdl", NATIVE]):
            corrected, requests = corrected_source(original.read_bytes().decode("latin-1"))
            clauses.append(requests)
            (directory / name).write_bytes(corrected.encode("latin-1"))
        if clauses[0] != clauses[1]:
            raise ValueError("Native and preprocessed v6 PV equations differ")
        for source in vensim.glob("*_pysd_v6.csv"):
            shutil.copy2(source, directory / source.name)
        shutil.copy2(sources[0], directory / sources[0].name)
        with warnings.catch_warnings(record=True) as baseline:
            warnings.simplefilter("always")
            pysd.read_vensim(directory / sources[0].name, initialize=False)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            pysd.read_vensim(directory / (STEM + ".mdl"), initialize=False)
        def warning_key(warning):
            message = str(warning.message)
            for name in FLOWS:
                message = message.replace("'Requested " + name + "'", "'" + name + "'")
            return warning.category.__name__, message
        if Counter(map(warning_key, caught)) != Counter(map(warning_key, baseline)):
            raise ValueError("Python translation warnings differ from the unmodified v6 source")
        if any(not re.match(r"Variable '.+' is defined with different (?:sub)?types:", str(w.message)) for w in caught):
            raise ValueError("Unclassified Python translation warning")
        audit["python_translation_warnings"] = sorted([
            {"category": w.category.__name__, "message": str(w.message),
             "classification": "Unchanged v6 mixed-clause metadata warning; full simulation validation required"}
            for w in caught], key=lambda row: row["message"])
        # Existing PySD compatibility fixes are part of the reference contract;
        # they fix translation mechanics, not the new housing equations.
        import fix_selfref_sure
        import fix_allocate_sure
        compatibility_log = io.StringIO()
        for module in (fix_selfref_sure, fix_allocate_sure):
            previous = module.PY
            try:
                module.PY = directory / (STEM + ".py")
                with contextlib.redirect_stdout(compatibility_log):
                    module.main()
            finally:
                module.PY = previous
        audit["python_compatibility_fixes"] = {
            str(Path(module.__file__).relative_to(ROOT)): digest(module.__file__)
            for module in (fix_selfref_sure, fix_allocate_sure)}
        audit["python_compatibility_log"] = compatibility_log.getvalue().splitlines()
        before = component_asts(vensim / "SURE_pysd_v6.py")
        after = component_asts(directory / (STEM + ".py"))
        changed = {name for name in before if after.get(name) != before[name]}
        expected = {name.lower().replace(" ", "_") for name in FLOWS}
        if changed != expected:
            debug = ROOT / "dist/julia-production/pv-budget-source-audit"
            debug.mkdir(parents=True, exist_ok=True)
            shutil.copy2(directory / (STEM + ".py"), debug / (STEM + ".py"))
            raise ValueError(f"Unexpected generated Python component changes: {changed ^ expected}")
        audit["unchanged_python_components"] = len(before) - len(changed)
        audit["renamed_request_clauses"] = {n: len(c) for n, c in clauses[0].items()}
        names = [STEM + ".mdl", STEM + ".py", NATIVE]
        audit["artifacts"] = {"Vensim/" + n: digest(directory / n) for n in names}
        for name in names:
            if check:
                if digest(vensim / name) != digest(directory / name):
                    raise ValueError(f"Stale source artifact: {name}")
            else:
                shutil.copy2(directory / name, vensim / name)
    target = Path(__file__).with_name("pv-budget.json")
    if check:
        import json
        if json.loads(target.read_text()) != audit:
            raise ValueError("Stale PV source audit")
    else:
        dump(target, audit)
    print(f"{REVISION}: native/preprocessed requests match; {audit['unchanged_python_components']} components unchanged")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    prepare(parser.parse_args().check)
