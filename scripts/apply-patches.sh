#!/usr/bin/env bash
set -euo pipefail
export LC_ALL=C

if [[ $# != 1 ]]; then
    echo "Usage: $0 <upstream-src-dir>" >&2
    exit 2
fi
repo_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
source_dir=$(cd -- "$1" && pwd)
git -C "$source_dir" rev-parse --show-toplevel >/dev/null
if [[ -d $(git -C "$source_dir" rev-parse --absolute-git-dir)/rebase-apply ]]; then
    echo "An existing git am/rebase operation must be finished first." >&2
    exit 1
fi

shopt -s nullglob
patches=("$repo_dir"/patches/*.patch)
log_file=$(mktemp)
trap 'rm -f -- "$log_file"' EXIT
for patch in "${patches[@]}"; do
    echo "Applying: ${patch##*/}"
    if git -C "$source_dir" am --3way -- "$patch" >"$log_file" 2>&1; then
        cat "$log_file"
    else
        echo "Failed patch: ${patch##*/}" >&2
        cat "$log_file" >&2
        git -C "$source_dir" am --abort || true
        exit 1
    fi
done
echo "Applied ${#patches[@]} patch(es)."
