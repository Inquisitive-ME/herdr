#!/bin/sh
# Adapted from herdrdev/herdr's Apache-2.0 distribution/install.sh.
#
# Install or update herdr from Inquisitive-ME/herdr releases:
#   curl -fsSL https://raw.githubusercontent.com/Inquisitive-ME/herdr/main/install.sh | sh
# Pass options after `sh -s --` when piping, e.g. `| sh -s -- --with-shell-count`:
#   --with-shell-count  also install the shell-count watcher (extras/shell-count)
#   --with-asking       also install Claude Code hooks that show what a waiting agent
#                       is asking (extras/claude-asking)
#                       Once an extra is installed, later runs update it too.
#   --uninstall         stop herdr, remove its agent integrations, the extras and
#                       the herdr binary
#   --purge             with --uninstall, also delete herdr's config, saved sessions
#                       and logs
#   --yes               don't ask before uninstalling
set -eu

MANIFEST_URL="https://github.com/Inquisitive-ME/herdr/releases/latest/download/latest.json"
EXTRAS_URL="https://raw.githubusercontent.com/Inquisitive-ME/herdr/main/extras"
SHELL_COUNT_BIN="$HOME/.local/bin/herdr-shell-count"
SHELL_COUNT_LABEL="com.inquisitive-me.herdr-shell-count"
ASKING_BIN="$HOME/.local/bin/herdr-asking"

log() { printf '  > %s\n' "$1"; }
err() { printf 'error: %s\n' "$1" >&2; exit 1; }
need() { command -v "$1" >/dev/null 2>&1 || err "requires '$1'"; }

TMP=""
EXTRAS_TMP=""
trap 'rm -f "$TMP"; rm -rf "$EXTRAS_TMP"' 0
trap 'exit 1' HUP INT TERM

install_herdr() {
    need curl
    need awk
    OS=$(uname -s)
    case "$OS" in
        Linux) os=linux ;;
        Darwin) os=macos ;;
        *) err "unsupported OS: $OS" ;;
    esac
    if [ "$OS" = Linux ] && [ "$(uname -o 2>/dev/null || true)" = Android ]; then
        err "Android/Termux is not supported by the release binaries"
    fi
    ARCH=$(uname -m)
    case "$ARCH" in
        x86_64|amd64) arch=x86_64 ;;
        aarch64|arm64) arch=aarch64 ;;
        *) err "unsupported architecture: $ARCH" ;;
    esac
    TARGET="${os}-${arch}"
    log "detected $TARGET"

    # make-manifest.py emits upstream's pretty-printed string URL + SHA map format.
    MANIFEST=$(curl -fsSL --retry 3 --connect-timeout 10 --max-time 20 "$MANIFEST_URL") \
        || err "cannot fetch $MANIFEST_URL"
    URL=$(printf '%s\n' "$MANIFEST" | awk -v target="\"${TARGET}\"" '
        /^[[:space:]]*"assets"[[:space:]]*:/ { in_assets = 1; next }
        in_assets && /^[[:space:]]*}/ { exit }
        in_assets && index($0, target) {
            sub(/^.*:[[:space:]]*"/, ""); sub(/".*$/, ""); print; exit
        }
    ')
    SHA256=$(printf '%s\n' "$MANIFEST" | awk -v target="\"${TARGET}\"" '
        /^[[:space:]]*"sha256"[[:space:]]*:/ { in_sha256 = 1; next }
        in_sha256 && /^[[:space:]]*}/ { exit }
        in_sha256 && index($0, target) {
            sub(/^.*:[[:space:]]*"/, ""); sub(/".*$/, ""); print; exit
        }
    ')
    VERSION=$(printf '%s\n' "$MANIFEST" | awk -F '"' '/^[[:space:]]*"version"[[:space:]]*:/ { print $4; exit }')
    [ -n "$URL" ] || err "no build for $TARGET (this fork builds Linux x86_64/aarch64 and Apple Silicon macOS)"
    case "$URL" in https://*) ;; *) err "asset URL must use HTTPS" ;; esac
    [ -n "$VERSION" ] || err "manifest has no version"
    [ "${#SHA256}" -eq 64 ] || err "manifest has no valid SHA-256 for $TARGET"
    case "$SHA256" in *[!0-9a-fA-F]*) err "invalid SHA-256 for $TARGET" ;; esac
    SHA256=$(printf '%s\n' "$SHA256" | awk '{print tolower($0)}')

    if command -v sha256sum >/dev/null 2>&1; then
        SHA256_TOOL=sha256sum
    elif command -v shasum >/dev/null 2>&1; then
        SHA256_TOOL=shasum
    elif command -v openssl >/dev/null 2>&1; then
        SHA256_TOOL=openssl
    else
        err "SHA-256 verification requires sha256sum, shasum, or openssl"
    fi

    if [ -n "${HERDR_INSTALL_DIR:-}" ]; then
        INSTALL_PATH="$HERDR_INSTALL_DIR/herdr"
    elif EXISTING=$(command -v herdr 2>/dev/null); then
        INSTALL_PATH=$EXISTING
    else
        INSTALL_PATH="$HOME/.local/bin/herdr"
    fi
    [ ! -d "$INSTALL_PATH" ] || err "install path is a directory: $INSTALL_PATH"
    INSTALL_DIR=$(dirname -- "$INSTALL_PATH")
    mkdir -p "$INSTALL_DIR"
    INSTALL_DIR=$(cd "$INSTALL_DIR" && pwd -P)
    INSTALL_PATH="$INSTALL_DIR/herdr"
    [ -w "$INSTALL_DIR" ] || err "install directory is not writable: $INSTALL_DIR"

    # Staging on the destination filesystem lets rename replace a running executable.
    TMP=$(mktemp "$INSTALL_DIR/.herdr.XXXXXXXX")
    log "downloading v$VERSION..."
    curl -fsSL --retry 3 --connect-timeout 10 --max-time 120 "$URL" -o "$TMP" \
        || err "download failed from $URL"
    case "$SHA256_TOOL" in
        sha256sum) ACTUAL_SHA256=$(sha256sum < "$TMP" | awk '{print $1}') ;;
        shasum) ACTUAL_SHA256=$(shasum -a 256 < "$TMP" | awk '{print $1}') ;;
        openssl) ACTUAL_SHA256=$(openssl dgst -sha256 < "$TMP" | awk '{print $NF}') ;;
    esac
    [ "$ACTUAL_SHA256" = "$SHA256" ] || err "SHA-256 mismatch; download was not installed"
    chmod 755 "$TMP"
    mv -f "$TMP" "$INSTALL_PATH"
    log "installed herdr v$VERSION to $INSTALL_PATH"
    case ":$PATH:" in
        *":$INSTALL_DIR:"*) ;;
        *) printf 'Add this to your shell config:\n  export PATH="%s:$PATH"\n' "$INSTALL_DIR" ;;
    esac
}

# Download extras/<name>/<files...> into a fresh directory and print its path.
fetch_extra() {
    name=$1
    shift
    [ -n "$EXTRAS_TMP" ] || EXTRAS_TMP=$(mktemp -d)
    mkdir -p "$EXTRAS_TMP/$name"
    for file in "$@"; do
        curl -fsSL --retry 3 --connect-timeout 10 --max-time 60 "$EXTRAS_URL/$name/$file" \
            -o "$EXTRAS_TMP/$name/$file" || err "cannot download $EXTRAS_URL/$name/$file"
    done
    printf '%s\n' "$EXTRAS_TMP/$name"
}

install_shell_count() {
    log "installing the shell-count watcher..."
    dir=$(fetch_extra shell-count install.sh herdr-shell-count.py herdr-shell-count.service \
        "$SHELL_COUNT_LABEL.plist")
    # Its installer looks herdr up on PATH, which may not include a fresh install dir yet.
    PATH="$INSTALL_DIR:$PATH" sh "$dir/install.sh"
}

install_asking() {
    log "installing the Claude Code asking hooks..."
    dir=$(fetch_extra claude-asking install.sh herdr-asking)
    sh "$dir/install.sh"
}

remove_shell_count() {
    case "$(uname -s)" in
        Linux)
            if command -v systemctl >/dev/null 2>&1; then
                systemctl --user disable --now herdr-shell-count.service >/dev/null 2>&1 || true
            fi
            rm -f "$HOME/.config/systemd/user/herdr-shell-count.service"
            if command -v systemctl >/dev/null 2>&1; then
                systemctl --user daemon-reload >/dev/null 2>&1 || true
            fi
            ;;
        Darwin)
            launchctl bootout "gui/$(id -u)/$SHELL_COUNT_LABEL" >/dev/null 2>&1 || true
            rm -f "$HOME/Library/LaunchAgents/$SHELL_COUNT_LABEL.plist"
            ;;
    esac
    rm -f "$SHELL_COUNT_BIN"
}

confirm() {
    [ "$YES" = 0 ] || return 0
    printf 'Continue? [y/N] ' >/dev/tty 2>/dev/null || err "no terminal to confirm on; rerun with --yes"
    answer=""
    read -r answer </dev/tty || true
    case "$answer" in
        y|Y|yes|YES) ;;
        *) err "cancelled; nothing was changed" ;;
    esac
}

uninstall() {
    # Stopping herdr from inside it would kill this very shell halfway through.
    [ "${HERDR_ENV:-}" != 1 ] || err "run --uninstall outside herdr (detach with Ctrl+b q first)"
    if [ -n "${HERDR_INSTALL_DIR:-}" ] && [ -e "$HERDR_INSTALL_DIR/herdr" ]; then
        HERDR="$HERDR_INSTALL_DIR/herdr"
    else
        HERDR=$(command -v herdr 2>/dev/null || true)
    fi
    CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/herdr"
    integrations=""
    sessions=""
    if [ -n "$HERDR" ]; then
        # Lines look like "claude: current (v11) (...)" or "pi: not installed (...)".
        integrations=$("$HERDR" integration status 2>/dev/null | awk -F': ' '
            NF > 1 && $2 !~ /^not installed/ { sub(/ \(.*$/, "", $1); printf "%s ", $1 }') || true
        sessions=$("$HERDR" session list --json 2>/dev/null | tr '{' '\n' | awk '
            /"running":true/ && match($0, /"name":"[^"]*"/) {
                printf "%s ", substr($0, RSTART + 8, RLENGTH - 9) }') || true
    fi
    asking=0
    [ ! -e "$ASKING_BIN" ] || asking=1
    watcher=0
    if [ -e "$SHELL_COUNT_BIN" ] || [ -e "$HOME/.config/systemd/user/herdr-shell-count.service" ] \
        || [ -e "$HOME/Library/LaunchAgents/$SHELL_COUNT_LABEL.plist" ]; then
        watcher=1
    fi
    purge=0
    if [ "$PURGE" = 1 ] && [ -e "$CONFIG_DIR" ]; then
        purge=1
    fi
    if [ -z "$HERDR" ] && [ "$watcher" = 0 ] && [ "$asking" = 0 ] && [ "$purge" = 0 ]; then
        log "herdr is not installed; nothing to remove"
        return 0
    fi

    echo "This will:"
    [ -z "$sessions" ] || echo "  - stop running herdr sessions (${sessions% }), closing all their panes and agents"
    [ -z "$integrations" ] || echo "  - remove herdr's agent integrations: ${integrations% }"
    [ "$watcher" = 0 ] || echo "  - remove the shell-count watcher"
    [ "$asking" = 0 ] || echo "  - remove the herdr-asking hooks from Claude Code's settings"
    [ -z "$HERDR" ] || echo "  - delete $HERDR"
    [ "$purge" = 0 ] || echo "  - delete $CONFIG_DIR (config, saved sessions, logs)"
    confirm

    for name in $integrations; do
        "$HERDR" integration uninstall "$name" >/dev/null 2>&1 \
            && log "removed the $name integration" || log "could not remove the $name integration"
    done
    if [ "$watcher" = 1 ]; then
        remove_shell_count
        log "removed the shell-count watcher"
    fi
    if [ "$asking" = 1 ]; then
        "$ASKING_BIN" uninstall >/dev/null 2>&1 \
            && log "removed the herdr-asking hooks" || log "could not remove the herdr-asking hooks"
    fi
    for session in $sessions; do
        "$HERDR" session stop "$session" >/dev/null 2>&1 \
            && log "stopped session $session" || log "could not stop session $session"
    done
    if [ -n "$HERDR" ]; then
        rm -f "$HERDR"
        log "deleted $HERDR"
    fi
    if [ "$purge" = 1 ]; then
        rm -rf "$CONFIG_DIR"
        log "deleted $CONFIG_DIR"
    elif [ -e "$CONFIG_DIR" ]; then
        log "kept $CONFIG_DIR (rerun with --uninstall --purge to delete it)"
    fi
}

WITH_SHELL_COUNT=0
WITH_ASKING=0
UNINSTALL=0
PURGE=0
YES=0
for argument in "$@"; do
    case "$argument" in
        --with-shell-count) WITH_SHELL_COUNT=1 ;;
        --with-asking) WITH_ASKING=1 ;;
        --uninstall) UNINSTALL=1 ;;
        --purge) PURGE=1 ;;
        --yes|-y) YES=1 ;;
        -h|--help) sed -n '2,18p' "$0" 2>/dev/null || true; exit 0 ;;
        *) err "unknown option: $argument" ;;
    esac
done
[ "$PURGE" = 0 ] || [ "$UNINSTALL" = 1 ] || err "--purge only works with --uninstall"
[ "$UNINSTALL" = 0 ] || [ "$WITH_SHELL_COUNT$WITH_ASKING" = 00 ] \
    || err "--with-shell-count and --with-asking can't be combined with --uninstall"

if [ "$UNINSTALL" = 1 ]; then
    uninstall
else
    install_herdr
    # Keep an installed watcher in step with the herdr it belongs to.
    if [ "$WITH_SHELL_COUNT" = 1 ] || [ -e "$SHELL_COUNT_BIN" ]; then
        install_shell_count
    fi
    if [ "$WITH_ASKING" = 1 ] || [ -e "$ASKING_BIN" ]; then
        install_asking
    fi
fi
