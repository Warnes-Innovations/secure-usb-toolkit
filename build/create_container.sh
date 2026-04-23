#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/../templates/container_config.env"

echo "[*] Creating VeraCrypt container: $OUTPUT_CONTAINER ($SIZE)"
echo "    You will be prompted to enter and verify a password."
echo

# Password is entered interactively by VeraCrypt — never stored or logged.
veracrypt --text --create "$OUTPUT_CONTAINER" \
  --size "$SIZE" \
  --encryption AES \
  --filesystem exfat \
  --pim 0 \
  --random-source /dev/urandom

echo
echo "[+] Container created: $OUTPUT_CONTAINER"
