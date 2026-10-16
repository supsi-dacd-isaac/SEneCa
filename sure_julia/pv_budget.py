"""Verify the shared PV adoption budget already present in canonical SURE v7.

The correction is part of Vensim/SURE.mdl; no second executable model is generated.
"""
import argparse
from pathlib import Path
import re
from .common import ROOT, MODEL_REVISION, digest, dump, read

REVISION = MODEL_REVISION
FLOWS = [f"{owner} adopting {kind}" for owner in ("Owners", "Renters")
         for kind in ("PV", "RCP", "RCPv")]
DIMS = "[District,HS,Performance,Type]"
SOURCE_DIMS = "[District,HS,Performance,Type,PVno,Bno]"
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



def budget_audit(source):
    model = source.partition(MARKER)[0]
    def normalize(text):
        return re.sub(r"\s+", "", text.replace("\\", "")).lower()
    checks = {}
    for name, expression in equations().items():
        blocks = re.findall(r"(?m)^" + re.escape(name) + r"\[District,HS,Performance,Type\]\s*=([^~]+)~", model)
        checks[name] = len(blocks) == 1 and normalize(blocks[0]) == normalize(expression)
    requests = {}
    for name in FLOWS:
        blocks = re.findall(r"(?m)^Requested " + re.escape(name) + r"\[.*?\|", model, re.S)
        requests[name] = [normalize(block.split("~")[0]) for block in blocks]
        checks["Requested " + name] = len(blocks) == (1 if name.endswith("RCPv") else 2)
    if not all(checks.values()):
        raise ValueError(f"PV source budget changed: {[n for n, ok in checks.items() if not ok]}")
    return {"checks": checks, "requests": requests}


def prepare(check=False):
    sources = [ROOT / "Vensim/SURE.mdl", ROOT / "Vensim/SURE_pysd_v7.mdl"]
    audits = [budget_audit(p.read_text(encoding="latin-1")) for p in sources]
    if audits[0] != audits[1]:
        raise ValueError("Native and preprocessed PV source budgets differ")
    audit = {"revision": REVISION, "sources": {str(p.relative_to(ROOT)): digest(p) for p in sources},
             "pass": True, "checks": audits[0]["checks"], "native_preprocessed_requests_identical": True}
    target = Path(__file__).with_name("pv-budget.json")
    if check:
        if read(target) != audit:
            raise ValueError("Stale PV source audit")
    else:
        dump(target, audit)
    print(f"{REVISION}: canonical native/preprocessed PV budgets verified")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    prepare(parser.parse_args().check)
