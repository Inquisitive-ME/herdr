#!/bin/sh
# Install (or with --uninstall, remove) the herdr-asking Claude Code hooks.
set -eu
here=$(cd -- "$(dirname -- "$0")" && pwd)
bin="$HOME/.local/bin/herdr-asking"
if [ "${1:-}" = --uninstall ]; then
    if [ -x "$bin" ]; then
        "$bin" uninstall
    else
        sh "$here/herdr-asking" uninstall
    fi
    exit 0
fi
command -v python3 >/dev/null 2>&1 || { echo "herdr-asking needs python3" >&2; exit 1; }
mkdir -p "$(dirname "$bin")"
install -m 755 "$here/herdr-asking" "$bin"
"$bin" install
