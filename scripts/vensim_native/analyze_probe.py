"""Cell-level reading of the native allocator probe. Does not relax tolerances."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
PROBE = ROOT / "dist" / "sure-alignment" / "native-probe"
RESULT = ROOT / "dist" / "sure-alignment" / "native-probe-result"


def limit(expected, values):
    rounded = np.float32(values)
    half_ulp = np.maximum(
        np.nextafter(rounded, np.float32(np.inf)).astype(float) - values,
        values - np.nextafter(rounded, np.float32(-np.inf)).astype(float),
    ) / 2
    return 1e-10 * np.maximum(1, np.abs(expected)) + 1e-8 * np.abs(expected) + half_ulp


def marginal(priority, allocation):
    """Last supplier in descending priority with a strictly positive raw allocation.

    No fixed cutoff is applied. A 1e-17 Python residual and a 1e-7 native spill
    are both retained so the caller can see which magnitude actually moved.
    """
    order = np.argsort(-np.asarray(priority), kind="mergesort")
    chosen = None
    for index in order:
        if allocation[index] > 0:
            chosen = int(index)
    return chosen


def main():
    cases = json.loads((PROBE / "cases.json").read_text(encoding="utf-8"))
    native = json.loads((RESULT / "native.json").read_text(encoding="utf-8"))
    report = {"functions": {}, "shift_pairs": [], "groups": {}}
    cell_fail = {}
    for kind in ("Available allocation", "Priority allocation"):
        cell_fail[kind] = {"cells": 0, "cases": 0, "max_abs": 0.0, "max_balance": 0.0,
                           "marginal_changes": []}
    vectors = {}
    for case in cases:
        expected = np.asarray(case["expected"], dtype=float)
        request = np.asarray(case["request"], dtype=float)
        priority = np.asarray(case["priority"], dtype=float)
        vectors[case["id"]] = {}
        for kind in ("Available allocation", "Priority allocation"):
            values = np.array([native["series"][f"{kind}[{case['id']},S{i}]"]["values"][0]
                               for i in range(9)], dtype=float)
            vectors[case["id"]][kind] = values
            error = np.abs(values - expected)
            bound = limit(expected, values)
            failed = error > bound
            balance = float(values.sum() - min(request.sum(), case["supply"]))
            expected_marginal = marginal(priority, expected)
            native_marginal = marginal(priority, values)
            entry = cell_fail[kind]
            entry["cells"] += int(failed.sum())
            entry["cases"] += int(failed.any())
            entry["max_abs"] = max(entry["max_abs"], float(error.max()))
            entry["max_balance"] = max(entry["max_balance"], abs(balance))
            if native_marginal != expected_marginal:
                entry["marginal_changes"].append({
                    "id": case["id"], "shift": case.get("shift"), "boundary": case.get("boundary"),
                    "offset": case.get("offset"), "expected_marginal": expected_marginal,
                    "native_marginal": native_marginal, "max_abs": float(error.max()),
                    "balance_error": balance,
                    "expected_at_native_marginal": None if native_marginal is None else float(expected[native_marginal]),
                    "native_at_native_marginal": None if native_marginal is None else float(values[native_marginal]),
                    "expected_at_expected_marginal": None if expected_marginal is None else float(expected[expected_marginal]),
                    "native_at_expected_marginal": None if expected_marginal is None else float(values[expected_marginal]),
                })
    # Priority translation: same requests and supplies, priorities increased by 200.
    shifted = [c for c in cases if c.get("shift") == 200.0]
    base = {c["id"]: c for c in cases if c.get("shift") == 0.0}
    # Generator order is shift 0 for all boundary cases, then shift 200.
    bases = [c for c in cases if c.get("shift") == 0.0]
    pair_delta = {kind: 0.0 for kind in cell_fail}
    for left, right in zip(bases, shifted):
        for kind in pair_delta:
            delta = np.max(np.abs(vectors[left["id"]][kind] - vectors[right["id"]][kind]))
            pair_delta[kind] = max(pair_delta[kind], float(delta))
    negative = [c for c in cases if np.any(np.asarray(c["priority"]) < 0)]
    positive = [c for c in cases if np.all(np.asarray(c["priority"]) >= 0)]
    def group_stats(selected):
        out = {}
        ids = {c["id"] for c in selected}
        for kind, entry in cell_fail.items():
            changes = [item for item in entry["marginal_changes"] if item["id"] in ids]
            max_abs = 0.0
            for case in selected:
                error = np.abs(vectors[case["id"]][kind] - np.asarray(case["expected"]))
                max_abs = max(max_abs, float(error.max()))
            out[kind] = {"cases": len(selected), "max_abs": max_abs,
                         "marginal_changes": len(changes)}
        return out
    report["cell_failures"] = cell_fail
    report["translation_max_abs_native"] = pair_delta
    report["groups"] = {
        "negative_priority": group_stats(negative),
        "translated_or_nonnegative": group_stats(positive),
    }
    report["n_cases"] = len(cases)
    destination = RESULT / "cell-analysis.json"
    destination.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({
        "cell_failures": {k: {kk: vv for kk, vv in v.items() if kk != "marginal_changes"} | {
            "marginal_changes": len(v["marginal_changes"])} for k, v in cell_fail.items()},
        "translation_max_abs_native": pair_delta,
        "groups": report["groups"],
    }, indent=2))


if __name__ == "__main__":
    main()
