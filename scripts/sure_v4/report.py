"""Compact, reproducible conclusions; magnitude metrics never replace acceptance."""
from pathlib import Path
import sys

import numpy as np

from scripts.julia_repro.common import digest, dump, read
from scripts.julia_repro.results import load_snapshot


def generate(directory):
    manifest = read(directory / "manifest.json")
    validation = read(directory / "validation.json")
    cases = []
    for case, result in validation["cases"].items():
        rows = result["vensim_reconstructed_vs_python"]["rows"]
        selected = {r["variable"]: r for r in rows}
        cases.append({"id": case, "python_julia_pass": result["python_vs_julia"]["pass"],
                      "native_variables_pass": sum(r["pass"] for r in rows),
                      "native_numerical_failure_cells": sum(r["failures"] for r in rows),
                      "native_beyond_one_percent_cells": sum(r["beyond_one_percent"] for r in rows),
                      "phs_max_error_fraction_peak": selected["PHS hourly demand"]["max_fraction_variable_scale"],
                      "dispatch_max_error_fraction_peak": selected["Electricity dispatched"]["max_fraction_variable_scale"],
                      "phs_maximum": selected["PHS hourly demand"]["maximum_difference"],
                      "dispatch_maximum": selected["Electricity dispatched"]["maximum_difference"]})
    rows = [r for case in validation["cases"].values() for r in case["python_vs_julia"]["rows"]]
    pyj = {"variables_per_scenario": len(validation["cases"]["01_base"]["python_vs_julia"]["rows"]),
           "cells_compared": sum(r["elements"] for r in rows),
           "failure_cells": sum(r["failures"] for r in rows),
           "max_tolerance_fraction": max(r.get("max_tolerance_fraction", 0) for r in rows),
           "six_dimensional_outputs": [n for n in manifest["diagnostics"] if len(manifest["variables"][n].get("subscripts", [])) == 6]}
    native_meta, a = load_snapshot(directory / "native/reconstructed/01_base")
    py_meta, b = load_snapshot(directory / "reference/diagnostic/01_base")
    coordinate = "M5,H3"
    example = {"case": "01_base", "year": 2011, "coordinate": coordinate, "suppliers": {}}
    for name in ("Hourly available supply by Supplier", "Electricity dispatched"):
        example["suppliers"][name] = {c.rsplit(",", 1)[1].rstrip("]"): {"vensim": float(a[name][0, i]), "python": float(b[name][0, i])}
            for i, c in enumerate(native_meta["variables"][name]["columns"]) if f"[{coordinate}," in c}
    for name in ("PHS hourly demand", "Hourly demand and PHS"):
        index = py_meta["variables"][name]["columns"].index(f"{name}[{coordinate}]")
        example[name] = {"python": float(b[name][0, index]), "vensim": float(a[name][0, index]) if name in a else None}
    example["interpretation"] = ("A material Import dispatch difference is already present in 2011. Available supplies and pumping demand are nearly equal here. "
        "Hourly grid demand and supplier priority profiles are not native outputs, so this does not prove the allocation algorithm is the cause.")
    summary = {"revision": manifest["revision"], "model_sha256": digest(directory / "model/SURE_v4.jl"),
               "validation_sha256": digest(directory / "validation.json"), "alignment_pass": validation["alignment_pass"],
               "native_equivalence_certified": validation["native_equivalence_certified"], "python_julia": pyj,
               "reproducibility": {k: {"pass": v["pass"], "bitwise_identical": v["bitwise_identical"]} for k, v in validation["reproducibility"].items()},
               "compiled_module_reused": validation["compiled_module_reused"], "delay_update_audit_pass": validation["delay_update_audit_pass"],
               "allocation_fixtures_pass": validation["allocation_fixtures_pass"], "warnings": validation["warnings"],
               "native_stored_cells": 8480480, "native_reconstructed_cells": 112320,
               "native_model_sha256": manifest["native_metadata"]["model_sha256"],
               "native_unset_levers": manifest["native_metadata"]["unset_levers"],
               "early_material_divergence_example": example, "cases": cases,
               "next_native_exports": ["Hourly electricity demand", "Hourly electricity grid demand", "Hourly demand and PHS",
                  "Priority vector by supplier", "Marginal cost by supplier", "Hourly imported electricity",
                  "PHS annual demand", "Seasonal PHS hourly demand", "Hour factor PHS consumption"]}
    dump(directory / "summary.json", summary)
    status = lambda value: "PASS" if value else "FAIL"
    import_example = example["suppliers"]["Electricity dispatched"]["Import"]
    lines = ["# Allineamento SURE v4: Python, Julia e Vensim", "",
        f"Sorgente main fissata a `{manifest['revision']}`. Tutte le elaborazioni sono isolate da webapp, modello v3 e ambiente corrente.", "",
        "## Esito", "",
        f"**Julia–PySD v4: {status(validation['alignment_pass'])}** su 10 scenari, {pyj['variables_per_scenario']} variabili e {pyj['cells_compared']:,} valori, senza campionamento. Sono inclusi i 52 output webapp, i 60 output nativi e i diagnostici multidimensionali già verificati nella v3.",
        "**Equivalenza con Vensim: non dimostrata.** Gli stessi scarti nativi sono presenti con PySD v4 e con Julia. Alcuni sono consistenti e non giustificano un aumento delle tolleranze.", "",
        "## Allineamento e ripetibilità", "",
        "- Rigenerazione dal MDL v4; cinque accumulatori aggiuntivi per i nuovi diagnostici.",
        "- Rimossa la sostituzione specifica delle normalizzazioni HS della v3; mantenute le equazioni v4.",
        "- Portato il wrapper v4 ALLOCATE AVAILABLE: algoritmo per priorità quando tutti i profili rettangolari hanno la stessa larghezza, fallback precedente per larghezze diverse. Richieste negative troncate come in PySD v4.",
        f"- 104 casi mirati di allocazione, 314 verifiche: {status(validation['allocation_fixtures_pass'])}; conservazione dell’energia: {status(all(r['python_energy']['pass'] and r['julia_energy']['pass'] for r in validation['cases'].values()))}.",
        "- Julia 1.10.12, PySD Python 3.14.3, Float64, un thread, Euler fisso, passo annuale, tutti gli anni 2011–2050. Dipendenze Julia nel manifest preesistente.",
        "- Soglia Python–Julia invariata: `1e-10 × max(1, S) + 1e-8 × abs(Python)`, con S massimo della singola serie temporale. Etichette, anni e valori discreti esatti.",
        f"- Il massimo scarto usa solo {pyj['max_tolerance_fraction']:.8g} della tolleranza consentita.",
        f"- Identità dei 52 output fra percorso diagnostico e webapp, in tutti i dieci scenari: {status(all(r['app_vs_diagnostic']['pass'] for r in validation['cases'].values()))}.",
        f"- Identità bit per bit del base dopo gli altri scenari e in un secondo processo, per entrambi i motori: {status(all(r['pass'] for r in validation['reproducibility'].values()))}.",
        f"- Un solo modulo e tipo dei parametri; zero nuova compilazione dopo il primo scenario: {status(validation['compiled_module_reused'])}. Ogni run ricrea stato iniziale e ritardi.",
        f"- Audit dei ritardi con strumentazione a risultati invariati e conferma della lettura dello SMOOTH già aggiornato per il ritardo delle importazioni: {status(validation['delay_update_audit_pass'])}.",
        f"- Tutti gli avvisi sono conservati e classificati; esclusione di costrutti ignorati o non supportati: {status(validation['warnings']['pass'])}.", "",
        "## Scarti Vensim", "",
        "La tabella riporta il massimo errore assoluto diviso per il massimo assoluto della variabile Vensim nello scenario. Non è l’errore percentuale puntuale, né un criterio di accettazione. Le celle orarie non sono aggregate per determinare l’esito.", "",
        "| Scenario | Python–Julia | PHS: errore / picco | Dispatch: errore / picco |",
        "|---|---:|---:|---:|"]
    lines += [f"| {r['id']} | {status(r['python_julia_pass'])} | {100*r['phs_max_error_fraction_peak']:.2f}% | {100*r['dispatch_max_error_fraction_peak']:.2f}% |" for r in cases]
    lines += ["", "Il confronto nativo considera esplicitamente la quantizzazione Float32 dell’export (mezzo ULP), oltre alla tolleranza numerica. Questa correzione non elimina gli scarti della tabella.", "",
        f"Già nel 2011, M5/H3, l’elettricità dispatchata dal fornitore Import vale {import_example['vensim']:.10f} in Vensim e {import_example['python']:.10f} in PySD. Nella stessa cella disponibilità dei fornitori e domanda di pompaggio sono quasi uguali. Mancano però la domanda oraria di rete e i profili di priorità nativi: non è ancora possibile attribuire univocamente lo scarto all’allocatore anziché ai suoi input.", "",
        "## Archivio e limiti di provenienza", "",
        "L’archivio contiene 8.480.480 valori nativi finiti. Per `Hourly exported electricity[Month,Hour,Import]` le 288 serie di ciascun run hanno solo il 2011. Il confronto grezzo le segnala incomplete. Un secondo confronto aggiunge separatamente 112.320 zeri complessivi secondo l’equazione MDL costante; questi zeri non sono misure native indipendenti. Nessun originale è modificato.",
        "Tutti i 20 parametri della webapp sono registrati. Restano impliciti nel VPMX i default di ICE ban year, Deflussi minimi LPAc e Cambiamento climatico Hydro. Nella sorgente Python sono 2050, 1 e 1; non costituiscono prova del contenuto del VPMX.",
        f"Il VPMX usato per i run ha SHA-256 `{summary['native_model_sha256']}` e non coincide con quello locale della release data-v1.0.0. I risultati si possono confrontare senza DLL; per riprodurre e diagnosticare il run nativo serve lo stesso VPMX e un ambiente Vensim compatibile.", "",
        "## Diagnosi nativa successiva", "",
        "Usare lo stesso VPMX dei nuovi run, registrare esplicitamente anche i tre default e le impostazioni del motore, ed esportare gli intermedi seguenti nello scenario base e in 09_hydro_on:", ""]
    lines += [f"- {n}" for n in summary["next_native_exports"]]
    lines += ["", "I tempi raccolti durante questi controlli sono diagnostici: non costituiscono un nuovo benchmark controllato né una misura di latenza del servizio web.", "",
        "Riproduzione: vedere `benchmarks/sure-v4/README.md`. Manifest, coordinate, parametri applicati, warning, risultati completi e checksum sono nella directory del run. `summary.json` è il riepilogo compatto; `validation.json` conserva tutti gli esiti per variabile.", ""]
    (directory / "REPORT.md").write_text("\n".join(lines))
    return summary


if __name__ == "__main__":
    generate(Path(sys.argv[1]).resolve())
