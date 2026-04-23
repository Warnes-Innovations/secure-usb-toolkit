#!/usr/bin/env bash
# Linux launcher
# Run from a terminal: bash SecureUSB.sh
# Requires Python 3 (standard on all modern Linux distros).

cd "$(dirname "$0")/../.." || exit 1

if ! command -v python3 &>/dev/null; then
    echo "Error: python3 not found. Install it with your package manager."
    echo "  Ubuntu/Debian: sudo apt install python3"
    echo "  Fedora:        sudo dnf install python3"
    exit 1
fi

python3 tui.py
