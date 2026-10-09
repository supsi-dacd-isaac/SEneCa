"""Produce a report on success, failure, or an intentionally partial pilot."""
from __future__ import annotations

from .common import read, dump, experiment_hashes


def write_report(directory):
    manifest = read(directory / "manifest.json")
    statuses = {p.stem: read(p) for p in sorted((directory / "status").glob("*.json"))}
    fixtures = read(directory / "fixtures.json") if (directory / "fixtures.json").exists() else {}
    validation = read(directory / "validation.json") if (directory / "validation.json").exists() else {}
    checks = {p.stem: read(p) for p in sorted((directory / "checks").glob("*.json"))}
    references = {s: checks[f"reference_{s}"] for s in manifest["scenarios"] if f"reference_{s}" in checks}
    blockers = []
    warning_count = 0
    for path in sorted((directory / "julia").glob("*/translation-warnings.json")):
        messages = read(path)
        warning_count += len(messages)
        blockers.extend({"scenario": path.parent.name, **m} for m in messages
                        if m.get("classification") != "existing_python_input_interpolation")
    divergent = [{"scenario": key.removeprefix("julia_"), **row}
                 for key, result in checks.items() if key.startswith("julia_")
                 for row in result["rows"] if not row["pass"]]
    divergent.sort(key=lambda r: (r.get("year", -1), r["scenario"], r["variable"]))
    # A temporal/dependency diagnosis of the captured variables; never infer that
    # the earliest exported difference is necessarily the root cause.
    failed_names = {r["variable"] for r in divergent}
    names = {v["python_name"]: k for k, v in manifest["variables"].items()}
    for row in divergent:
        deps = manifest["variables"].get(row["variable"], {}).get("depends_on", {})
        row["also_divergent_dependencies"] = [names[k] for k in deps if names.get(k) in failed_names]
    packing = {key.removeprefix("packing_"): value for key, value in checks.items() if key.startswith("packing_")}
    current = experiment_hashes()
    accepted = (validation.get("pass", False) and validation.get("full_suite", False)
                and validation.get("experiment") == current and not blockers)
    if accepted:
        from .execution import check_benchmark_gate
        try:
            check_benchmark_gate(directory)
        except (ValueError, RuntimeError, FileNotFoundError):
            accepted = False
    summary = {
        "accepted": accepted, "full_suite_size": len(manifest["scenarios"]),
        "reference_scenarios": {s: r["pass"] for s, r in references.items()},
        "reference_determinism": checks.get("reference_determinism", {}).get("pass"),
        "fixtures_pass": fixtures.get("pass"), "fixtures_current": fixtures.get("experiment") == current,
        "packing": packing, "blocking_warnings": blockers, "warnings_recorded": warning_count,
        "divergences": divergent, "statuses": statuses, "pins": manifest["pins"],
        "experiment": current,
    }
    dump(directory / "summary.json", summary)
    lines = ["# Riproducibilità locale SURE Python–Julia", "",
             "**Esito: " + ("suite completa accettata.**" if accepted else "equivalenza completa non dimostrata; benchmark non autorizzato dai controlli.**"), "",
             f"Branch di lavoro: `codex/julia-reproducibility`; commit di partenza `{manifest['pins']['base_commit']}`.",
             f"SURE v3, release `{manifest['pins']['data_release']}`, Python/PySD {manifest['pins']['pysd_reference']}, Julia {manifest['pins']['julia']}; Float64, un thread, Euler annuale 2011–2050.", "",
             "## Copertura effettiva", "",
             f"- Suite congelata: {len(manifest['scenarios'])} scenari distinti, con parametri e alias in `manifest.json`.",
             f"- Riferimenti Python completati: {len(references)}/{len(manifest['scenarios'])} ({', '.join(references) or 'nessuno'}).",
             f"- Output webapp: {len(manifest['outputs'])}; variabili diagnostiche: {len(manifest['diagnostics'])}; componenti raggiungibili a sei dimensioni: {len(manifest['six_dimensional'])}.",
             f"- Test mirati Julia: {fixtures.get('pass', 'non eseguiti')}; corrispondenza al codice corrente: {summary['fixtures_current']}.",
             f"- Ripetibilità Python, due processi nuovi e base → high → base: {summary['reference_determinism']}.", "",
             "| Scenario Python | Webapp vs diagnostica | Errore assoluto massimo | Celle 6D ricostruite esattamente |",
             "|---|---|---:|---:|"]
    for case, result in references.items():
        maximum = max((r.get("max_abs", 0.) for r in result["rows"]), default=0.)
        lines.append(f"| {case} | {'PASS' if result['pass'] else 'FAIL'} | {maximum:.6g} | {packing.get(case, {}).get('cells_checked', 0):,} |")
    lines += ["", "La mappa esplicita e reversibile conserva tutte le 5.280 celle nella forma 120 × 11 × 4. Non è una riduzione degli stati e non dimostra una simulazione completa con equazioni riscritte a tre dimensioni.",
              "I test sintetici controllano anche selezioni, esclusioni, somme, normalizzazioni e trasferimenti fra categorie.", "",
              "## Blocchi e divergenze", "",
              f"Avvisi della traduzione registrati: {warning_count}; bloccanti: {len(blockers)}."]
    lines += [f"- `{b['scenario']}`: {b['message']}" for b in blockers]
    compared = [key for key in checks if key.startswith("julia_")]
    if not divergent and compared:
        lines.append(f"Nessuna divergenza numerica nei {len(compared)} scenari Julia confrontati. L'accettazione richiede comunque l'intera suite e i controlli di ripetibilità.")
    elif not divergent:
        lines.append("Nessuna divergenza numerica Julia disponibile: se la traduzione è bloccata, la simulazione completa non viene eseguita. L'assenza di confronti non costituisce un PASS.")
    else:
        lines += ["Prime divergenze fra le variabili osservate (dettaglio e dipendenze in `summary.json`):"]
        lines += [f"- `{r['scenario']}`, `{r['variable']}`, anno {r.get('year', 'schema')}: {r.get('reason', 'tolleranza superata')}." for r in divergent[:20]]
    ignored = manifest.get("ignored_ui_levers", [])
    if not ignored:
        path = directory / "reference/app/base.inputs.json"
        ignored = read(path).get("ignored_by_webapp", []) if path.exists() else []
    lines += ["", "## Riferimento e riproduzione", "",
              "Leve già ignorate dalla webapp v3: " + (", ".join(f"`{n}`" for n in ignored) or "nessuna rilevata") + ". Il runner registra questa condizione e conserva il comportamento del riferimento.",
              "Checksum di sorgenti, CSV, costanti, ambiente e scenari: `manifest.json`; parametri effettivi: `reference/*/*.params.json`; avvisi e log sono conservati accanto agli artefatti.",
              "Le interpolazioni di dati mancanti sono ammesse solo quando l'avviso corrisponde per variabile, file e cella a quello del riferimento Python. Ogni altro avviso di traduzione blocca il confronto.",
              "Le soglie restano 1e−12 × max(1, S) + 1e−9 × |Python|, con S per serie elementare. Etichette, anni e valori discreti richiedono corrispondenza esatta.",
              "", "## Prestazioni", "",
              "I tempi diagnostici salvati durante la preparazione non sono benchmark comparativi. I risultati prestazionali sono validi solo dopo l'accettazione dell'intera suite.",
              "Il runner separa i costi osservabili e conserva i tempi grezzi; le misure a caldo riutilizzano lo stesso scenario compilato. La latenza di un futuro servizio persistente resta fuori da questo esperimento.", ""]
    (directory / "REPORT.md").write_text("\n".join(lines))
    return summary
