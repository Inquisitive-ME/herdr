#!/usr/bin/env bash
set -euo pipefail
export LC_ALL=C

if [[ $# -gt 2 ]]; then
    echo "Usage: $0 [herdr-src-dir] [base-tag]" >&2
    exit 2
fi
repo_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
source_dir=${1:-/home/richard/workspace/herdr-src}
base_tag=${2:-$(cat "$repo_dir/UPSTREAM_BASE")}
git -C "$source_dir" rev-parse --verify "refs/tags/$base_tag^{commit}" >/dev/null
git -C "$source_dir" merge-base --is-ancestor "refs/tags/$base_tag" HEAD
if [[ -n $(git -C "$source_dir" status --porcelain) ]]; then
    echo "The source checkout must be clean; format-patch exports committed changes only." >&2
    exit 1
fi

# Generate successfully before replacing the queue, so an invalid range cannot erase it.
temp_dir=$(mktemp -d)
trap 'rm -rf -- "$temp_dir"' EXIT
git -C "$source_dir" format-patch --no-signature --zero-commit -N --no-stat \
    --output-directory "$temp_dir" "refs/tags/$base_tag..HEAD" --
mkdir -p "$repo_dir/patches"
shopt -s nullglob
old_patches=("$repo_dir"/patches/*.patch)
if ((${#old_patches[@]})); then
    rm -- "${old_patches[@]}"
fi
new_patches=("$temp_dir"/*.patch)
if ((${#new_patches[@]})); then
    cp -- "${new_patches[@]}" "$repo_dir/patches/"
fi
printf '%s\n' "$base_tag" > "$repo_dir/UPSTREAM_BASE"
echo "Exported ${#new_patches[@]} patch(es) against $base_tag."
