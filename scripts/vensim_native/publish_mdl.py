"""Publish a text Vensim model with the form file accepted by DSS 10.2.2."""
from __future__ import annotations

import subprocess
import time
from pathlib import Path

VENSIM = Path(r"C:\Program Files\Vensim\vendss64.exe")
LOG = Path(r"C:\Users\matteo.palucci.inst\AppData\Roaming\Vensim\vensimdp.err")
VERSION_LINE = (
    "Vensim DSS Version 10.2.2 x64 (x64), Build : TK-240930.00384"
)


def form_text(package_name: str, model_name: str, extras: list[str] | None = None) -> str:
    files = [package_name, model_name, *(extras or [])]
    body = [
        "PublishSettings",
        "561",
        "1,0,0,0",
        "0",
        "1,1,1,1,1,1",
        "0,0,0,0",
        "",
        VERSION_LINE,
        *files,
        "",
    ]
    return "\r\n".join(body)


def publish(mdl: Path, vpmx: Path, log_copy: Path, extras: list[Path] | None = None,
            timeout: float = 120) -> str:
    mdl = mdl.resolve()
    vpmx = vpmx.resolve()
    work = mdl.parent
    frm = work / f"{mdl.stem}.frm"
    frm.write_bytes(form_text(vpmx.name, mdl.name, [p.name for p in (extras or [])]).encode("ascii"))
    cmd_path = work / f"publish-{mdl.stem}.cmd"
    cmd_path.write_bytes(
        "SPECIAL>NOINTERACTION\r\n"
        f"SPECIAL>LOADMODEL|{mdl}\r\n"
        f"FILE>PUBLISH|{frm}\r\n"
        "MENU>EXIT\r\n".encode("ascii")
    )
    if LOG.exists():
        LOG.unlink()
    if vpmx.exists():
        vpmx.unlink()
    proc = subprocess.Popen([str(VENSIM), str(cmd_path)], cwd=work)
    deadline = time.time() + timeout
    while time.time() < deadline:
        if vpmx.exists() and vpmx.stat().st_size > 0 and proc.poll() is not None:
            break
        if proc.poll() is not None:
            break
        time.sleep(0.25)
    if proc.poll() is None:
        proc.kill()
        proc.wait(timeout=15)
    text = LOG.read_text(encoding="latin-1", errors="replace") if LOG.exists() else ""
    log_copy.write_text(text, encoding="utf-8")
    if not vpmx.exists() or vpmx.stat().st_size == 0:
        raise RuntimeError(f"Publication failed for {mdl.name}\n{text}")
    return text
