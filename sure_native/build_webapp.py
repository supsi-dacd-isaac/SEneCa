"""Build della traduzione nativa per la webapp (stesso contratto di sure_julia/build.py).

Copia nel build il modulo Julia generato da SURE.mdl, gli input (cartelle di serie
estratte dai .vdfx) e il file di calibrazione, scrive export.json con le uscite del
catalogo della webapp e build.json con le impronte. sure_julia/runtime.py riconosce
il build dal campo "worker": "native" e avvia sure_native/webapp_worker.jl.

Uso: python -m sure_native.build_webapp RUN_DIR GENERATED.jl [TARGET]
RUN_DIR contiene SURE.mdl, calibration.out e inputs/ (quelli usati per la validazione).
"""
import ast
import shutil
import subprocess
import sys
from pathlib import Path

from sure_julia.catalog import outputs
from sure_julia.common import ROOT, MODEL_PY, NATIVE_REVISION, digest, dump, read

HERE = Path(__file__).resolve().parent


def old_subscripts():
    """Dimensioni della traduzione PySD precedente, per segnalare etichette cambiate."""
    for node in ast.parse(MODEL_PY.read_text()).body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "_subscript_dict" for t in node.targets):
            return ast.literal_eval(node.value)
    return {}


def build(run_dir, generated, target):
    run_dir, generated, target = Path(run_dir).resolve(), Path(generated).resolve(), Path(target).resolve()
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    dump(target / "build.json", {"complete": False})
    names = outputs()
    (target / "outputs.txt").write_text("\n".join(names) + "\n", encoding="utf-8")
    subprocess.run(["julia", "--startup-file=no", f"--project={HERE}", str(HERE / "scripts/webapp_export.jl"),
                    str(run_dir / "SURE.mdl"), str(target / "outputs.txt"), str(target / "export.json")], check=True)
    (target / "outputs.txt").unlink()
    shutil.copy2(generated, target / "SUREGenerated.jl")
    shutil.copy2(run_dir / "calibration.out", target / "calibration.out")
    shutil.copytree(run_dir / "inputs", target / "inputs")
    export = read(target / "export.json")
    old = old_subscripts()
    changed = sorted({d for item in export for d in item["dims"] if d in old and old[d] != item["coords"][d]})
    new = sorted({d for item in export for d in item["dims"] if d not in old})
    if changed or new:
        print(f"ATTENZIONE dimensioni diverse dalla traduzione PySD: cambiate {changed}, nuove {new}")
    artifacts = {str(p.relative_to(target)).replace("\\", "/"): digest(p)
                 for p in sorted(target.rglob("*")) if p.is_file() and p.name != "build.json"}
    dump(target / "build.json", {
        "complete": True, "worker": "native", "model_revision": NATIVE_REVISION,
        "model": "SUREGenerated.jl", "inputs": "inputs", "calibration": "calibration.out",
        "sources": {"SURE.mdl": digest(run_dir / "SURE.mdl"), "calibration.out": digest(run_dir / "calibration.out")},
        "implementation": {str(p.relative_to(ROOT)).replace("\\", "/"): digest(p) for p in sorted(HERE.rglob("*"))
                           if p.is_file() and p.suffix in {".py", ".jl", ".toml"} and target not in p.parents},
        "artifacts": artifacts, "outputs": len(export), "float": "Float64", "years": list(range(2011, 2051)),
        "dimension_changes": {"changed": changed, "new": new}})
    print(f"build nativo: {len(export)} uscite in {target}")


if __name__ == "__main__":
    build(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else ROOT / "sure_native/generated")
