"""The production image serves the committed native build exactly as recorded."""
import fnmatch
import hashlib
import json
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
BUILD = "sure_native/generated"


class DockerBuildContextTests(unittest.TestCase):
    def test_image_selects_the_native_build(self):
        dockerfile = (ROOT / "Dockerfile").read_text()
        self.assertIn(f"SURE_JULIA_MODEL=/app/{BUILD}", dockerfile)
        self.assertIn("scripts/verify_julia_release.py", dockerfile)
        if not (ROOT / ".dockerignore").exists():
            # inside the image: .dockerignore is not copied, the build itself is present
            self.assertTrue((ROOT / BUILD / "build.json").is_file())
            return
        ignored = [line.strip() for line in (ROOT / ".dockerignore").read_text().splitlines()
                   if line.strip() and not line.startswith("#")]
        for pattern in ignored:
            self.assertFalse(fnmatch.fnmatch(f"{BUILD}/build.json", pattern.rstrip("/") + "*")
                             or BUILD.startswith(pattern.rstrip("/")), pattern)

    def test_committed_build_files_match_their_checksums(self):
        # Git must store the bytes unchanged (-text), whatever the checkout platform.
        build = json.loads((ROOT / BUILD / "build.json").read_text())
        try:
            tracked = subprocess.run(["git", "ls-files", BUILD], cwd=ROOT, text=True,
                                     capture_output=True, check=True).stdout.split()
        except (OSError, subprocess.CalledProcessError):
            self.skipTest("No git checkout")
        if not tracked:
            self.skipTest("Build not committed in this checkout")
        for name, expected in build["artifacts"].items():
            blob = subprocess.run(["git", "cat-file", "-p", f"HEAD:{BUILD}/{name}"], cwd=ROOT,
                                  capture_output=True, check=True).stdout
            self.assertEqual(hashlib.sha256(blob).hexdigest(), expected, name)
