# herdr-shell-count

Shows how many background shells each agent is running in the patched sidebar, e.g.
`● fridge prod 1 · 2 shells`, like Claude Code's own shell count. A Bash call Claude is
waiting on looks the same from outside, but it started during the current working turn
and is at most 10 minutes old, the longest Claude Code waits on a command. So while an
agent is working, a command counts once it's older than the turn or than 10 minutes; a
background command started less than 10 minutes into a turn shows up late. This uses
the patched server's `state_since_ms` token; with an unpatched server every running
command counts. Commands younger than 3 seconds (hooks) are ignored.

A small watcher runs as a user service. Every 3 seconds it asks herdr which process
each agent pane runs, counts that process's commands with `ps`, and stores the count
in the pane's `shells` token. Commands are its child shells, and programs a background
shell turned into with `exec` (a server started as `exec python serve.py`), which
Claude Code still counts. Children the agent started itself at launch (MCP servers),
`caffeinate` and its own helper processes don't count. Counts expire within a minute if the watcher stops.
It needs Python 3 and works on Linux (systemd) and macOS (launchd).

```sh
extras/shell-count/install.sh              # install and start
extras/shell-count/install.sh --uninstall  # stop and remove
python3 extras/shell-count/herdr-shell-count.py --once --dry-run  # just print counts
```

It must run on the machine where the herdr server and agents run.

It never outlives herdr. If herdr is removed, the watcher exits on its next check and
the service doesn't restart it. On Linux the service also won't start at login while
herdr is missing. While herdr is installed but not running, it waits quietly and logs
once. To remove the watcher itself, run `install.sh --uninstall`.
