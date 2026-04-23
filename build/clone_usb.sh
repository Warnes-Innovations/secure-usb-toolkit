#!/usr/bin/env bash
set -euo pipefail

SOURCE="${1:?Usage: $0 <source> <target>}"
TARGET="${2:?Usage: $0 <source> <target>}"

echo
echo "  Cloning : $SOURCE  →  $TARGET"
echo "  WARNING : ALL DATA ON $TARGET WILL BE OVERWRITTEN."
echo
read -rp "  Type YES to proceed: " confirm
[ "$confirm" = "YES" ] || { echo "  Aborted."; exit 1; }

echo "[*] Starting clone..."
dd if="$SOURCE" of="$TARGET" bs=4M status=progress conv=fsync
echo
echo "[+] Clone complete."
