#!/usr/bin/env bash
# macOS double-click launcher
# Place this file on the TOOLS partition. Users double-click it to open the TUI.
# Requires Python 3 (pre-installed on macOS 10.15+).

cd "$(dirname "$0")/../.." || exit 1

if ! command -v python3 &>/dev/null; then
    osascript -e 'display alert "Python 3 Required" message "Please install Python 3 from https://www.python.org/downloads/"'
    exit 1
fi

python3 tui.py
