"""Pacchetto per lo staging su Elettra (senza passare da GitHub).

Contiene i file versionati del commit corrente (la worktree deve essere pulita),
il build nativo sure_native/generated, gli scenari generati dal batch
(RELEASE_DIR/precomputed e RELEASE_DIR/provenance) e i file dati delle pagine
(Vensim/*.vdfx; SURE.vpmx non serve alla webapp) presi dalla copia locale installata.

Uso: python deploy/make_staging_bundle.py RELEASE_DIR [OUT.tar.gz]
RELEASE_DIR è la cartella release/ del batch (sure_julia.batch).
"""
import io
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.data_release import DATA_PATHS, PROVENANCE_PATHS  # noqa: E402


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True, encoding="utf-8")


def main(release, out=None):
    release = Path(release).resolve()
    if git("status", "--porcelain", "--untracked-files=no").strip():
        raise SystemExit("La worktree ha modifiche non registrate: fai prima un commit")
    commit = git("rev-parse", "--short", "HEAD").strip()
    out = Path(out or ROOT / "dist" / f"seneca-staging-{commit}.tar.gz")
    out.parent.mkdir(parents=True, exist_ok=True)
    prefix = "seneca-staging"
    count = 0
    with tarfile.open(out, "w:gz") as tar:
        def add(src, arc):
            nonlocal count
            tar.add(src, arcname=f"{prefix}/{arc}", recursive=False)
            count += 1
        # file del commit come sono nel repository (fine riga LF), non la copia Windows
        raw = subprocess.run(["git", "-c", "core.autocrlf=false", "archive", "--format=tar", "HEAD"],
                             cwd=ROOT, check=True, capture_output=True).stdout
        tracked = set()
        with tarfile.open(fileobj=io.BytesIO(raw)) as src:
            for m in src.getmembers():
                if m.isfile():
                    tracked.add(m.name)
                    data = src.extractfile(m)
                    m.name = f"{prefix}/{m.name}"
                    tar.addfile(m, data)
                    count += 1
        # build nativo: dal commit se versionato, altrimenti dalla copia locale
        for p in sorted((ROOT / "sure_native/generated").rglob("*")):
            if p.is_file() and p.relative_to(ROOT).as_posix() not in tracked:
                add(p, p.relative_to(ROOT).as_posix())
        for p in [d for d in DATA_PATHS if not d.endswith(".vpmx")]:   # .vpmx non usato dalla webapp
            src = release / p if p.startswith("precomputed/") else ROOT / p
            if not src.is_file():
                raise SystemExit(f"File mancante: {src}")
            add(src, p)
        for p in PROVENANCE_PATHS:
            add(release / p, p)
        (ROOT / "dist").mkdir(exist_ok=True)
        stamp = ROOT / "dist" / "STAGING_COMMIT"
        stamp.write_text(commit + "\n", encoding="utf-8")
        add(stamp, "STAGING_COMMIT")
    print(f"{out} ({count} file, {out.stat().st_size / 1e6:.0f} MB), commit {commit}")


if __name__ == "__main__":
    main(*sys.argv[1:3])
