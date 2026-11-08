# herdr patch queue

Builds of [herdrdev/herdr](https://github.com/herdrdev/herdr) stable releases with
the Inquisitive-ME sidebar patches. This repository holds patches, scripts, and
CI, not an upstream source checkout.

The patches in `patches/`:

1. **Agents under their space.** Each space in the sidebar lists its agents
   underneath, and clicking one jumps to that agent. The agent section below only
   shows agents that need input and only appears while one does. Most of the code
   is in a new file (`src/client/shell/space_agents.rs`) so upstream changes rarely
   conflict with it. Upstream's sidebar tests for the replaced agent list, sort
   toggle and fixed divider fail with this patch; that is expected and CI does not
   run them.
2. **Updates from this repo.** `herdr update`, background version checks and
   remote installs read this repository's `latest.json` instead of herdr.dev.
3. **Shell counts.** Agent lines show `· N shells` when the agent is running shell
   commands. The count comes from the watcher in
   [`extras/shell-count`](extras/shell-count), which runs as a user service on the
   machine where herdr's server runs.
4. **Needs input under the list.** The needs-input section sits right under the
   spaces list and moves with it, dropping to the bottom only when the list is too
   long to leave room.

Builds: Linux x86_64, Linux ARM (aarch64) and Apple Silicon macOS. There are no
Windows or Intel Mac builds; use upstream herdr there.

Install:

```sh
curl -fsSL https://raw.githubusercontent.com/Inquisitive-ME/herdr/main/install.sh | sh
```

The installer verifies the SHA-256 checksum and replaces the `herdr` on PATH
atomically (a running herdr keeps working), or installs to `~/.local/bin/herdr`
if none exists. Set `HERDR_INSTALL_DIR` to choose another directory.

Options go after `sh -s --` when piping, e.g. `... | sh -s -- --with-shell-count`:

- `--with-shell-count` also installs the [shell-count watcher](extras/shell-count).
  Once it's installed, later installs update it too.
- `--uninstall` lists what it will do, asks, then removes herdr's agent integrations
  (such as the Claude hooks), the shell-count watcher, stops running herdr sessions
  (closing their panes and agents) and deletes the herdr binary. Run it outside
  herdr. Add `--purge` to also delete `~/.config/herdr` (config, saved sessions,
  logs) and `--yes` to skip the question.

After the first patched install, `herdr update` follows this repository's
`latest.json`. Upstream compares the Cargo version, so patch-only rebuilds of the same version
require rerunning the installer.

CI checks daily and on queue/script changes. It picks the latest published stable
upstream version and publishes `<upstream_tag>-tree.<8-digit-patch-sha256>`.
The hash covers the concatenated bytes of `patches/*.patch` in filename order.
Existing release tags are skipped; a manual run can select `upstream_tag` and
set `force` to replace the assets. The release includes the three platform assets,
`latest.json`, and `SHA256SUMS` (covering the assets and manifest).

When patches stop applying, CI opens an issue titled `Patches don't apply to
<tag>`, or comments on the existing open issue. Rebase the patched `herdr-src`
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

herdr is developed by [herdrdev/herdr](https://github.com/herdrdev/herdr) and
licensed under Apache-2.0. The installer is adapted from upstream's
distribution script. See [LICENSE](LICENSE).
