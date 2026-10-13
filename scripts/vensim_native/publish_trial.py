"""Try Vensim DSS command-script publication and record the form that works."""
from __future__ import annotations

import subprocess
import textwrap
from pathlib import Path

VENSIM = Path(r"C:\Program Files\Vensim\vendss64.exe")
ROOT = Path(r"C:\Users\matteo.palucci.inst\AppData\Local\Temp\vensim-publish-trial")


def main() -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    mdl = ROOT / "tiny.mdl"
    mdl.write_text(
        "{UTF-8}\nX=1\n\t~\t\n\t~\t\t|\n\n"
        "INITIAL TIME=0 ~ Year ~|\n\nFINAL TIME=1 ~ Year ~|\n\n"
        "TIME STEP=1 ~ Year ~|\n\nSAVEPER=TIME STEP ~ Year ~|\n",
        encoding="utf-8",
        newline="\n",
    )
    forms = {
        "minimal.frm": textwrap.dedent(
            """\
            PublishSettings
            561
            1,0,0,0
            0
            1,1,1,1,1,1
            tiny.vpmx
            tiny.mdl
            """
        ),
        "forum.frm": textwrap.dedent(
            """\
            PublishSettings
            561
            1,0,0,0
            0
            1,1,1,1,1,1
            0,0,0,0
            Vensim DSS Version 10.2.2
            tiny.vpmx
            tiny.mdl
            """
        ),
    }
    for name, body in forms.items():
        trial = ROOT / name.replace(".frm", "")
        trial.mkdir(exist_ok=True)
        (trial / "tiny.mdl").write_bytes(mdl.read_bytes())
        (trial / "tiny.frm").write_text(body, encoding="ascii", newline="\r\n")
        cmd = trial / "publish.cmd"
        cmd.write_text(
            "SPECIAL>NOINTERACTION\n"
            f"SPECIAL>LOADMODEL|{trial / 'tiny.mdl'}\n"
            f"FILE>PUBLISH|{trial / 'tiny.frm'}\n"
            "MENU>EXIT\n",
            encoding="ascii",
            newline="\r\n",
        )
        for stale in ("vensim.err", "tiny.vpmx"):
            p = trial / stale
            if p.exists():
                p.unlink()
        print("===", name)
        proc = subprocess.run(
            [str(VENSIM), str(cmd)],
            cwd=trial,
            capture_output=True,
            text=True,
            timeout=90,
        )
        print("rc", proc.returncode)
        print("stdout", proc.stdout[-500:])
        print("stderr", proc.stderr[-500:])
        err = trial / "vensim.err"
        print("err exists", err.exists(), "vpmx", (trial / "tiny.vpmx").exists())
        if err.exists():
            print(err.read_text(encoding="latin-1", errors="replace")[-2000:])


if __name__ == "__main__":
    main()
