"""Cell-wise housing and transfer invariants for the corrected SURE model."""
import numpy as np


class PhysicalInvariantError(ValueError):
    """Keep failed numerical arrays available for diagnosis, never acceptance."""
    def __init__(self, report, arrays):
        super().__init__(f"Housing stock or transfer invariant failed: {report}")
        self.report = report
        self.arrays = arrays


OUTPUTS = [
    "Heating Solution", "Annual archetypes", "Total Res buildings",
    "Buildings adopting HS", "Buildings leaving HS", "Buildings construction with battery",
    "Building demolition by archetype", "Buildings HS Renovation From", "Buildings HS Renovation To",
    "Consumers leaving HS for old age", "Buildings adopting HS for old age",
    "Consumers adopting PV no", "Consumers adopting PV yes with battery",
    "Consumers adopting RCPv yes with battery",
]
TRANSFERS = OUTPUTS[6:]


def check(arrays):
    missing = set(OUTPUTS)-set(arrays)
    if missing:
        return {"pass": False, "reason": "Missing physical diagnostics", "missing": sorted(missing)}
    rows = {}
    for name in OUTPUTS:
        a = arrays[name]
        if a.shape[0] != 40 or not np.isfinite(a).all():
            return {"pass": False, "reason": "Invalid physical diagnostic", "variable": name}
    for name in ["Heating Solution", "Annual archetypes", "Total Res buildings", *TRANSFERS]:
        a = arrays[name]
        tolerance = 1e-10*np.maximum(1.,np.abs(a).max(axis=0))
        bad = a < -tolerance
        rows['nonnegative:'+name] = {"pass": not bool(bad.any()), "minimum": float(a.min()),
                                     "failures": int(bad.sum())}
        if bad.any():rows['nonnegative:'+name]['first_index'] = np.argwhere(bad)[0].tolist()

    def balanced(name, a, b):
        error = abs(a-b)
        tolerance = 1e-10*np.maximum(1.,np.maximum(abs(a).max(axis=0),abs(b).max(axis=0)))
        bad = error > tolerance
        rows[name] = {"pass": not bool(bad.any()), "max_abs": float(error.max()), "failures": int(bad.sum())}
        if bad.any():rows[name]['first_index'] = np.argwhere(bad)[0].tolist()

    s = arrays['Heating Solution']
    balanced('annual_euler', s[1:],s[:-1]+arrays['Buildings adopting HS'][:-1]-arrays['Buildings leaving HS'][:-1])
    balanced('heating_transfer',arrays['Buildings adopting HS for old age'].sum(axis=2),arrays['Consumers leaving HS for old age'].sum(axis=2))
    balanced('renovation_transfer',arrays['Buildings HS Renovation To'].sum(axis=3),arrays['Buildings HS Renovation From'].sum(axis=3))
    balanced('pv_transfer',(arrays['Consumers adopting PV yes with battery']+arrays['Consumers adopting RCPv yes with battery']).sum(axis=(5,6)),arrays['Consumers adopting PV no'].sum(axis=(5,6)))
    # The input files have a small, fixed initial fine/coarse discrepancy.
    # Require preservation of that explicit offset, never a drifting balance.
    fine, coarse = s.sum(axis=(2,5,6)),arrays['Total Res buildings']
    balanced('fine_coarse_changes',fine-fine[0],coarse-coarse[0])
    balanced('external_balance',s[1:].sum(axis=(2,3,5,6)),s[:-1].sum(axis=(2,3,5,6))+(arrays['Buildings construction with battery'][:-1]-arrays['Building demolition by archetype'][:-1]).sum(axis=(2,3,5,6)))
    return {"pass": all(r['pass'] for r in rows.values()), "checks": rows,
            "initial_fine_coarse_max_abs": float(abs(fine[0]-coarse[0]).max())}
