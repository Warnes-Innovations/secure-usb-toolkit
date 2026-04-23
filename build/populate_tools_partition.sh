#!/usr/bin/env bash
set -euo pipefail

MOUNT="${1:?Usage: $0 <mount-path>}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

if [ ! -d "$REPO_ROOT/dist" ] || [ -z "$(ls -A "$REPO_ROOT/dist" 2>/dev/null)" ]; then
    echo "[!] dist/ is empty. Run 'make dist' first to build launchers."
    exit 1
fi

echo "[*] Copying tools to $MOUNT..."
cp -r "$REPO_ROOT/dist/"* "$MOUNT/"
cp "$REPO_ROOT/templates/README.html" "$MOUNT/README.html"

echo "[+] Tools partition populated."
echo "    Users should open README.html to get started."
