"""Bind verified, stable Python SUM layouts to experimental Vensim AST sites."""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from .common import RUNTIME, YEARS, check_sources, digest, read, run_logged


def layout_plan(record):
    """NumPy sums contiguous reduced tails pairwise, then outer blocks in order."""
    rank = len(record["dims"])
    physical = record["physical_axes_slow_to_fast"]
    reduced = set(record["reduce_axes"])
    if sorted(physical) != list(range(rank)) or not reduced <= set(physical):
        raise ValueError("Invalid recorded reduction axes")
    if not record["finite_input"]:
        raise ValueError("Nonfinite SUM input requires explicit reference semantics")
    if any(size <= 1 for size in record["shape"]):
        raise ValueError("Singleton/empty axis reduction layout has not been verified")
    blocksize = 1
    for axis in reversed(physical):
        if axis not in reduced:
            break
        blocksize *= record["shape"][axis]
    return {"reduced_order": [record["dims"][axis].removesuffix("!") for axis in physical if axis in reduced],
            "reduced_sizes": {record["dims"][axis].removesuffix("!"): record["shape"][axis] for axis in reduced},
            "blocksize": blocksize}


def calendar_plan(records_by_scenario, years=YEARS):
    """Accept an observed initial/remaining-grid split, never a layout guess."""
    first_time = years[0]
    contracts = []
    for scenario, records in records_by_scenario.items():
        by_year = {}
        for record in records:
            plan = layout_plan(record)
            for observation, count in record["observations"].items():
                stage, time = observation.rsplit(":", 1)
                time = float(time)
                if (count < 1 or time not in years or stage not in {"Initialization", "Run"}
                        or stage == "Initialization" and time != first_time):
                    raise ValueError(f"Unsupported SUM observation: {scenario}/{observation}")
                if time in by_year and by_year[time] != plan:
                    raise ValueError(f"Ambiguous SUM layout at the same time: {scenario}/{time}")
                by_year[time] = plan
        if set(by_year) != set(years):
            raise ValueError(f"Incomplete SUM calendar coverage: {scenario}/{set(years)-set(by_year)}")
        subsequent = by_year[years[1]]
        if any(by_year[year] != subsequent for year in years[1:]):
            raise ValueError(f"SUM layout changes after the first integration step: {scenario}")
        contract = {"initial_time": first_time, "initial": by_year[first_time],
                    "subsequent": subsequent, "observed_years": list(years)}
        if contracts and contract != contracts[0]:
            raise ValueError(f"SUM calendar layout differs between scenarios: {scenario}")
        contracts.append(contract)
    if not contracts:
        raise ValueError("No scenario observations for the SUM calendar contract")
    return contracts[0]


def ensure_policy(directory, case="base"):
    directory = Path(directory).resolve()
    manifest = read(directory / "manifest.json")
    check_sources(manifest)
    from . import reduction_audit
    cases = list(dict.fromkeys(["base", "high", case]))
    records_by_scenario, catalogs, evidence = {}, [], {}
    artifact_names = {"sites.json", "layouts.json", "samples.npz", "snapshot.json", "snapshot.npz"}
    for scenario in cases:
        target = directory / "debug/reduction-audit" / scenario
        reference = directory / "reference/diagnostic" / scenario
        def valid(report):
            return (report["pass"] and report["uint64_bitwise"] and report["hash_seed"] == "0"
                    and report["implementation"] == digest(Path(reduction_audit.__file__))
                    and report["sources"] == manifest["sources"] and report["pins"] == manifest["pins"]
                    and report["packages"] == manifest["packages"]
                    and set(report["artifacts"]) == artifact_names
                    and report["artifacts"] == {name: digest(target / name) for name in artifact_names}
                    and report["reference"] == {suffix: digest(reference.with_suffix(suffix)) for suffix in
                                               (".json", ".npz", ".params.json", ".provenance.json")})
        try:
            report = read(target / "result.json")
            ready = valid(report)
        except (OSError, KeyError, ValueError):
            ready = False
        if not ready:
            command = f"from scripts.julia_repro.reduction_audit import run; run({str(directory)!r}, case={scenario!r})"
            run_logged([RUNTIME / "python-reference/bin/python", "-B", "-c", command],
                       directory / "logs" / f"reduction-audit-{scenario}.log")
            report = read(target / "result.json")
            if not valid(report):
                raise RuntimeError(f"Unverified SUM layout audit: {scenario}")
        records_by_scenario[scenario] = read(target / "layouts.json")
        catalogs.append(read(target / "sites.json"))
        for name in sorted(artifact_names | {"result.json"}):
            evidence[str((target / name).relative_to(directory))] = digest(target / name)
    if any(catalog != catalogs[0] for catalog in catalogs[1:]):
        raise ValueError("Scenario audits have different Vensim/Python SUM bindings")
    by_id = {item["id"]: item for item in catalogs[0]["bindings"]}
    plans = defaultdict(list)
    observed = defaultdict(dict)
    for scenario, records in records_by_scenario.items():
        for record in records:
            identifier = record["binding"]
            if identifier not in by_id:
                raise ValueError("Observed SUM lacks an unambiguous Vensim binding")
            plan = layout_plan(record)
            if plan not in plans[identifier]:
                plans[identifier].append(plan)
            observed[identifier].setdefault(scenario, []).append(record)
    entries, deferred = [], []
    for identifier, variants in sorted(plans.items()):
        binding = by_id[identifier]
        if len(variants) != 1:
            if set(observed[identifier]) != set(cases):
                raise ValueError("Calendar-dependent SUM was not observed in every required scenario")
            entries.append({**binding, "plan": calendar_plan(observed[identifier])})
            continue
        entries.append({**binding, "plan": variants[0]})
    return {"entries": entries, "deferred": deferred, "rejected_components": catalogs[0]["rejected"],
            "scenarios": cases, "evidence": evidence,
            "contract": "Observed invariant layouts use NumPy block reduction; time-varying layouts require a unique first-time/remaining-annual-grid contract in every scenario"}


def configure(policy):
    from pysd.builders.julia.julia_model_builder import JuliaSectionBuilder
    grouped = defaultdict(dict)
    for entry in policy.get("entries", []):
        key = (entry["vensim_component_index"], entry["vensim_ast_path"])
        component = entry["component"]
        if key in grouped[component]:
            raise ValueError(f"Duplicate reduction policy: {component}/{key}")
        grouped[component][key] = entry
    JuliaSectionBuilder._seneca_reduction_policy = dict(grouped)


def context(section, element):
    """Bind before nested-state lowering copies AST objects; never use call count."""
    from dataclasses import fields, is_dataclass
    from pysd.translators.structures.abstract_expressions import CallStructure
    configured = getattr(section, "_seneca_reduction_policy", {}).get(element.name, {})
    found, used = {}, set()
    def visit(node, component, path):
        if isinstance(node, CallStructure) and node.function.reference.upper() == "SUM":
            key = (component, path)
            if key in configured:
                entry = configured[key]
                fingerprint = repr(node)
                if fingerprint in found and found[fingerprint][0]["plan"] != entry["plan"]:
                    raise ValueError(f"Identical SUM AST requires conflicting layouts: {element.name}")
                found.setdefault(fingerprint, []).append(entry)
                used.add(key)
        if is_dataclass(node):
            for field in fields(node):
                visit(getattr(node, field.name), component, path + "." + field.name)
        elif isinstance(node, (list, tuple)):
            for index, child in enumerate(node):
                visit(child, component, path + f"[{index}]")
    for index, component in enumerate(element.components):
        visit(component.ast, index, "ast")
    if used != set(configured):
        raise ValueError(f"Candidate AST does not match verified SUM sites: {element.name}: {set(configured)-used}")
    return found
