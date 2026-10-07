"""Safety and reproducibility checks for the data-release tooling."""

from __future__ import annotations

import hashlib
import io
import json
import ssl
import tarfile
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from scripts import data_release


class DataReleaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.source.mkdir()
        self.relative = "Vensim/Input Hour Factors.vdfx"
        self.file = self.source / self.relative
        self.file.parent.mkdir()
        self.file.write_bytes(b"existing Vensim input\n")
        patcher = patch.object(data_release, "DATA_PATHS", (self.relative,))
        patcher.start()
        self.addCleanup(patcher.stop)

    def package(self) -> tuple[dict, Path]:
        output = self.root / "output"
        pin = data_release.package_data(self.source, output, "data-v1.0.0", "a" * 40)
        return pin, output / pin["asset"]

    def test_round_trip_and_local_verification(self) -> None:
        pin, archive = self.package()
        loaded = data_release.load_pin(self.root / "output" / "data-release.json")
        self.assertEqual(pin, loaded)
        destination = self.root / "installed"
        data_release.install_archive(archive, destination, pin)
        data_release.verify_installed(destination, pin)
        self.assertEqual((destination / self.relative).read_bytes(), self.file.read_bytes())
        (destination / self.relative).write_bytes(b"changed input\n")
        with self.assertRaisesRegex(ValueError, "modificato|Checksum"):
            data_release.verify_installed(destination, pin)

    def test_package_is_deterministic(self) -> None:
        first, _ = self.package()
        second = data_release.package_data(self.source, self.root / "other", "data-v1.0.0", "a" * 40)
        self.assertEqual(first["sha256"], second["sha256"])

    def test_missing_and_lfs_pointer_are_rejected(self) -> None:
        self.file.unlink()
        with self.assertRaisesRegex(ValueError, "mancante"):
            self.package()
        self.file.write_text("version https://git-lfs.github.com/spec/v1\noid sha256:abc\n")
        with self.assertRaisesRegex(ValueError, "puntatore Git LFS"):
            self.package()

    def test_wrong_archive_checksum_is_rejected(self) -> None:
        pin, archive = self.package()
        pin["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            data_release.install_archive(archive, self.root / "installed", pin)

    def test_unsafe_tar_member_is_rejected(self) -> None:
        pin, _ = self.package()
        manifest = {
            "schema": 1,
            "tag": pin["tag"],
            "files": [{"path": self.relative, "size": 1, "sha256": hashlib.sha256(b"x").hexdigest()}],
        }
        archive = self.root / "unsafe.tar.gz"
        with tarfile.open(archive, "w:gz") as tar:
            for name, content in (
                ("manifest.json", json.dumps(manifest).encode()),
                (self.relative, b"x"),
                ("../outside", b"escape"),
            ):
                info = tarfile.TarInfo(name)
                info.size = len(content)
                tar.addfile(info, io.BytesIO(content))
        pin["sha256"] = data_release.sha256_file(archive)
        with self.assertRaisesRegex(ValueError, "inattesi"):
            data_release.install_archive(archive, self.root / "installed", pin)
        self.assertFalse((self.root / "outside").exists())

    def test_verified_curl_fallback_for_missing_python_ca_bundle(self) -> None:
        pin, _ = self.package()
        problem = urllib.error.URLError(ssl.SSLCertVerificationError("missing CA"))
        with (
            patch("urllib.request.urlopen", side_effect=problem),
            patch("shutil.which", return_value="/usr/bin/curl"),
            patch("subprocess.run") as run,
        ):
            data_release.download_asset(pin, self.root / "download.tar.gz")
        command = run.call_args.args[0]
        self.assertEqual(command[0], "curl")
        self.assertIn("--fail", command)
        self.assertNotIn("--insecure", command)
        self.assertNotIn("-k", command)


if __name__ == "__main__":
    unittest.main()
