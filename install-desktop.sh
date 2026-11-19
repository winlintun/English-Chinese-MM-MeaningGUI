#!/usr/bin/env bash
# Install or remove the VocApp entry in the Linux applications menu.
# The entry runs vocapp.py from this repository through the local .env
# virtualenv, so code changes are picked up on the next launch.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_ID="vocapp"
DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
DESKTOP_DIR="$DATA_HOME/applications"
ICON_DIR="$DATA_HOME/icons/hicolor/256x256/apps"
ICON_SRC="$REPO_DIR/assets/icon.png"
DESKTOP_FILE="$DESKTOP_DIR/$APP_ID.desktop"

refresh_caches() {
    if command -v update-desktop-database >/dev/null 2>&1; then
        update-desktop-database "$DESKTOP_DIR" >/dev/null 2>&1 || true
    fi
    if command -v gtk-update-icon-cache >/dev/null 2>&1; then
        gtk-update-icon-cache -q -t "$DATA_HOME/icons/hicolor" >/dev/null 2>&1 || true
    fi
}

# .desktop Exec= has two escaping layers; reject paths that would need a
# fragile two-layer escape rather than emit a broken menu entry.
check_exec_path() {
    local path="$1" char
    for char in '\' '"' '$' '`' '%' $'\n'; do
        if [[ "$path" == *"$char"* ]]; then
            echo "error: path contains a character that cannot be used in a .desktop Exec line: $path" >&2
            exit 1
        fi
    done
    if [[ "$path" == " "* || "$path" == *" " ]]; then
        echo "error: path must not start or end with a space: $path" >&2
        exit 1
    fi
}

exec_arg() {
    printf '"%s"' "$1"
}

if [[ "${1:-}" == "--uninstall" ]]; then
    rm -f "$DESKTOP_FILE" "$ICON_DIR/$APP_ID.png"
    refresh_caches
    echo "Removed VocApp from the applications menu."
    exit 0
fi

if [[ ! -f "$ICON_SRC" ]]; then
    echo "error: missing icon at $ICON_SRC" >&2
    exit 1
fi

PYTHON="$REPO_DIR/.env/bin/python"
if [[ ! -x "$PYTHON" ]]; then
    echo "error: $PYTHON not found." >&2
    echo "Create the virtualenv first:" >&2
    echo "  python3 -m venv \"$REPO_DIR/.env\"" >&2
    echo "  \"$REPO_DIR/.env/bin/python\" -m pip install -r \"$REPO_DIR/requirements.txt\"" >&2
    exit 1
fi
if ! "$PYTHON" -c "import PySide6" >/dev/null 2>&1; then
    echo "error: PySide6 is not installed in $PYTHON." >&2
    echo "Run: \"$PYTHON\" -m pip install -r \"$REPO_DIR/requirements.txt\"" >&2
    exit 1
fi

SCRIPT_PATH="$REPO_DIR/vocapp.py"
check_exec_path "$PYTHON"
check_exec_path "$SCRIPT_PATH"

mkdir -p "$DESKTOP_DIR" "$ICON_DIR"
install -m 0644 "$ICON_SRC" "$ICON_DIR/$APP_ID.png"

cat > "$DESKTOP_FILE" <<DESKTOP_ENTRY
[Desktop Entry]
Type=Application
Version=1.0
Name=VocApp
Comment=English–Chinese–Myanmar vocabulary manager
Exec=$(exec_arg "$PYTHON") $(exec_arg "$SCRIPT_PATH")
Path=$REPO_DIR
Icon=$APP_ID
Terminal=false
Categories=Education;Languages;
StartupWMClass=VocApp
DESKTOP_ENTRY
chmod 0644 "$DESKTOP_FILE"

refresh_caches
echo "Installed $DESKTOP_FILE"
echo "VocApp now appears in the applications menu."
