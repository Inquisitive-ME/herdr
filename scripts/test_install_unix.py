"""Exercise the Unix installer with a fake network and temporary install paths."""

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

INSTALLER = Path(__file__).resolve().parents[1] / "install.sh"


@unittest.skipUnless(os.name == "posix", "requires a Unix shell")
class UnixInstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="herdr-installer-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        for command in ("awk", "cat", "chmod", "cp", "dirname", "mkdir", "mktemp", "mv", "rm"):
            (self.bin / command).symlink_to(shutil.which(command))
        self.payload = self.root / "payload"
        self.payload.write_bytes(b"dummy herdr release\n")
        self.checksum = hashlib.sha256(self.payload.read_bytes()).hexdigest()
        self.install = self.root / "install"
        self.snapshot = self.root / "latest.json"
        self.write_command("uname", '''#!/bin/sh
case "$1" in
    -s) echo "${FAKE_OS:-Linux}" ;;
    -m) echo "${FAKE_ARCH:-x86_64}" ;;
    -o) echo "${FAKE_KERNEL:-GNU/Linux}" ;;
    *) exit 1 ;;
esac
''')
        self.write_command("curl", '''#!/bin/sh
out=""
previous=""
for argument in "$@"; do
    if [ "$previous" = "-o" ]; then out="$argument"; fi
    previous="$argument"
done
if [ -n "$out" ]; then cp "$FAKE_PAYLOAD" "$out"; else cat "$FAKE_MANIFEST"; fi
''')

    def write_command(self, name, content):
        path = self.bin / name
        path.write_text(content)
        path.chmod(0o755)

    def run_installer(self, checksum=None, tool="sha256sum", on_path=False, extra=None):
        for name in ("sha256sum", "shasum", "openssl"):
            (self.bin / name).unlink(missing_ok=True)
        command = shutil.which(tool)
        if command is None:
            self.skipTest(f"{tool} is unavailable")
        (self.bin / tool).symlink_to(command)
        keys = ("linux-x86_64", "linux-aarch64", "macos-x86_64", "macos-aarch64")
        self.snapshot.write_text(json.dumps({
            "version": "0.9.5",
            "assets": {k: f"https://example.invalid/herdr-{k}" for k in keys},
            "sha256": {k: self.checksum.upper() if checksum is None else checksum for k in keys},
        }, indent=2) + "\n")
        env = {**os.environ, "PATH": str(self.bin), "HERDR_INSTALL_DIR": str(self.install),
               "FAKE_PAYLOAD": str(self.payload), "FAKE_MANIFEST": str(self.snapshot), **(extra or {})}
        if on_path:
            env.pop("HERDR_INSTALL_DIR", None)
        return subprocess.run(["/bin/sh", str(INSTALLER)], env=env, capture_output=True, text=True)

    def test_platforms_and_checksum_tools(self):
        for platform, arch in (("Linux", "x86_64"), ("Linux", "aarch64"), ("Darwin", "x86_64"), ("Darwin", "arm64")):
            for tool in ("sha256sum", "shasum", "openssl"):
                with self.subTest(platform=platform, arch=arch, tool=tool):
                    result = self.run_installer(tool=tool, extra={"FAKE_OS": platform, "FAKE_ARCH": arch})
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual((self.install / "herdr").read_bytes(), self.payload.read_bytes())
                    self.assertIn("v0.9.5", result.stdout)
                    self.assertFalse(list(self.install.glob(".herdr.*")))

    def test_existing_path_executable_is_replaced_atomically(self):
        installed = self.bin / "herdr"
        installed.write_bytes(b"old running binary\n")
        installed.chmod(0o755)
        with installed.open("rb") as running:
            old_inode = os.fstat(running.fileno()).st_ino
            result = self.run_installer(on_path=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(running.read(), b"old running binary\n")
            self.assertNotEqual(installed.stat().st_ino, old_inode)
        self.assertEqual(installed.read_bytes(), self.payload.read_bytes())
        self.assertFalse(self.install.exists())

    def test_bad_checksums_preserve_existing_binary(self):
        self.install.mkdir()
        installed = self.install / "herdr"
        installed.write_bytes(b"existing binary\n")
        for checksum in ("0" * 64, "", "z" * 64):
            with self.subTest(checksum=checksum):
                result = self.run_installer(checksum=checksum)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(installed.read_bytes(), b"existing binary\n")
                self.assertFalse(list(self.install.glob(".herdr.*")))

    def test_android_rejected(self):
        result = self.run_installer(extra={"FAKE_KERNEL": "Android"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Android/Termux", result.stderr)
        self.assertFalse(self.install.exists())


if __name__ == "__main__":
    unittest.main()
