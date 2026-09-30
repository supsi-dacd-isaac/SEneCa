"""Post-process Vensim/SURE_pysd.py: replace xarray-heavy hot paths with numpy.

Target families (from _profile_out.txt):
  - utility_hs_exp_3 / utility_hs_exp_3_no_incentives  (repeated .loc + 4x u2 reads)
  - market_share_hs* / market_share_hs_no_incentives*  (xarray sum + suitability broadcast)

Pure numpy (no numba). Idempotent via '# hotpath:' markers.
Adapted from Possible usefull files/patch_hotpaths.py (Canton -> District).

Uso:
    .\\.venv\\Scripts\\python.exe patch_hotpaths_sure.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import sure_paths as paths  # noqa: E402

PY = paths.pysd_py()

HELPERS = '''
def _hotpath_asarray(arr):
    return arr.values if isinstance(arr, xr.DataArray) else np.asarray(arr)


def _hotpath_idx_list(dim, labels):
    names = _subscript_dict[dim]
    if isinstance(labels, str):
        return [names.index(labels)]
    return [names.index(x) for x in labels]


def _hotpath_dt_broadcast_5d(arr):
    """Broadcast (District, Type) -> (District, HS, Performance, Type, PVpanel)."""
    v = _hotpath_asarray(arr)
    return v[:, np.newaxis, np.newaxis, :, np.newaxis]


def _hotpath_da_like(template, values):
    # Always construct a new DataArray (never shallow-copy+mutate): mutating a
    # shallow copy can corrupt PySD's per-step function cache.
    if isinstance(template, xr.DataArray):
        return xr.DataArray(
            values, coords=template.coords, dims=template.dims, name=template.name
        )
    return xr.DataArray(
        values,
        {
            "District": _subscript_dict["District"],
            "HS": _subscript_dict["HS"],
            "Performance": _subscript_dict["Performance"],
            "Type": _subscript_dict["Type"],
            "PVpanel": _subscript_dict["PVpanel"],
        },
        ["District", "HS", "Performance", "Type", "PVpanel"],
    )


def _hotpath_ms_normalize(vals):
    denom = vals.sum(axis=1, keepdims=True)
    return vals / denom


def _hotpath_ms_exclude(ms, exclude_labels):
    """Zero selected HS labels and renormalize (nogas / nodh / etc.)."""
    vals = np.array(_hotpath_asarray(ms), copy=True, dtype=float)
    excl = _hotpath_idx_list("HS", exclude_labels)
    vals[:, excl, :, :, :] = 0.0
    return _hotpath_da_like(ms, _hotpath_ms_normalize(vals))


def _hotpath_da_like_6d(template, values):
    """DataArray like template with Battery as 6th dim."""
    if isinstance(template, xr.DataArray):
        return xr.DataArray(
            values, coords=template.coords, dims=template.dims, name=template.name
        )
    return xr.DataArray(
        values,
        {
            "District": _subscript_dict["District"],
            "HS": _subscript_dict["HS"],
            "Performance": _subscript_dict["Performance"],
            "Type": _subscript_dict["Type"],
            "PVpanel": _subscript_dict["PVpanel"],
            "Battery": _subscript_dict["Battery"],
        },
        ["District", "HS", "Performance", "Type", "PVpanel", "Battery"],
    )


def _hotpath_build_utility_hs_exp_3(u2):
    """Build utility HS exp 3 from utility exp 2 (single u2 read, numpy indexing)."""
    u2v = _hotpath_asarray(u2)
    value = np.full_like(u2v, np.nan)
    one_minus = 1.0 - float(_hotpath_asarray(muken_2025_scenario_application()))

    hs_r = _hotpath_idx_list("HS", _subscript_dict["RenSolution"])
    value[:, hs_r, :, :, :] = u2v[:, hs_r, :, :, :]

    hs_nr = _hotpath_idx_list("HS", _subscript_dict["NonRenSolution"])
    pf_l = _hotpath_idx_list("Performance", _subscript_dict["PerformanceLow"])
    for hi in hs_nr:
        value[:, hi, pf_l, :, :] = u2v[:, hi, pf_l, :, :] * one_minus

    pf_h = _hotpath_idx_list("Performance", _subscript_dict["PerformanceHigh"])
    mod = _subscript_dict["Performance"].index("Moderate")
    for hi in hs_nr:
        for pi in pf_h:
            if pi == mod:
                continue
            value[:, hi, pi, :, :] = u2v[:, hi, pi, :, :]
        value[:, hi, mod, :, :] = u2v[:, hi, mod, :, :] * one_minus

    return _hotpath_da_like(u2, value)

'''

PATCHES: list[tuple[str, str, str]] = [
    (
        "# hotpath: utility_hs_exp_3_no_incentives",
        r"def utility_hs_exp_3_no_incentives\(\):\n(?:.*?\n)*?(?=\n@component\.add|\n\ndef )",
        '''def utility_hs_exp_3_no_incentives():
    # hotpath: utility_hs_exp_3_no_incentives
    return _hotpath_build_utility_hs_exp_3(utility_hs_exp_2_no_incentives())
''',
    ),
    (
        "# hotpath: utility_hs_exp_3",
        r"def utility_hs_exp_3\(\):\n(?:.*?\n)*?(?=\n@component\.add|\n\ndef )",
        '''def utility_hs_exp_3():
    # hotpath: utility_hs_exp_3
    return _hotpath_build_utility_hs_exp_3(utility_hs_exp_2())
''',
    ),
    (
        "# hotpath: market_share_hs_no_incentives",
        r"def market_share_hs_no_incentives\(\):\n(?:.*?\n)*?(?=\n@component\.add|\n\ndef )",
        '''def market_share_hs_no_incentives():
    # hotpath: market_share_hs_no_incentives
    u = utility_hs_exp_3_no_incentives()
    vals = _hotpath_asarray(u)
    return _hotpath_da_like(u, _hotpath_ms_normalize(vals))
''',
    ),
    (
        "# hotpath: market_share_hs",
        r"def market_share_hs\(\):\n(?:.*?\n)*?(?=\n@component\.add|\n\ndef )",
        '''def market_share_hs():
    # hotpath: market_share_hs
    u = utility_hs_exp_3()
    vals = _hotpath_asarray(u)
    return _hotpath_da_like(u, _hotpath_ms_normalize(vals))
''',
    ),
    (
        "# hotpath: market_share_hs_no_incentives_filtered",
        r"def market_share_hs_no_incentives_filtered\(\):\n(?:.*?\n)*?(?=\n@component\.add|\n\ndef )",
        '''def market_share_hs_no_incentives_filtered():
    # hotpath: market_share_hs_no_incentives_filtered
    ms = _hotpath_asarray(market_share_hs_no_incentives())
    ms_ng = _hotpath_asarray(market_share_hs_no_incentives_nogas())
    ms_nd = _hotpath_asarray(market_share_hs_no_incentives_nodh())
    ms_ndng = _hotpath_asarray(market_share_hs_no_incentives_nodh_nogas())
    w0 = _hotpath_dt_broadcast_5d(dh_and_gas_suitability())
    w1 = _hotpath_dt_broadcast_5d(dh_only_suitability())
    w2 = _hotpath_dt_broadcast_5d(gas_only_suitability())
    w3 = _hotpath_dt_broadcast_5d(no_suitability())
    out = ms * w0 + ms_ng * w1 + ms_nd * w2 + ms_ndng * w3
    return _hotpath_da_like(market_share_hs_no_incentives(), out)
''',
    ),
    (
        "# hotpath: market_share_hs_filtered",
        r"def market_share_hs_filtered\(\):\n(?:.*?\n)*?(?=\n@component\.add|\n\ndef )",
        '''def market_share_hs_filtered():
    # hotpath: market_share_hs_filtered
    ms = _hotpath_asarray(market_share_hs())
    ms_ng = _hotpath_asarray(market_share_hs_nogas())
    ms_nd = _hotpath_asarray(market_share_hs_nodh())
    ms_ndng = _hotpath_asarray(market_share_hs_nodh_nogas())
    w0 = _hotpath_dt_broadcast_5d(dh_and_gas_suitability())
    w1 = _hotpath_dt_broadcast_5d(dh_only_suitability())
    w2 = _hotpath_dt_broadcast_5d(gas_only_suitability())
    w3 = _hotpath_dt_broadcast_5d(no_suitability())
    out = ms * w0 + ms_ng * w1 + ms_nd * w2 + ms_ndng * w3
    return _hotpath_da_like(market_share_hs(), out)
''',
    ),
    (
        "# hotpath: market_share_hs_nogas",
        r"def market_share_hs_nogas\(\):\n(?:.*?\n)*?(?=\n@component\.add|\n\ndef )",
        '''def market_share_hs_nogas():
    # hotpath: market_share_hs_nogas
    return _hotpath_ms_exclude(market_share_hs(), _subscript_dict["WithGas"])
''',
    ),
    (
        "# hotpath: market_share_hs_nodh",
        r"def market_share_hs_nodh\(\):\n(?:.*?\n)*?(?=\n@component\.add|\n\ndef )",
        '''def market_share_hs_nodh():
    # hotpath: market_share_hs_nodh
    return _hotpath_ms_exclude(market_share_hs(), ["DH"])
''',
    ),
    (
        "# hotpath: market_share_hs_nodh_nogas",
        r"def market_share_hs_nodh_nogas\(\):\n(?:.*?\n)*?(?=\n@component\.add|\n\ndef )",
        '''def market_share_hs_nodh_nogas():
    # hotpath: market_share_hs_nodh_nogas
    return _hotpath_ms_exclude(market_share_hs_nodh(), _subscript_dict["WithGas"])
''',
    ),
    (
        "# hotpath: market_share_hs_no_incentives_nogas",
        r"def market_share_hs_no_incentives_nogas\(\):\n(?:.*?\n)*?(?=\n@component\.add|\n\ndef )",
        '''def market_share_hs_no_incentives_nogas():
    # hotpath: market_share_hs_no_incentives_nogas
    return _hotpath_ms_exclude(
        market_share_hs_no_incentives(), _subscript_dict["WithGas"]
    )
''',
    ),
    (
        "# hotpath: market_share_hs_no_incentives_nodh",
        r"def market_share_hs_no_incentives_nodh\(\):\n(?:.*?\n)*?(?=\n@component\.add|\n\ndef )",
        '''def market_share_hs_no_incentives_nodh():
    # hotpath: market_share_hs_no_incentives_nodh
    return _hotpath_ms_exclude(market_share_hs_no_incentives(), ["DH"])
''',
    ),
    (
        "# hotpath: market_share_hs_no_incentives_nodh_nogas",
        r"def market_share_hs_no_incentives_nodh_nogas\(\):\n(?:.*?\n)*?(?=\n@component\.add|\n\ndef )",
        '''def market_share_hs_no_incentives_nodh_nogas():
    # hotpath: market_share_hs_no_incentives_nodh_nogas
    return _hotpath_ms_exclude(
        market_share_hs_no_incentives_nodh(), _subscript_dict["WithGas"]
    )
''',
    ),
]


def _insert_helpers(src: str) -> str:
    if "_hotpath_ms_exclude" in src:
        return src
    if "_hotpath_asarray" in src:
        # Upgrade v1 helpers already present
        needle = "def _hotpath_ms_normalize(vals):\n    denom = vals.sum(axis=1, keepdims=True)\n    return vals / denom\n"
        extra = '''def _hotpath_ms_normalize(vals):
    denom = vals.sum(axis=1, keepdims=True)
    return vals / denom


def _hotpath_ms_exclude(ms, exclude_labels):
    """Zero selected HS labels and renormalize (nogas / nodh / etc.)."""
    vals = np.array(_hotpath_asarray(ms), copy=True, dtype=float)
    excl = _hotpath_idx_list("HS", exclude_labels)
    vals[:, excl, :, :, :] = 0.0
    return _hotpath_da_like(ms, _hotpath_ms_normalize(vals))


def _hotpath_da_like_6d(template, values):
    """DataArray like template with Battery as 6th dim."""
    if isinstance(template, xr.DataArray):
        return xr.DataArray(
            values, coords=template.coords, dims=template.dims, name=template.name
        )
    return xr.DataArray(
        values,
        {
            "District": _subscript_dict["District"],
            "HS": _subscript_dict["HS"],
            "Performance": _subscript_dict["Performance"],
            "Type": _subscript_dict["Type"],
            "PVpanel": _subscript_dict["PVpanel"],
            "Battery": _subscript_dict["Battery"],
        },
        ["District", "HS", "Performance", "Type", "PVpanel", "Battery"],
    )

'''
        if needle not in src:
            raise RuntimeError("Could not upgrade helpers in SURE_pysd.py")
        return src.replace(needle, extra, 1)
    anchor = '__data = {"scope": None, "time": lambda: 0}\n'
    if anchor not in src:
        raise RuntimeError("Could not find helper insertion point in SURE_pysd.py")
    return src.replace(anchor, anchor + HELPERS, 1)


def _has_hotpath_marker(src: str, marker: str) -> bool:
    tag = marker.strip()
    return any(line.strip() == tag for line in src.splitlines())


def _apply_patch(src: str, marker: str, pattern: str, replacement: str) -> tuple[str, bool]:
    if _has_hotpath_marker(src, marker):
        return src, False
    new_src, n = re.subn(pattern, replacement + "\n", src, count=1, flags=re.MULTILINE)
    if n != 1:
        raise RuntimeError(f"Could not apply patch for {marker!r} (matches={n})")
    return new_src, True


def main():
    original = PY.read_text(encoding="utf-8")
    src = _insert_helpers(original)
    applied = []
    for marker, pattern, body in PATCHES:
        src, ok = _apply_patch(src, marker, pattern, body.rstrip())
        if ok:
            applied.append(marker.split(":")[-1].strip())

    if not applied and src == original:
        print("patch_hotpaths_sure: all hotpaths already applied")
    else:
        bak = PY.with_suffix(".py.pre_hotpath")
        if not bak.exists():
            bak.write_text(original, encoding="utf-8")
            print(f"backup: {bak.name}")
        PY.write_text(src, encoding="utf-8")
        print("patch_hotpaths_sure: applied", len(applied), "patch(es):")
        for name in applied:
            print(f"  - {name}")


if __name__ == "__main__":
    main()
