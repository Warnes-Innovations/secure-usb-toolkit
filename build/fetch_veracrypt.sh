#!/usr/bin/env bash
# Downloads the current VeraCrypt Windows installer into dist/VeraCrypt/
# and verifies its SHA-256 checksum against the official checksum file.
#
# To update to a new VeraCrypt release, change VERACRYPT_VERSION below.
set -euo pipefail

VERACRYPT_VERSION="1.26.24"
BASE_URL="https://launchpad.net/veracrypt/trunk/${VERACRYPT_VERSION}/+download"
INSTALLER_FILE="VeraCrypt Setup ${VERACRYPT_VERSION}.exe"
INSTALLER_URL="${BASE_URL}/VeraCrypt%20Setup%20${VERACRYPT_VERSION}.exe"
CHECKSUM_URL="${BASE_URL}/veracrypt-${VERACRYPT_VERSION}-sha256sum.txt"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DEST_DIR="$SCRIPT_DIR/../dist/VeraCrypt"

mkdir -p "$DEST_DIR"

echo
echo "[*] VeraCrypt ${VERACRYPT_VERSION} — Windows installer"
echo "    Destination: $DEST_DIR"
echo

echo "[*] Downloading installer..."
curl -L --progress-bar \
    -o "$DEST_DIR/${INSTALLER_FILE}" \
    "$INSTALLER_URL"

echo "[*] Downloading official SHA-256 checksums..."
curl -L --silent \
    -o "$DEST_DIR/sha256sums.txt" \
    "$CHECKSUM_URL"

echo "[*] Verifying checksum..."
cd "$DEST_DIR"

EXPECTED_HASH=$(grep -i "VeraCrypt Setup ${VERACRYPT_VERSION}.exe" sha256sums.txt | awk '{print $1}')
if [ -z "$EXPECTED_HASH" ]; then
    echo
    echo "[!] ERROR: Could not find checksum entry for '${INSTALLER_FILE}'."
    echo "    The checksum file contents:"
    cat sha256sums.txt
    rm -f "${INSTALLER_FILE}"
    exit 1
fi

if command -v sha256sum &>/dev/null; then
    ACTUAL_HASH=$(sha256sum "${INSTALLER_FILE}" | awk '{print $1}')
else
    ACTUAL_HASH=$(shasum -a 256 "${INSTALLER_FILE}" | awk '{print $1}')
fi

if [ "$ACTUAL_HASH" = "$EXPECTED_HASH" ]; then
    echo "[+] Checksum OK: ${INSTALLER_FILE}"
else
    echo
    echo "[!] ERROR: Checksum MISMATCH — installer may be corrupt or tampered with."
    echo "    Expected : $EXPECTED_HASH"
    echo "    Actual   : $ACTUAL_HASH"
    rm -f "${INSTALLER_FILE}"
    exit 1
fi

echo
echo "[+] Done. VeraCrypt ${VERACRYPT_VERSION} Windows installer is ready."
echo "    Location : $DEST_DIR/${INSTALLER_FILE}"
echo "    Run 'make populate MOUNT=<path>' to copy it to the USB TOOLS partition."
echo
