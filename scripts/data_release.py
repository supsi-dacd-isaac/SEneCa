"""Package and install the immutable data snapshot used by SEneCa releases.

Only ``pack`` needs the project dependencies (pyarrow for Parquet validation).
``fetch`` and ``verify`` use the Python standard library so they can run before
the Docker image installs its dependencies.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
import re
import shutil
import ssl
import subprocess
import tarfile
import tempfile
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
PIN_PATH = ROOT / "data-release.json"
INSTALLED_PATH = ".data-release-installed.json"
REPOSITORY = "supsi-dacd-isaac/SEneCa"
DATA_PATHS = (
    "Vensim/EVinput.vdfx",
    "Vensim/HPinput.vdfx",
    "Vensim/Input Hour Factors.vdfx",
    "Vensim/Input2011.vdfx",
    "Vensim/InputRenovation.vdfx",
    "Vensim/PVinput.vdfx",
    "Vensim/SURE.vpmx",
    "precomputed/elettricita_combo_index.parquet",
    "precomputed/elettricita_hourly.parquet",
    "precomputed/exploratory/uncertainty_samples.parquet",
    "precomputed/exploratory_kpis.parquet",
    "precomputed/pv_batteries_gmd.parquet",
    "precomputed/pv_batteries_scenarios.parquet",
    "precomputed/risanamento_gmd.parquet",
    "precomputed/risanamento_scenarios.parquet",
    "precomputed/veicoli_scenarios.parquet",
)
TAG_RE = re.compile(r"data-v[0-9]+\.[0-9]+\.[0-9]+\Z")
SHA_RE = re.compile(r"[0-9a-f]{64}\Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_lfs_pointer(path: Path) -> bool:
    with path.open("rb") as stream:
        return stream.read(80).startswith(b"version https://git-lfs.github.com/spec/v1")


def _validate_source(root: Path, relative: str) -> dict:
    path = root / relative
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"File dati mancante o non regolare: {relative}")
    size = path.stat().st_size
    if size == 0 or _is_lfs_pointer(path):
        raise ValueError(f"File vuoto o puntatore Git LFS: {relative}")
    if path.suffix == ".parquet":
        try:
            import pyarrow.parquet as pq
        except ImportError as exc:
            raise RuntimeError("Installa requirements.txt per validare i Parquet") from exc
        metadata = pq.ParquetFile(path).metadata
        if metadata.num_rows == 0:
            raise ValueError(f"Parquet senza righe: {relative}")
    return {"path": relative, "size": size, "sha256": sha256_file(path)}


def _add_bytes(archive: tarfile.TarFile, name: str, content: bytes) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(content)
    info.mode = 0o644
    info.mtime = 0
    archive.addfile(info, io.BytesIO(content))


def package_data(root: Path, output: Path, tag: str, source_commit: str) -> dict:
    if not TAG_RE.fullmatch(tag):
        raise ValueError("Il tag dati deve avere forma data-vX.Y.Z")
    if not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise ValueError("source_commit deve essere un commit SHA completo")
    files = [_validate_source(root, relative) for relative in DATA_PATHS]
    manifest = {"schema": 1, "tag": tag, "source_commit": source_commit, "files": files}
    manifest_bytes = (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode()
    output.mkdir(parents=True, exist_ok=True)
    asset = f"seneca-{tag}.tar.gz"
    archive_path = output / asset
    partial = output / f".{asset}.partial"
    try:
        with partial.open("wb") as raw:
            with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as zipped:
                with tarfile.open(fileobj=zipped, mode="w", format=tarfile.PAX_FORMAT) as archive:
                    _add_bytes(archive, "manifest.json", manifest_bytes)
                    for item in files:
                        path = root / item["path"]
                        info = tarfile.TarInfo(item["path"])
                        info.size = item["size"]
                        info.mode = 0o644
                        info.mtime = 0
                        with path.open("rb") as stream:
                            archive.addfile(info, stream)
        os.replace(partial, archive_path)
    finally:
        partial.unlink(missing_ok=True)
    digest = sha256_file(archive_path)
    pin = {"schema": 1, "repository": REPOSITORY, "tag": tag, "asset": asset, "sha256": digest}
    (output / "data-release.json").write_text(json.dumps(pin, indent=2) + "\n", encoding="utf-8")
    (output / "SHA256SUMS.txt").write_text(f"{digest}  {asset}\n", encoding="ascii")
    return pin


def load_pin(path: Path) -> dict:
    pin = json.loads(path.read_text(encoding="utf-8"))
    if (
        pin.get("schema") != 1
        or pin.get("repository") != REPOSITORY
        or not TAG_RE.fullmatch(str(pin.get("tag", "")))
        or pin.get("asset") != f"seneca-{pin.get('tag')}.tar.gz"
        or not SHA_RE.fullmatch(str(pin.get("sha256", "")))
    ):
        raise ValueError(f"Pin dati non valido: {path}")
    return pin


def _check_manifest(manifest: dict, pin: dict, members: list[tarfile.TarInfo]) -> None:
    if manifest.get("schema") != 1 or manifest.get("tag") != pin["tag"]:
        raise ValueError("Manifest della release dati non corrispondente al pin")
    records = manifest.get("files")
    if not isinstance(records, list) or len(records) != len(DATA_PATHS):
        raise ValueError("Elenco file nel manifest incompleto")
    paths = [item.get("path") for item in records if isinstance(item, dict)]
    if len(paths) != len(DATA_PATHS) or set(paths) != set(DATA_PATHS) or len(set(paths)) != len(paths):
        raise ValueError("Elenco file nel manifest diverso da quello atteso")
    by_name = {member.name: member for member in members}
    if len(by_name) != len(members) or set(by_name) != {"manifest.json", *DATA_PATHS}:
        raise ValueError("Archivio con percorsi duplicati, mancanti o inattesi")
    if any(not member.isfile() for member in members):
        raise ValueError("L'archivio contiene link o file non regolari")
    for item in records:
        if not isinstance(item.get("size"), int) or item["size"] <= 0:
            raise ValueError(f"Dimensione non valida: {item['path']}")
        if not SHA_RE.fullmatch(str(item.get("sha256", ""))):
            raise ValueError(f"Checksum non valido: {item['path']}")
        if by_name[item["path"]].size != item["size"]:
            raise ValueError(f"Dimensione diversa dal manifest: {item['path']}")


def install_archive(archive_path: Path, destination: Path, pin: dict) -> dict:
    if sha256_file(archive_path) != pin["sha256"]:
        raise ValueError("SHA-256 dell'archivio dati diverso dal pin")
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".seneca-data-", dir=destination) as temp_name:
        staging = Path(temp_name)
        with tarfile.open(archive_path, mode="r:gz") as archive:
            members = archive.getmembers()
            manifest_member = next((member for member in members if member.name == "manifest.json"), None)
            if manifest_member is None or not manifest_member.isfile() or manifest_member.size > 1024 * 1024:
                raise ValueError("Manifest mancante o non valido nell'archivio")
            manifest_stream = archive.extractfile(manifest_member)
            if manifest_stream is None:
                raise ValueError("Impossibile leggere il manifest")
            manifest = json.load(manifest_stream)
            _check_manifest(manifest, pin, members)
            for item in manifest["files"]:
                member = archive.getmember(item["path"])
                source = archive.extractfile(member)
                if source is None:
                    raise ValueError(f"Impossibile leggere {item['path']}")
                target = staging / item["path"]
                target.parent.mkdir(parents=True, exist_ok=True)
                digest = hashlib.sha256()
                with target.open("wb") as out:
                    for chunk in iter(lambda: source.read(1024 * 1024), b""):
                        digest.update(chunk)
                        out.write(chunk)
                if digest.hexdigest() != item["sha256"] or _is_lfs_pointer(target):
                    raise ValueError(f"Contenuto non valido: {item['path']}")
        for item in manifest["files"]:
            target = destination / item["path"]
            parent = destination
            for part in Path(item["path"]).parts[:-1]:
                parent = parent / part
                if parent.is_symlink():
                    raise ValueError(f"Directory dati simbolica non consentita: {parent}")
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.is_symlink():
                raise ValueError(f"File dati simbolico non consentito: {target}")
            os.replace(staging / item["path"], target)
        installed = {"tag": pin["tag"], "sha256": pin["sha256"], "files": manifest["files"]}
        marker = staging / INSTALLED_PATH
        marker.write_text(json.dumps(installed, indent=2) + "\n", encoding="utf-8")
        os.replace(marker, destination / INSTALLED_PATH)
    return manifest


def verify_installed(destination: Path, pin: dict) -> None:
    marker = destination / INSTALLED_PATH
    if not marker.is_file():
        raise ValueError("Dati non installati: esegui python scripts/data_release.py fetch")
    installed = json.loads(marker.read_text(encoding="utf-8"))
    if installed.get("tag") != pin["tag"] or installed.get("sha256") != pin["sha256"]:
        raise ValueError("Dati locali diversi dalla release pinata: esegui fetch")
    records = installed.get("files", [])
    if len(records) != len(DATA_PATHS) or {item.get("path") for item in records} != set(DATA_PATHS):
        raise ValueError("Manifest locale incompleto")
    for item in records:
        path = destination / item["path"]
        if not path.is_file() or path.is_symlink() or path.stat().st_size != item["size"]:
            raise ValueError(f"File dati mancante o modificato: {item['path']}")
        if _is_lfs_pointer(path) or sha256_file(path) != item["sha256"]:
            raise ValueError(f"Checksum dati non valido: {item['path']}")


def download_asset(pin: dict, output: Path) -> None:
    url = f"https://github.com/{pin['repository']}/releases/download/{pin['tag']}/{pin['asset']}"
    request = urllib.request.Request(url, headers={"User-Agent": "SEneCa-data-release/1"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response, output.open("wb") as stream:
            shutil.copyfileobj(response, stream, length=1024 * 1024)
    except urllib.error.URLError as exc:
        # Some macOS Python installations have no CA bundle; curl uses the OS
        # trust store. Never disable certificate verification.
        if not isinstance(exc.reason, ssl.SSLCertVerificationError) or not shutil.which("curl"):
            raise
        subprocess.run(
            ["curl", "--fail", "--location", "--silent", "--show-error", "--retry", "3",
             "--output", str(output), url],
            check=True,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    pack = commands.add_parser("pack", help="Prepara archivio e checksum per una release dati")
    pack.add_argument("--tag", required=True)
    pack.add_argument("--source-commit", required=True)
    pack.add_argument("--root", type=Path, default=ROOT)
    pack.add_argument("--output", type=Path, default=ROOT / "dist" / "data-release")
    fetch = commands.add_parser("fetch", help="Installa la release dati pinata")
    fetch.add_argument("--pin", type=Path, default=PIN_PATH)
    fetch.add_argument("--destination", type=Path, default=ROOT)
    fetch.add_argument("--archive", type=Path, help="Archivio locale per test o installazione offline")
    verify = commands.add_parser("verify", help="Verifica i dati installati")
    verify.add_argument("--pin", type=Path, default=PIN_PATH)
    verify.add_argument("--destination", type=Path, default=ROOT)
    args = parser.parse_args()
    try:
        if args.command == "pack":
            pin = package_data(args.root, args.output, args.tag, args.source_commit)
            print(f"Archivio pronto: {args.output / pin['asset']}")
            print(f"SHA-256: {pin['sha256']}")
            print(f"Pubblica anche {args.output / 'SHA256SUMS.txt'}")
            print(f"Dopo la pubblicazione, copia il contenuto di {args.output / 'data-release.json'} nel pin del repository")
        elif args.command == "fetch":
            pin = load_pin(args.pin)
            if args.archive:
                install_archive(args.archive, args.destination, pin)
            else:
                with tempfile.TemporaryDirectory(prefix="seneca-download-") as temp_name:
                    archive_path = Path(temp_name) / pin["asset"]
                    download_asset(pin, archive_path)
                    install_archive(archive_path, args.destination, pin)
            print(f"Dati {pin['tag']} installati e verificati in {args.destination}")
        else:
            pin = load_pin(args.pin)
            verify_installed(args.destination, pin)
            print(f"Dati {pin['tag']} verificati")
    except (OSError, ValueError, tarfile.TarError, json.JSONDecodeError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"Errore dati SEneCa: {exc}\n")


if __name__ == "__main__":
    main()
