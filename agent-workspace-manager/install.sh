#!/bin/bash
# install.sh - Install agent-workspace-manager ws commands to ~/.local/bin
# Generates wrapper scripts with hardcoded Python script path
# Usage: bash install.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="$HOME/.local/bin"
PYTHON_SCRIPT="$SCRIPT_DIR/scripts/workspace_manager.py"

mkdir -p "$BIN_DIR"

# Verify python script exists
if [ ! -f "$PYTHON_SCRIPT" ]; then
    echo "ERROR: workspace_manager.py not found at $PYTHON_SCRIPT"
    exit 1
fi

# Remove old files/symlinks first
rm -f "$BIN_DIR/ws" "$BIN_DIR/wscreate" "$BIN_DIR/wslist" "$BIN_DIR/wsopen" "$BIN_DIR/wsdelete"

# Generate ws dispatcher
printf '#!/bin/bash\nPYTHON_SCRIPT="%s"\ncase "${1:-}" in\n    create) shift; exec python3 "$PYTHON_SCRIPT" create "$@" ;;\n    list)   shift; exec python3 "$PYTHON_SCRIPT" list "$@" ;;\n    open)   shift; exec python3 "$PYTHON_SCRIPT" open "$@" ;;\n    delete) shift; exec python3 "$PYTHON_SCRIPT" delete "$@" ;;\n    "")\n        echo "Usage: ws {create|list|open|delete} [args]"\n        echo "  ws create [branch-name]              Create workspace (default: master)"\n        echo "  ws list [--project PROJECT]          List workspaces"\n        echo "  ws open --name NAME [--project P]    Open in IDEA"\n        echo "  ws delete --name NAME [--project P]  Delete (branch preserved)"\n        echo "Aliases: wscreate, wslist, wsopen, wsdelete"\n        exit 1 ;;\n    *) echo "Unknown: $1"; exit 1 ;;\nesac\n' "$PYTHON_SCRIPT" > "$BIN_DIR/ws"
chmod +x "$BIN_DIR/ws"

# Generate alias wrappers
for cmd in create list open delete; do
    printf '#!/bin/bash\nexec python3 "%s" %s "$@"\n' "$PYTHON_SCRIPT" "$cmd" > "$BIN_DIR/ws${cmd}"
    chmod +x "$BIN_DIR/ws${cmd}"
done

echo "Installed to $BIN_DIR:"
echo "  ws, wscreate, wslist, wsopen, wsdelete"
echo "  Python script: $PYTHON_SCRIPT"

# Check if BIN_DIR is in PATH
case ":$PATH:" in
    *":$BIN_DIR:"*)
        echo "PATH OK"
        ;;
    *)
        echo ""
        echo "WARNING: $BIN_DIR is not in your PATH."
        echo "Add this to your shell profile:"
        echo "  export PATH=\"$BIN_DIR:\$PATH\""
        ;;
esac
