"""Produce a report on success, failure, or an intentionally partial pilot."""
from __future__ import annotations

from .common import CONFIG, read, dump, digest, experiment_hashes


def write_report(directory):
    manifest = read(directory / "manifest.json")
    statuses = {p.stem: read(p) for p in sorted((directory / "status").glob("*.json"))}
    fixtures = read(directory / "fixtures.json") if (directory / "fixtures.json").exists() else {}
    validation = read(directory / "validation.json") if (directory / "validation.json").exists() else {}
    checks = {p.stem: read(p) for p in sorted((directory / "checks").glob("*.json"))
              if not p.name.endswith(".provenance.json")}
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
                 for row in result.get("rows", []) if not row["pass"]]
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
    benchmark = read(directory / "benchmark.json") if (directory / "benchmark.json").exists() else None
    benchmark_current = bool(benchmark and benchmark.get("pass") and
        benchmark.get("experiment") == current and (directory / "validation.json").exists() and
        benchmark.get("validation_sha256") == digest(directory / "validation.json"))
    reference_suite = read(directory / "reference-suite.json") if (directory / "reference-suite.json").exists() else {}
    acceptance_policy = read(CONFIG / "acceptance.json")
    strict_cases = {key.removeprefix("julia_"): result.get("strict", result).get("pass", False)
                    for key, result in checks.items() if key.startswith("julia_")}
    stress_failures = fixtures.get("allocation_stress", {}).get("python", {}).get("conservation_failure_count")
    summary = {
        "accepted": accepted, "full_suite_size": len(manifest["scenarios"]),
        "reference_scenarios": {s: r["pass"] for s, r in references.items()},
        "reference_determinism": checks.get("reference_determinism", {}).get("pass"),
        "fixtures_pass": fixtures.get("pass"), "fixtures_current": fixtures.get("experiment") == current,
        "packing": packing, "blocking_warnings": blockers, "warnings_recorded": warning_count,
        "divergences": divergent, "statuses": statuses, "pins": manifest["pins"],
        "experiment": current, "reference_failures": [*reference_suite.get("failures", []),
            *({"case": key.removeprefix("conservation_reference_"), "stage": "conservation", **value}
              for key, value in checks.items() if key.startswith("conservation_reference_") and not value["pass"])],
        "benchmark": benchmark if accepted and benchmark_current else None,
        "benchmark_current": benchmark_current,
        "acceptance_policy": acceptance_policy, "original_tolerance_cases": strict_cases,
        "reference_stress_conservation_pass": None if stress_failures is None else stress_failures == 0,
    }
    dump(directory / "summary.json", summary)
    lines = ["# Riproducibilità locale SURE Python–Julia", "",
             "**Esito: " + ("equivalenza numerica accettata per tutti gli scenari SURE.**" if accepted else "equivalenza completa non dimostrata; benchmark non autorizzato dai controlli.**"), "",
             f"Branch di lavoro: `codex/julia-reproducibility`; commit di partenza `{manifest['pins']['base_commit']}`.",
             f"SURE v3, release `{manifest['pins']['data_release']}`, Python/PySD {manifest['pins']['pysd_reference']}, Julia {manifest['pins']['julia']}; Float64, un thread, Euler annuale 2011–2050. Il processo Python usa `PYTHONHASHSEED=0`.", "",
             "## Copertura effettiva", "",
             f"- Suite congelata: {len(manifest['scenarios'])} scenari distinti, con parametri e alias in `manifest.json`.",
             f"- Riferimenti Python completati: {len(references)}/{len(manifest['scenarios'])} ({', '.join(references) or 'nessuno'}).",
             f"- Output webapp: {len(manifest['outputs'])}; variabili diagnostiche: {len(manifest['diagnostics'])}; componenti raggiungibili a sei dimensioni: {len(manifest['six_dimensional'])}.",
             f"- Test mirati Julia: {fixtures.get('pass', 'non eseguiti')}; corrispondenza al codice corrente: {summary['fixtures_current']}.",
             f"- Ripetibilità Python, due processi nuovi e base → high → base: {summary['reference_determinism']}.", "",
             "| Scenario Python | Webapp vs diagnostica | Errore assoluto massimo | Celle 6D ricostruite esattamente |",
             "|---|---|---:|---:|"]
    for case, result in references.items():
        maximum = max((r.get("max_abs", 0.) for r in result.get("rows", [])), default=0.)
        lines.append(f"| {case} | {'PASS' if result['pass'] else 'FAIL'} | {maximum:.6g} | {packing.get(case, {}).get('cells_checked', 0):,} |")
    for case, result in references.items():
        if not result["pass"] and result.get("reason"):
            lines.append(f"\nRiferimento `{case}`: {result['reason']}\n")
    lines += ["", "| Gruppo mirato | Esito | Casi o lettori |", "|---|---|---:|"]
    for group in ("julia", "runner", "external", "stateful", "semantics", "sure_inputs", "indexing", "allocation_stress", "reductions", "reduction_blocks", "hotpaths", "numpy_math", "lookups"):
        item = fixtures.get(group, {})
        if item:
            count = item.get("cases", item.get("variables", item.get("python", {}).get("cases", len(item.get("results", [])))))
            lines.append(f"| {group} | {'PASS' if item.get('pass') else 'FAIL'} | {count or '—'} |")
    allocation_audit = fixtures.get("allocation_stress", {}).get("python", {})
    if allocation_audit.get("conservation_failure_count"):
        lines += ["", f"Audit sintetico esteso dell'allocazione: {allocation_audit['conservation_failure_count']} casi estremi mostrano un residuo di conservazione del riferimento Python oltre la soglia. "
                  "Questi residui vengono registrati separatamente e riprodotti, senza eliminare casi o modificare il riferimento. Il PASS del gruppo indica equivalenza numerica a Python; non certifica la conservazione fisica in quegli estremi."]
    lines += ["", "La mappa esplicita e reversibile conserva tutte le 5.280 celle nella forma 120 × 11 × 4. Non è una riduzione degli stati e non dimostra una simulazione completa con equazioni riscritte a tre dimensioni.",
              "I test sintetici controllano anche selezioni, esclusioni, somme, normalizzazioni e trasferimenti fra categorie.", "",
              "## Blocchi e divergenze", "",
              f"Avvisi della traduzione registrati: {warning_count}; bloccanti: {len(blockers)}."]
    lines += [f"- `{b['scenario']}`: {b['message']}" for b in blockers]
    compared = [key for key in checks if key.startswith("julia_")]
    if compared:
        lines += ["", "| Scenario Julia | Esito | Soglia originale | Valori confrontati | Errore assoluto massimo |",
                  "|---|---|---|---:|---:|"]
        for key in compared:
            result = checks[key]
            rows = result.get("rows", [])
            lines.append(f"| {key.removeprefix('julia_')} | {'PASS' if result['pass'] else 'FAIL'} | "
                         f"{'PASS' if strict_cases[key.removeprefix('julia_')] else 'FAIL'} | "
                         f"{sum(r.get('elements', 0) for r in rows):,} | {max((r.get('max_abs', 0.) for r in rows), default=0.):.6g} |")
    energy = {key: value for key, value in checks.items() if key.startswith("conservation_")}
    if energy:
        lines += ["", f"Conservazione dell'allocazione nelle simulazioni SURE: {sum(r['pass'] for r in energy.values())}/{len(energy)} controlli superati. Ogni controllo comprende tutti gli anni, mesi e ore; verifica anche allocazioni non negative e non superiori alle richieste troncate. Un fallimento Python o Julia impedisce l'accettazione."]
        lines += [f"- `{key}`: {value.get('first_failure', value.get('reason'))}." for key, value in energy.items() if not value["pass"]]
    reductions = {key: value for key, value in checks.items() if key.startswith("reduction_samples_")}
    if reductions:
        lines += ["", f"Riduzioni sugli input reali registrati: {sum(r['pass'] for r in reductions.values())}/{len(reductions)} scenari superati, {sum(r.get('cells', 0) for r in reductions.values()):,} risultati confrontati bit per bit. I layout sono legati alla posizione esatta delle espressioni Python e Vensim e agli output del riferimento."]
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
              f"Su autorizzazione dell'utente del 9 ottobre 2026, la soglia di accettazione è {acceptance_policy['atol_scale']:g} × max(1, S) + {acceptance_policy['rtol']:g} × |Python|, con S per serie elementare. La soglia originale 1e−12 × max(1, S) + 1e−9 × |Python| resta riportata come diagnostica. Etichette, anni, valori discreti e ripetibilità richiedono corrispondenza esatta. I controlli di conservazione SURE mantengono la soglia originale.",
              "La potatura PySD ordina gli aggiornamenti attraverso un set. L'audit versionato registra l'ordine effettivo del riferimento e verifica gli output prima di applicarlo alla traduzione. In SURE, il ritardo di Hourly imported electricity legge lo SMOOTH già aggiornato; gli altri ritardi conservano le letture precedenti. Le copie dei ritardi avvengono dopo Euler, prima del salvataggio annuale.",
              "L'esperimento riproduce il riferimento con hash seed 0: non dimostra indipendenza della webapp corrente dall'ordine degli aggiornamenti. Le funzioni EXP e POWER usano la libreria matematica del riferimento macOS arm64, con versioni del sistema e della libreria controllate prima dell'esecuzione; non è ancora una certificazione per altre piattaforme.",
              "", "## Prestazioni", "",
              "I tempi diagnostici salvati durante la preparazione non sono benchmark comparativi. I risultati prestazionali sono validi solo dopo l'accettazione dell'intera suite.",
              "Il runner separa i costi osservabili e conserva i tempi grezzi; le misure a caldo riutilizzano lo stesso scenario compilato. La latenza di un futuro servizio persistente resta fuori da questo esperimento.", ""]
    if accepted and benchmark_current:
        lines += ["Il confronto principale è la simulazione completa con cattura dei risultati. PySD calcola ausiliari durante la cattura e ne riutilizza la cache durante Euler: i tempi delle singole fasi non misurano da soli il guadagno dell'intera simulazione.", "",
                  "| Motore | Scenario | Esecuzione | Simulazione e risultati (s) | Serializzazione (s) | Caricamento (s) | Inizializzazione (s) | Integrazione (s) | Estrazione (s) | Picco memoria (MiB) |",
                  "|---|---|---|---:|---:|---:|---:|---:|---:|---:|"]
        for group in benchmark["summary"]:
            metrics = group["metrics"]
            def median(*names):
                return next((metrics[n]["median"] for n in names if n in metrics), 0.)
            lines.append(f"| {group['engine']} | {group['scenario']} | {group['kind']} | "
                         f"{median('simulation_and_capture_seconds'):.4f} | {median('serialization_seconds'):.4f} | {median('load_seconds'):.4f} | "
                         f"{median('initialize_seconds', 'initialization_and_configuration_seconds'):.4f} | "
                         f"{median('solve_seconds', 'integration_seconds'):.4f} | {median('extraction_seconds'):.4f} | "
                         f"{metrics.get('max_rss_bytes', {}).get('max', 0)/1024**2:.1f} |")
        lines += ["", "Tempi singoli, mediana, minimo/massimo e contatori di compilazione sono in `benchmark.json`. Il caricamento Julia include la prima costruzione di u0, misurata anche come sottofase separata; i contatori JIT sono inclusi nei tempi di parete e non si sommano nuovamente.",
                  "La memoria è il massimo cumulativo del processo: nelle ripetizioni a caldo comprende anche il riscaldamento e la compilazione precedente.",
                  "I processi nuovi caricano un modello già tradotto. Il timer di preparazione sotto misura parsing, applicazione dei parametri e generazione; esclude la copia preliminare dei file e gli audit del riferimento.", "",
                  "| Scenario | Preparazione sorgente Julia (s) |", "|---|---:|"]
        for case in ("base", "mid", "high"):
            path = directory / "julia" / case / "translation.json"
            if path.exists():
                lines.append(f"| {case} | {read(path)['seconds']:.4f} |")
        lines.append("")
    (directory / "REPORT.md").write_text("\n".join(lines))
    return summary
