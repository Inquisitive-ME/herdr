#!/bin/sh
# Adapted from herdrdev/herdr's Apache-2.0 distribution/install.sh.
set -eu

MANIFEST_URL="https://github.com/Inquisitive-ME/herdr/releases/latest/download/latest.json"

log() { printf '  > %s\n' "$1"; }
err() { printf 'error: %s\n' "$1" >&2; exit 1; }
need() { command -v "$1" >/dev/null 2>&1 || err "requires '$1'"; }

main() {
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
    [ -n "$URL" ] || err "manifest has no asset for $TARGET"
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
    trap 'rm -f "$TMP"' 0
    trap 'exit 1' HUP INT TERM
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

main "$@"
