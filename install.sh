#!/usr/bin/env bash
set -e

APP_NAME="x86-idg"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="$HOME/.local/bin"
TARGET_BIN="$BIN_DIR/$APP_NAME"
DESKTOP_DIR="$HOME/.local/share/applications"
DESKTOP_FILE="$DESKTOP_DIR/$APP_NAME.desktop"

# Package manager variable: defaults to "pip", can be overridden (e.g., PKG_MGR=uv ./install.sh)
PKG_MGR="${PKG_MGR:-pip}"

echo "==> Installing $APP_NAME using $PKG_MGR from $PROJECT_DIR..."

cd "$PROJECT_DIR"

# 1. Setup virtual environment and sync dependencies
if [ "$PKG_MGR" = "uv" ]; then
    if ! command -v uv &> /dev/null; then
        echo "Error: 'uv' is not installed or not in PATH." >&2
        exit 1
    fi
    echo "==> Syncing project dependencies with uv..."
    uv sync
else
    if ! command -v python3 &> /dev/null; then
        echo "Error: 'python3' is not installed or not in PATH." >&2
        exit 1
    fi
    if [ ! -d ".venv" ]; then
        echo "==> Creating virtual environment in .venv..."
        python3 -m venv .venv
    fi
    echo "==> Installing dependencies with pip..."
    if [ -f "pyproject.toml" ]; then
        .venv/bin/pip install -e .
    elif [ -f "requirements.txt" ]; then
        .venv/bin/pip install -r requirements.txt
    fi
fi

# 2. Create target bin directory if missing
mkdir -p "$BIN_DIR"

# 3. Create wrapper executable calling runner.py via virtualenv python
echo "==> Creating wrapper binary at $TARGET_BIN..."
cat << EOF > "$TARGET_BIN"
#!/usr/bin/env bash
cd "$PROJECT_DIR"
exec "$PROJECT_DIR/.venv/bin/python" runner.py "\$@"
EOF

chmod +x "$TARGET_BIN"

# 4. Create Desktop Application entry
mkdir -p "$DESKTOP_DIR"
cat << EOF > "$DESKTOP_FILE"
[Desktop Entry]
Type=Application
Name=x86-64 Debugger & Interpreter
Exec=$TARGET_BIN -d
Terminal=true
Categories=Development;Debugger;
EOF

chmod +x "$DESKTOP_FILE"

# 5. Check PATH
if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
    echo "  Warning: $BIN_DIR is not in your \$PATH."
    echo "   Add 'fish_add_path ~/.local/bin' (Fish) or 'export PATH=\"\$HOME/.local/bin:\$PATH\"' (Bash/Zsh) to your shell config."
fi

echo " Installation complete! Run '$APP_NAME [file.asm] [-d]' from anywhere."
