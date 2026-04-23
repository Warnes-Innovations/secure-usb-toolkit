#!/usr/bin/env bash
set -euo pipefail

DEVICE="${1:?Usage: $0 <device>}"

echo
echo "  Target device : $DEVICE"
echo "  Partition 1   : FAT32  (TOOLS — unencrypted, ~1 GiB)"
echo "  Partition 2   : exFAT  (DATA  — VeraCrypt container)"
echo
echo "  WARNING: ALL DATA ON $DEVICE WILL BE PERMANENTLY ERASED."
echo
read -rp "  Type YES to proceed: " confirm
[ "$confirm" = "YES" ] || { echo "  Aborted."; exit 1; }

echo "[*] Creating partition table..."
parted "$DEVICE" --script mklabel msdos
parted "$DEVICE" --script mkpart primary fat32 1MiB 1024MiB
parted "$DEVICE" --script mkpart primary exfat 1024MiB 100%

echo "[*] Formatting partitions..."
mkfs.vfat -F32 "${DEVICE}1"
mkfs.exfat "${DEVICE}2"

echo
echo "[+] USB layout created."
echo "    Partition 1 (FAT32 / TOOLS) : ${DEVICE}1"
echo "    Partition 2 (exFAT / DATA)  : ${DEVICE}2"
