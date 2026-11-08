"""Offline manifest tests with dummy release assets; no Rust build required."""

import contextlib
import hashlib
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).with_name("make-manifest.py")
SPEC = importlib.util.spec_from_file_location("make_manifest", SCRIPT)
manifest_tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(manifest_tool)


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="herdr-manifest-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        (self.source / "src/protocol").mkdir(parents=True)
        (self.source / "Cargo.toml").write_text('[package]\nversion = "0.9.5"\n')
        (self.source / "src/protocol/wire.rs").write_text('pub const PROTOCOL_VERSION: u32 = 22;\n')
        self.assets = self.root / "assets"
        self.assets.mkdir()
        for name in manifest_tool.ASSETS.values():
            (self.assets / name).write_bytes(("dummy asset: " + name).encode())
        self.snapshot = self.root / "upstream.json"
        # The top-level value must never override the requested version's metadata.
        self.snapshot.write_text(json.dumps({"endpoint_generation": 99, "releases": {
            "0.9.5": {"endpoint_generation": 1}, "9.0.0": {"endpoint_generation": 7},
        }}))
        self.notes = self.root / "notes.txt"
        self.notes.write_text("Upstream notes.\n\nThis build adds the Inquisitive-ME patches.\n")
        self.output = self.root / "latest.json"

    def args(self):
        return [str(SCRIPT), "--source-dir", str(self.source), "--assets-dir", str(self.assets),
                "--repo", "Inquisitive-ME/herdr", "--release-tag", "v0.9.5-tree.1234abcd",
                "--notes-file", str(self.notes), "--output", str(self.output)]

    def test_cli_dummy_assets_match_upstream_schema_and_checksums(self):
        subprocess.run([sys.executable, "-B", *self.args(), "--upstream-manifest", str(self.snapshot)], check=True)
        manifest = json.loads(self.output.read_text())
        self.assertEqual(set(manifest), {"version", "protocol", "endpoint_generation", "notes", "assets", "sha256", "releases"})
        self.assertEqual((manifest["version"], manifest["protocol"], manifest["endpoint_generation"]), ("0.9.5", 22, 1))
        self.assertEqual(set(manifest["assets"]), set(manifest_tool.ASSETS))
        for key, name in manifest_tool.ASSETS.items():
            self.assertEqual(manifest["assets"][key], f"https://github.com/Inquisitive-ME/herdr/releases/download/v0.9.5-tree.1234abcd/{name}")
            self.assertEqual(manifest["sha256"][key], hashlib.sha256((self.assets / name).read_bytes()).hexdigest())
        self.assertEqual(manifest["releases"]["0.9.5"], {k: v for k, v in manifest.items() if k not in ("version", "releases")})
        self.assertEqual(manifest["notes"], self.notes.read_text().strip())

    def test_missing_generation_stays_unknown(self):
        for snapshot in ({}, {"endpoint_generation": 99}, {"releases": None},
                         {"releases": {"0.9.4": {"endpoint_generation": 1}}}):
            with self.subTest(snapshot=snapshot):
                self.assertIsNone(manifest_tool.endpoint_generation(snapshot, "0.9.5"))

    def test_network_outage_uses_conservative_null(self):
        with mock.patch.object(sys, "argv", self.args()), \
             mock.patch.object(manifest_tool.urllib.request, "urlopen", side_effect=urllib.error.URLError("offline")), \
             contextlib.redirect_stderr(io.StringIO()) as errors:
            manifest_tool.main()
        self.assertIsNone(json.loads(self.output.read_text())["endpoint_generation"])
        self.assertIn("requires server restart", errors.getvalue())

    def test_invalid_generation_is_rejected(self):
        for value in (True, -1, 2**32, "1"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                manifest_tool.endpoint_generation({"releases": {"0.9.5": {"endpoint_generation": value}}}, "0.9.5")

    def test_missing_and_empty_assets_are_rejected(self):
        asset = self.assets / "herdr-linux-aarch64"
        asset.unlink()
        for exists in (False, True):
            if exists:
                asset.touch()
            with self.subTest(empty=exists), self.assertRaisesRegex(ValueError, "missing or empty asset"):
                manifest_tool.make_manifest("0.9.5", 22, 1, self.assets, "Inquisitive-ME/herdr", "tag", "notes")

    def test_metadata_override_must_match_source(self):
        result = subprocess.run([sys.executable, "-B", *self.args(), "--protocol", "23"], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("does not match wire.rs", result.stderr)


if __name__ == "__main__":
    unittest.main()
