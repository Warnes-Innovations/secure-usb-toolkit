#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DIST_DIR="$SCRIPT_DIR/../dist"

if [ ! -d "$DIST_DIR" ] || [ -z "$(ls -A "$DIST_DIR" 2>/dev/null)" ]; then
    echo "[!] dist/ is empty — nothing to verify. Run 'make dist' first."
    exit 0
fi

cd "$DIST_DIR"

# sha256sum on Linux, shasum on macOS
if command -v sha256sum &>/dev/null; then
    SHA_CMD="sha256sum"
else
    SHA_CMD="shasum -a 256"
fi

echo "[*] Generating checksums..."
find . -type f ! -name 'checksums.txt' | sort | xargs $SHA_CMD > checksums.txt

echo "[*] Verifying..."
$SHA_CMD -c checksums.txt
echo "[+] Integrity verified."
