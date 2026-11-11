#!/usr/bin/env bash
set -e

APP_NAME="x86-idg"
BIN_DIR="$HOME/.local/bin"
TARGET_BIN="$BIN_DIR/$APP_NAME"
DESKTOP_FILE="$HOME/.local/share/applications/$APP_NAME.desktop"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "==> Uninstalling $APP_NAME..."

# 1. Remove binary wrapper
if [ -f "$TARGET_BIN" ]; then
    rm -f "$TARGET_BIN"
    echo "  - Removed binary: $TARGET_BIN"
else
    echo "  - Binary not found at $TARGET_BIN"
fi

# 2. Remove desktop shortcut
if [ -f "$DESKTOP_FILE" ]; then
    rm -f "$DESKTOP_FILE"
    echo "  - Removed desktop entry: $DESKTOP_FILE"
fi

# 3. Optional cleanup of virtual environment
read -p "Do you also want to delete the project .venv directory? (y/N): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    if [ -d "$PROJECT_DIR/.venv" ]; then
        rm -rf "$PROJECT_DIR/.venv"
        echo "  - Removed .venv directory"
    fi
fi

echo "  Uninstallation complete!"
