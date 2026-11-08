#!/usr/bin/env python3
"""Generate the stable UpdateManifest consumed by upstream src/update.rs (Python 3.10+)."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote

UPSTREAM_MANIFEST_URL = "https://herdr.dev/latest.json"
ASSETS = {
    "linux-x86_64": "herdr-linux-x86_64",
    "linux-aarch64": "herdr-linux-aarch64",
    "macos-x86_64": "herdr-macos-x86_64",
    "macos-aarch64": "herdr-macos-aarch64",
    "windows-x86_64": "herdr-windows-x86_64.zip",
}


def uint32(value: object, name: str) -> int:
    if type(value) is not int or not 0 <= value <= 0xFFFFFFFF:
        raise ValueError(f"{name} must be an unsigned 32-bit integer")
    return value


def source_metadata(source_dir: Path) -> tuple[str, int]:
    # Upstream uses a literal package version. Scope the lookup to [package] so
    # dependency/crate versions cannot accidentally become the release version.
    cargo = (source_dir / "Cargo.toml").read_text(encoding="utf-8")
    package = re.search(r'^\[package\][ \t]*(?:#[^\n]*)?\n(.*?)(?=^\[|\Z)', cargo, re.M | re.S)
    version_match = re.search(r'^version\s*=\s*"([^"\n]+)"', package[1], re.M) if package else None
    if version_match is None:
        raise ValueError("cannot find a literal [package] version in Cargo.toml")
    version = version_match[1]
    wire = (source_dir / "src/protocol/wire.rs").read_text(encoding="utf-8")
    match = re.search(r"^pub const PROTOCOL_VERSION:\s*u32\s*=\s*(\d+);", wire, re.M)
    if match is None:
        raise ValueError("cannot find PROTOCOL_VERSION in src/protocol/wire.rs")
    return version, uint32(int(match[1]), "protocol")


def endpoint_generation(manifest: dict, version: str) -> int | None:
    releases = manifest.get("releases")
    release = releases.get(version) if isinstance(releases, dict) else None
    value = release.get("endpoint_generation") if isinstance(release, dict) else None
    if value is None:
        # None deserializes to Option::None and update_requires_server_restart returns true.
        # Never substitute the unrelated thin-client protocol or another version's generation.
        return None
    return uint32(value, "endpoint_generation")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def make_manifest(
    version: str,
    protocol: int,
    generation: int | None,
    assets_dir: Path,
    repo: str,
    release_tag: str,
    notes: str,
) -> dict:
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError("version must be the stable Cargo.toml version, without v or a suffix")
    uint32(protocol, "protocol")
    if generation is not None:
        uint32(generation, "endpoint_generation")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        raise ValueError("repo must be an owner/name slug")
    if not release_tag or not notes.strip():
        raise ValueError("release tag and notes must not be empty")

    assets = {}
    checksums = {}
    for key, name in ASSETS.items():
        path = assets_dir / name
        if not path.is_file() or path.stat().st_size == 0:
            raise ValueError(f"missing or empty asset: {path}")
        assets[key] = f"https://github.com/{repo}/releases/download/{quote(release_tag, safe='')}/{name}"
        checksums[key] = sha256_file(path)

    metadata = {
        "protocol": protocol,
        "endpoint_generation": generation,
        "notes": notes.strip(),
        "assets": assets,
        "sha256": checksums,
    }
    # String URLs + a separate SHA map also support upstream's Unix installer.
    # metadata_for_version uses the top level for latest and releases for archived notes.
    return {"version": version, **metadata, "releases": {version: dict(metadata)}}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, required=True, help="upstream checkout at the release tag")
    parser.add_argument("--version", help="optional explicit version; must match Cargo.toml")
    parser.add_argument("--protocol", type=int, help="optional explicit protocol; must match wire.rs")
    parser.add_argument("--endpoint-generation", type=int, help="override upstream release metadata")
    parser.add_argument("--upstream-manifest", type=Path, help="local upstream manifest snapshot (offline mode)")
    parser.add_argument("--assets-dir", type=Path, required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--release-tag", required=True)
    parser.add_argument("--notes-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, help="default: stdout")
    args = parser.parse_args()
    try:
        version, protocol = source_metadata(args.source_dir)
        if args.version is not None and args.version != version:
            raise ValueError("--version does not match Cargo.toml")
        if args.protocol is not None and args.protocol != protocol:
            raise ValueError("--protocol does not match wire.rs")
        if args.endpoint_generation is not None:
            generation = uint32(args.endpoint_generation, "endpoint_generation")
        else:
            if args.upstream_manifest:
                upstream = json.loads(args.upstream_manifest.read_text(encoding="utf-8"))
            else:
                try:
                    request = urllib.request.Request(UPSTREAM_MANIFEST_URL, headers={
                        "User-Agent": "herdr-patch-queue/1.0", "Accept": "application/json",
                    })
                    with urllib.request.urlopen(request, timeout=20) as response:
                        upstream = json.load(response)
                except (urllib.error.URLError, TimeoutError, OSError) as error:
                    print(f"Warning: upstream manifest unavailable: {error}", file=sys.stderr)
                    upstream = {}
            generation = endpoint_generation(upstream, version)
            if generation is None:
                print(f"Warning: no endpoint generation for {version}; using null (requires server restart).", file=sys.stderr)
        manifest = make_manifest(
            version, protocol, generation, args.assets_dir, args.repo, args.release_tag,
            args.notes_file.read_text(encoding="utf-8"),
        )
        output = json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
        if args.output:
            args.output.write_text(output, encoding="utf-8")
        else:
            sys.stdout.write(output)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
