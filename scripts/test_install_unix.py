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
url=""
previous=""
for argument in "$@"; do
    if [ "$previous" = "-o" ]; then out="$argument"; fi
    case "$argument" in https://*) url="$argument" ;; esac
    previous="$argument"
done
case "$url" in
    */extras/shell-count/install.sh)
        printf '#!/bin/sh\\necho "watcher installed with herdr at $(command -v herdr)" >> "$FAKE_LOG"\\n' > "$out" ;;
    */extras/claude-asking/install.sh)
        printf '#!/bin/sh\\necho "asking hooks installed" >> "$FAKE_LOG"\\n' > "$out" ;;
    */extras/*) echo "extra file" > "$out" ;;
    *) if [ -n "$out" ]; then cp "$FAKE_PAYLOAD" "$out"; else cat "$FAKE_MANIFEST"; fi ;;
esac
''')
        # Fake herdr and systemctl that only log what they're asked to do.
        self.log = self.root / "calls.log"
        self.home = self.root / "home"
        self.home.mkdir()
        for command in ("tr", "sh", "sed"):
            (self.bin / command).symlink_to(shutil.which(command))
        self.write_command("systemctl", '#!/bin/sh\necho "systemctl $*" >> "$FAKE_LOG"\n')

    def write_command(self, name, content):
        path = self.bin / name
        path.write_text(content)
        path.chmod(0o755)

    def run_installer(self, *args, checksum=None, tool="sha256sum", on_path=False, extra=None):
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
        # Tests may run inside herdr; don't let its environment leak into the installer.
        base = {k: v for k, v in os.environ.items() if k not in ("HERDR_ENV", "XDG_CONFIG_HOME")}
        env = {**base, "PATH": str(self.bin), "HERDR_INSTALL_DIR": str(self.install),
               "FAKE_PAYLOAD": str(self.payload), "FAKE_MANIFEST": str(self.snapshot),
               "FAKE_LOG": str(self.log), "HOME": str(self.home), **(extra or {})}
        if on_path:
            env.pop("HERDR_INSTALL_DIR", None)
        return subprocess.run(["/bin/sh", str(INSTALLER), *args], env=env, capture_output=True, text=True)

    def calls(self):
        return self.log.read_text() if self.log.exists() else ""

    def fake_installed_herdr(self):
        """A herdr in the install dir with claude installed and two running sessions."""
        self.install.mkdir(exist_ok=True)
        herdr = self.install / "herdr"
        herdr.write_text('''#!/bin/sh
echo "herdr $*" >> "$FAKE_LOG"
case "$1 $2" in
    "integration status") printf 'pi: not installed (x)\\nclaude: current (v11) (y)\\nletta (experimental): current (v1) (z)\\n' ;;
    "session list") echo '{"sessions":[{"default":true,"name":"default","running":true},{"name":"old","running":false},{"name":"work","running":true}]}' ;;
esac
''')
        herdr.chmod(0o755)
        return herdr

    def fake_watcher(self):
        files = [self.home / ".local/bin/herdr-shell-count",
                 self.home / ".config/systemd/user/herdr-shell-count.service"]
        for path in files:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("x")
        return files

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

    def test_with_shell_count_installs_the_watcher_next_to_herdr(self):
        result = self.run_installer("--with-shell-count")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.install / "herdr").read_bytes(), self.payload.read_bytes())
        self.assertIn(f"watcher installed with herdr at {self.install}/herdr", self.calls())

    def test_plain_install_skips_the_watcher_unless_already_installed(self):
        result = self.run_installer()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("watcher installed", self.calls())
        self.fake_watcher()
        result = self.run_installer()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("watcher installed", self.calls())

    def test_uninstall_removes_integrations_watcher_sessions_and_binary(self):
        herdr = self.fake_installed_herdr()
        watcher = self.fake_watcher()
        config = self.home / ".config/herdr"
        config.mkdir(parents=True)
        result = self.run_installer("--uninstall", "--yes")
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.calls()
        self.assertIn("herdr integration uninstall claude", calls)
        self.assertIn("herdr integration uninstall letta", calls)
        self.assertNotIn("integration uninstall pi", calls)
        self.assertIn("herdr session stop default", calls)
        self.assertIn("herdr session stop work", calls)
        self.assertNotIn("session stop old", calls)
        self.assertIn("systemctl --user disable --now herdr-shell-count.service", calls)
        self.assertFalse(herdr.exists())
        for path in watcher:
            self.assertFalse(path.exists())
        self.assertTrue(config.exists(), "config is kept without --purge")
        self.assertIn("--purge", result.stdout)

    def test_with_asking_installs_and_later_runs_update_the_hooks(self):
        result = self.run_installer()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("asking hooks installed", self.calls())
        result = self.run_installer("--with-asking")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("asking hooks installed", self.calls())
        asking = self.home / ".local/bin/herdr-asking"
        asking.parent.mkdir(parents=True, exist_ok=True)
        asking.write_text("x")
        self.log.unlink()
        result = self.run_installer()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("asking hooks installed", self.calls())

    def test_uninstall_removes_the_asking_hooks(self):
        self.fake_installed_herdr()
        asking = self.home / ".local/bin/herdr-asking"
        asking.parent.mkdir(parents=True, exist_ok=True)
        asking.write_text('#!/bin/sh\necho "herdr-asking $*" >> "$FAKE_LOG"\n')
        asking.chmod(0o755)
        result = self.run_installer("--uninstall", "--yes")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("herdr-asking uninstall", self.calls())
        self.assertIn("herdr-asking hooks", result.stdout)

    def test_uninstall_purge_deletes_config(self):
        self.fake_installed_herdr()
        config = self.home / ".config/herdr"
        (config / "sessions").mkdir(parents=True)
        result = self.run_installer("--uninstall", "--purge", "--yes")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(config.exists())

    def test_uninstall_refuses_inside_herdr_and_without_confirmation(self):
        herdr = self.fake_installed_herdr()
        result = self.run_installer("--uninstall", "--yes", extra={"HERDR_ENV": "1"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("outside herdr", result.stderr)
        setsid = shutil.which("setsid")
        if setsid is None:
            self.skipTest("setsid is unavailable")
        result = subprocess.run(
            [setsid, "-w", "/bin/sh", str(INSTALLER), "--uninstall"],  # no controlling terminal
            env={"PATH": str(self.bin), "HOME": str(self.home), "HERDR_INSTALL_DIR": str(self.install),
                 "FAKE_LOG": str(self.log)},
            capture_output=True, text=True, stdin=subprocess.DEVNULL)
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(herdr.exists(), "nothing is removed without confirmation")
        self.assertNotIn("uninstall claude", self.calls())

    def test_purge_requires_uninstall(self):
        result = self.run_installer("--purge")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--purge only works with --uninstall", result.stderr)


if __name__ == "__main__":
    unittest.main()
