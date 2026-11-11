"""Pacchetto per lo staging su Elettra (senza passare da GitHub).

Contiene i file versionati del commit corrente (la worktree deve essere pulita),
il build nativo sure_native/generated, gli scenari generati dal batch
(RELEASE_DIR/precomputed e RELEASE_DIR/provenance) e i file dati delle pagine
(Vensim/*.vdfx; SURE.vpmx non serve alla webapp) presi dalla copia locale installata.

Uso: python deploy/make_staging_bundle.py RELEASE_DIR [OUT.tar.gz]
RELEASE_DIR è la cartella release/ del batch (sure_julia.batch).
"""
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
    tracked = [p for p in git("ls-files", "-z").split("\0") if p]
    count = 0
    with tarfile.open(out, "w:gz") as tar:
        def add(src, arc):
            nonlocal count
            tar.add(src, arcname=f"{prefix}/{arc}", recursive=False)
            count += 1
        for p in tracked:
            if (ROOT / p).is_file():
                add(ROOT / p, p)
        for p in sorted((ROOT / "sure_native/generated").rglob("*")):
            if p.is_file():
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
