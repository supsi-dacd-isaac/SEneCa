"""Exercise imports using only the files copied into Docker's model builder."""
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class DockerBuildContextTests(unittest.TestCase):
    def test_builder_can_read_parameter_and_output_catalogs_in_isolation(self):
        from sure_julia.catalog import defaults, outputs

        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary)
            active = False
            # Follow the actual COPY list, so forgetting a transitive import
            # fails here before starting the expensive Julia image build.
            for line in (ROOT / "Dockerfile").read_text().replace("\\\n", " ").splitlines():
                if line.startswith("FROM "):
                    active = line.endswith(" AS model-builder")
                if not active or not line.startswith("COPY "):
                    continue
                _, *sources, destination = shlex.split(line)
                if not Path(destination).is_relative_to("/app"):
                    continue
                destination = target / Path(destination).relative_to("/app")
                destination.mkdir(parents=True, exist_ok=True)
                for pattern in sources:
                    for source in ROOT.glob(pattern):
                        if source.is_dir():
                            for path in source.rglob("*"):
                                if (path.is_file() and path.suffix in (".py", ".json")
                                        and "generated" not in path.relative_to(source).parts):
                                    copied = destination / path.relative_to(source)
                                    copied.parent.mkdir(parents=True, exist_ok=True)
                                    shutil.copy2(path, copied)
                        else:
                            shutil.copy2(source, destination / source.name)
            env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
            result = subprocess.run(
                [sys.executable, "-B", "-c", "import json; from sure_julia.catalog import defaults, outputs; "
                 "print(json.dumps({'defaults': defaults(), 'outputs': outputs()}))"],
                cwd=target, env=env, text=True, capture_output=True, timeout=60,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), {"defaults": defaults(), "outputs": outputs()})
