# herdr-asking

Shows what a waiting Claude Code agent is asking in the sidebar's "needs input"
section, for example `Bash: docker compose up -d`, `Edit: src/main.rs` or
`Question: Which approach?`.

It adds Claude Code hooks to `~/.claude/settings.json` (or `$CLAUDE_CONFIG_DIR`). On
`PermissionRequest`, which also fires for questions and plan approval, the hook stores
a one-line summary in the agent pane's `asking` token. It clears the token once the
tool runs, a new prompt is sent or the turn ends. Outside herdr the hooks do nothing.
It needs Python 3.

```sh
extras/claude-asking/install.sh              # install, then start new Claude sessions
extras/claude-asking/install.sh --uninstall  # remove the hooks and script
```

Show the token in the "needs input" rows in `~/.config/herdr/config.toml`:

```toml
[ui.sidebar.agents]
rows = [
  ["state_icon", "workspace", "tab"],
  [{ token = "$asking", dim = true }],
]
```

Rows with no value disappear, so agents without a question keep a single line.
