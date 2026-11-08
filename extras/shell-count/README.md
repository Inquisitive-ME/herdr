# herdr-shell-count

Shows how many shell commands each agent is running in the patched sidebar, e.g.
`● fridge prod 1 · 2 shells`. That covers Claude Code's background shells plus the
command it is currently running. Commands younger than 3 seconds (hooks) are ignored.

A small watcher runs as a user service. Every 3 seconds it asks herdr which process
each agent pane runs, counts that process's child shells with `ps`, and stores the
count in the pane's `shells` token. Counts expire within a minute if the watcher stops.
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
