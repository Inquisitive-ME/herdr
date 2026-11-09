# herdr patch queue

Builds of [herdrdev/herdr](https://github.com/herdrdev/herdr) stable releases with
the Inquisitive-ME sidebar patches. This repository holds patches, scripts, and
CI, not an upstream source checkout.

The patches in `patches/`:

1. **Updates from this repo.** `herdr update`, background version checks and remote
   installs read this repository's `latest.json` instead of herdr.dev. CI compiles the
   release tag in, `latest.json` carries it as `release`, and a different release of
   the same upstream version counts as an update. `herdr --version` prints the release.
2. **State times, branches and pane moves (server).** Agents carry a `state_since_ms`
   token with when their current state began, kept across a live handoff, and a
   `git_branch` token with the branch checked out where they work. Clients may call
   `pane.move`. This changes the server, so a running server needs a restart or
   `herdr server live-handoff --import-exe <new herdr>` (keeps agents running) to pick
   it up. Older servers just show no ages or branches and refuse cross-space drags.
3. **Agents under their space.** Most of the code is in a new file
   (`src/client/shell/space_agents.rs`) so upstream changes rarely conflict with it.
   - Each space in the sidebar lists its tabs underneath, and clicking one jumps to it.
     Working and blocked agents show how long they've been at it (`12m`, `3h`, `2d`).
   - Agent lines show `· N shells` when the agent is running shell commands. The count
     comes from the watcher in [`extras/shell-count`](extras/shell-count), which runs as
     a user service on the machine where herdr's server runs.
   - Plain terminals are listed dimmed (`$ backend`). Right-click a space and choose
     Hide terminals to hide them there.
   - A pane working outside its space's home folder (the first tab's) gets a
     `↳ subdir` line.
   - The ▾ at the right of a space collapses it to one summary row of status counts
     (`●2 ✓1 $2`); clicking the summary expands it again.
   - Drag a line onto another space to move it there as a new tab, or onto a line in
     the same space to reorder tabs. Right-click a line to rename its tab, move it to
     another or a new space, or close it.
   - The section under the spaces lists agents needing input (a permission, question or
     plan approval) first, then agents whose finished turn you haven't looked at yet
     under a "finished" heading. Visiting an agent clears it. The section sits right
     under the spaces list, dropping to the bottom only when the list is too long to
     leave room. Reattaching keeps the turns the server still reports unread.
   - `keys.next_agent` / `previous_agent` cycle the most urgent non-empty group (all
     agents when nobody is waiting). `keys.focus_agent` follows the tree order and shows
     the numbers 1-9 beside agents while it's bound.
   - With machines added, the tree of the machine being shown supports dragging and the
     right-click menu, clicking another machine's agent switches to it on release, and
     the agent keys and numbers walk the tree across all machines.
   - Upstream tests of the behavior this replaces fail by design, and CI does not run
     them: the sidebar tests for the old agent list, sort toggle and fixed divider,
     `first_snapshot_establishes_an_idle_baseline_without_server_seen_authority`,
     `local_agent_click_can_cancel_a_pending_remote_switch` and
     `switching_machines_preserves_aggregate_agent_scroll_and_visible_rows`.
4. **Boxes, shading and hover.**
   - Each space and its tree sit in a box; neighbouring spaces share a border row, and
     in the multi-machine sidebar each machine's spaces are boxed under its name.
     Sidebars narrower than 12 columns go without.
   - Every other tab in a space, and every other agent in the needs-input and finished
     groups, is shaded a few percent lighter than the terminal's background. The line
     under the mouse (a machine, space, tab, collapsed summary or waiting agent) lights
     up a step brighter; the current tab and space keep their own highlight. Both need a
     terminal that reports its background.
   - Hovering a tab line shows a card beside the sidebar with the folder it works in
     and, for an agent, its git branch.
   - Plain terminals show `$` in the agent-number column so their names line up with the
     agents', and waiting agents show their tree number in the same column.
   - Dragging a space below the last one marks the bottom edge of the last box.
   - Upstream's `mouse_hits_use_stable_workspace_tab_and_pane_ids` clicks the row that is
     now a box border and fails by design.

Builds: Linux x86_64, Linux ARM (aarch64) and Apple Silicon macOS. There are no
Windows or Intel Mac builds; use upstream herdr there.

## Install

Everything, on Linux or an Apple Silicon Mac:

```sh
curl -fsSL https://raw.githubusercontent.com/Inquisitive-ME/herdr/main/install.sh | sh -s -- --with-shell-count --with-asking
```

Just herdr, without the extras:

```sh
curl -fsSL https://raw.githubusercontent.com/Inquisitive-ME/herdr/main/install.sh | sh
```

Releases are named `v<upstream version>-tree.<patch set>`, e.g. `v0.9.5-tree.21330f2a`;
the installer prints the one it installed. `herdr --version` shows only the upstream
version.

If herdr was already running, its server keeps the old binary. Swap it without
stopping your agents (macOS and Linux), from a terminal outside herdr:

```sh
herdr server live-handoff --import-exe "$(command -v herdr)"
```

Then detach (`Ctrl+b q`) and run `herdr` again to load the new sidebar. With no
agents worth keeping, `herdr server stop` and starting `herdr` works too.

If herdr came from Homebrew, run `brew uninstall herdr` first so Homebrew doesn't
put upstream back.

### Config for the sidebar features

These go in `~/.config/herdr/config.toml`; none are required:

```toml
[ui]
# Let the sidebar's right edge drag wider than the default 36 columns.
sidebar_max_width = 60

[keys]
next_agent = "prefix+a"            # next agent needing input, then unread finished
previous_agent = "prefix+shift+a"
focus_agent = "prefix+alt+1..9"    # also numbers the agents in the sidebar

# Needs-input rows: where the agent is, then what it's asking (--with-asking).
[ui.sidebar.agents]
rows = [
  ["state_icon", "workspace", "tab"],
  [{ token = "$asking", dim = true }],
]
```

Run `herdr config check` after editing.

### Options

The installer verifies the SHA-256 checksum and replaces the `herdr` on PATH
atomically (a running herdr keeps working), or installs to `~/.local/bin/herdr`
if none exists. Set `HERDR_INSTALL_DIR` to choose another directory.

Options go after `sh -s --` when piping, e.g. `... | sh -s -- --with-shell-count`:

- `--with-shell-count` also installs the [shell-count watcher](extras/shell-count).
- `--with-asking` also installs [Claude Code hooks](extras/claude-asking) that show
  what a waiting agent is asking (`Bash: docker compose up`) in the needs-input
  section.
- Once an extra is installed, later installs update it too.
- `--uninstall` lists what it will do, asks, then removes herdr's agent integrations
  (such as the Claude hooks), the extras above, stops running herdr sessions
  (closing their panes and agents) and deletes the herdr binary. Run it outside
  herdr. Add `--purge` to also delete `~/.config/herdr` (config, saved sessions,
  logs) and `--yes` to skip the question.

### Updating

Run `herdr update` outside herdr, or rerun the install command, which also updates
the extras. Builds before `v0.9.5-tree.1811b71c` can't see patch-only rebuilds, so update
those once with the install command. When a release changes the server (the README
marks those patches), swap it with the live-handoff command above.

CI checks daily and on queue/script changes. It picks the latest published stable
upstream version and publishes `<upstream_tag>-tree.<8-digit-patch-sha256>`.
The hash covers the concatenated bytes of `patches/*.patch` in filename order.
Existing release tags are skipped; a manual run can select `upstream_tag` and
set `force` to replace the assets. The release includes the three platform assets,
`latest.json`, and `SHA256SUMS` (covering the assets and manifest).

Before publishing, CI runs `scripts/fork-tests.sh`, the tests covering the patches,
and the script tests; a failure blocks the release.

When patches stop applying, CI opens an issue titled `Patches don't apply to
<tag>`, or comments on the existing open issue. It then runs
[`fix-patches.yml`](.github/workflows/fix-patches.yml): Claude rebases the patches
onto the new tag on a read-only runner, the workflow re-checks that the exported queue
applies, builds and passes the fork tests, and opens a pull request
(`auto/rebase-<tag>`) for you to review and merge. If that fails, it comments on the
issue. This needs a `CLAUDE_CODE_OAUTH_TOKEN` repository secret (from
`claude setup-token`) or an `ANTHROPIC_API_KEY`, plus "Allow GitHub Actions to create
and approve pull requests" in the repository's Actions settings. You can also run
it by hand from the Actions tab with an upstream tag.

To fix it yourself instead, rebase the patched `herdr-src`
branch onto the new tag, resolve conflicts, then run:

```sh
scripts/export-patches.sh /path/to/herdr-src vNEW.VERSION.HERE
```

Review the exported patches and `UPSTREAM_BASE`, then push the patch queue.
Export defaults to `/home/richard/workspace/herdr-src` and the tag in
`UPSTREAM_BASE`. The source checkout must be clean. To apply a queue manually:

```sh
scripts/apply-patches.sh /path/to/clean/upstream-checkout
```

The manifest reads the version and thin-client `PROTOCOL_VERSION` from the
release tag. Endpoint generation is a separate compatibility contract: it uses
`https://herdr.dev/latest.json`'s `releases[version].endpoint_generation` when
available. If missing or the server is unreachable, it emits `null`, which
upstream treats as requiring a server restart. It never guesses from the
protocol number or another release. A local snapshot can be supplied with
`--upstream-manifest`, or a known generation with `--endpoint-generation`.

Local manifest and installer tests (Python 3.10+):

```sh
python3 -B -m unittest discover -s scripts -p 'test_*.py'
```

## Sidebar mockups

[`tools/sidebar-mockup`](tools/sidebar-mockup) draws a herdr build's sidebar to a PNG
the way kitty's Breeze Dark theme shows it, to compare looks before shipping them. It
runs the binary in a throwaway session with its own config, state and sockets (deleted
afterwards; a running herdr is not touched) and a made-up layout. Needs `pip install
pyte pillow`.

```sh
python3 tools/sidebar-mockup/mockup.py target/debug/herdr out.png --attention --hover deploy
python3 tools/sidebar-mockup/side_by_side.py both.png before.png before out.png after
```

herdr is developed by [herdrdev/herdr](https://github.com/herdrdev/herdr) and
licensed under Apache-2.0. The installer is adapted from upstream's
distribution script. See [LICENSE](LICENSE).
