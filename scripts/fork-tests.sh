#!/usr/bin/env bash
# Run the tests that cover this queue's patches in a patched herdr checkout.
# Usage: scripts/fork-tests.sh [herdr-src-dir] [extra cargo args...]
#
# Only the fork's own tests run: some upstream tests assert behavior the patches
# replace on purpose (see README), so the full suite is expected to fail there.
set -euo pipefail
source_dir=${1:-/home/richard/workspace/herdr-src}
shift || true
cd "$source_dir"
cargo test --locked "$@" --bin herdr -- \
    client::shell::space_agents:: \
    client::shell::tests::space_tree:: \
    server::client_commands:: \
    state_changes_record_when_the_state_began \
    handoff_keeps_the_start_of_a_redetected_state \
    fork_git_branch_is_read_once_per_folder_every_few_seconds \
    fork_rebuild_of_the_same_version_is_an_update \
    config::sidebar::tests::defaults_match_the_compact_agent_and_existing_space_layouts
cargo test --locked "$@" --test cli -- fork_agent_list_filters_by_workspace
