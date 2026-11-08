#!/bin/sh
# Install (or with --uninstall, remove) the herdr shell-count watcher as a user service.
set -eu

here=$(cd -- "$(dirname -- "$0")" && pwd)
bin="$HOME/.local/bin/herdr-shell-count"
unit="$HOME/.config/systemd/user/herdr-shell-count.service"
label="com.inquisitive-me.herdr-shell-count"
plist="$HOME/Library/LaunchAgents/$label.plist"

case "$(uname -s)" in
    Linux)
        if [ "${1:-}" = --uninstall ]; then
            systemctl --user disable --now herdr-shell-count.service 2>/dev/null || true
            rm -f "$unit" "$bin"
            systemctl --user daemon-reload
            echo "removed herdr-shell-count"
            exit 0
        fi
        mkdir -p "$(dirname "$bin")" "$(dirname "$unit")"
        install -m 755 "$here/herdr-shell-count.py" "$bin"
        install -m 644 "$here/herdr-shell-count.service" "$unit"
        systemctl --user daemon-reload
        systemctl --user enable --now herdr-shell-count.service
        systemctl --user restart herdr-shell-count.service  # pick up a new script on reinstall
        echo "herdr-shell-count running (systemctl --user status herdr-shell-count)"
        ;;
    Darwin)
        launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
        if [ "${1:-}" = --uninstall ]; then
            rm -f "$plist" "$bin"
            echo "removed herdr-shell-count"
            exit 0
        fi
        mkdir -p "$(dirname "$bin")" "$(dirname "$plist")"
        install -m 755 "$here/herdr-shell-count.py" "$bin"
        sed "s#__HOME__#$HOME#g" "$here/$label.plist" > "$plist"
        launchctl bootstrap "gui/$(id -u)" "$plist"
        echo "herdr-shell-count running (log: ~/Library/Logs/herdr-shell-count.log)"
        ;;
    *)
        echo "unsupported OS" >&2
        exit 1
        ;;
esac
