# 🔐 Secure USB Toolkit

Reproducible cross-platform encrypted USB provisioning using VeraCrypt.

## Features

- Dual-partition USB layout — unencrypted TOOLS partition + encrypted DATA partition
- AES-256 VeraCrypt container
- Cross-platform: Windows, macOS, Linux
- Safety layer that detects and blocks system/boot disk selection
- Double-typed device confirmation before any destructive operation
- Reproducible cloning and SHA-256 integrity verification
- Interactive TUI and scriptable CLI
- End-user `README.html` placed on the TOOLS partition for non-technical recipients

---

## Requirements

| Dependency | Purpose |
|---|---|
| Python 3.8+ | TUI / CLI / safety module |
| [VeraCrypt](https://www.veracrypt.fr/en/Downloads.html) | Container creation and mounting |
| [FUSE-T](https://www.fuse-t.org/) | Required on macOS for VeraCrypt to mount containers (works on Intel and Apple Silicon) |
| `parted` | USB partition layout (Linux) |
| `mkfs.vfat`, `mkfs.exfat` | Partition formatting (Linux) |
| `pyinstaller` | Build Windows/Linux launcher exe (optional) |

---

## Quick Start

```bash
# Launch the interactive TUI wizard
python3 tui.py

# Or use the CLI directly
python3 tui.py disks                        # list available disks
python3 tui.py usb /dev/sdb                 # partition and format USB
python3 tui.py container --size 5G          # create encrypted container
python3 tui.py populate /mnt/tools          # copy launchers + README to TOOLS partition
python3 tui.py clone /dev/sdb /dev/sdc      # bit-for-bit clone
python3 tui.py verify                       # checksum everything in dist/
python3 tui.py dist                         # build PyInstaller launcher into dist/
python3 tui.py fetch-veracrypt              # download Windows VeraCrypt installer
```

### Provisioning workflow (full USB from scratch)

```bash
python3 tui.py               # interactive wizard walks through all steps

# Or step-by-step via CLI:
python3 tui.py fetch-veracrypt              # download + verify VeraCrypt Windows installer
python3 tui.py usb /dev/sdb                 # partition and format the USB
python3 tui.py container                    # create SECURE_DATA.vc (you choose the password)
python3 tui.py dist                         # build platform launchers
python3 tui.py populate /mnt/tools          # copy launchers, README.html, and VeraCrypt to USB
python3 tui.py verify                       # checksum everything in dist/
```

---

## End-User Experience

Non-technical recipients receive a USB with:

- **Partition 1 (FAT32 — TOOLS):** `README.html` with step-by-step instructions, a bundled VeraCrypt Windows installer, and platform launchers (`SecureUSB.command` for macOS, `SecureUSB.bat` for Windows, `SecureUSB.sh` for Linux).
- **Partition 2 (exFAT — DATA):** `SECURE_DATA.vc` — the AES-256 encrypted VeraCrypt container.

**Windows users** double-click `SecureUSB.bat` → `README.html` opens in their browser → they run the bundled `VeraCrypt/VeraCrypt Setup 1.26.24.exe` → mount `SECURE_DATA.vc`. No internet connection required.

**macOS users** open `README.html` and follow the instructions to install [FUSE-T](https://www.fuse-t.org/) and then the VeraCrypt FUSE-T build. Both are required — VeraCrypt uses FUSE-T to mount containers on macOS.

**Linux users** open `README.html` and follow the instructions to install VeraCrypt from the official site.

> **Note:** Windows USB _provisioning_ (creating layouts, containers, cloning) currently requires Linux or macOS. See the GitHub issue tracker for the Windows provisioning roadmap.

---

## Safety Model

All destructive disk operations require:

1. An explicit disk listing so the operator can verify the target
2. The operator to type the full device path (e.g. `/dev/sdb`)
3. The operator to type it a second time to confirm
4. Automatic detection and hard-blocking of system disks, boot volumes, and root partitions

System disk detection is OS-aware:
- **Linux:** inspects `lsblk` mount points for `/`, `/boot`, `/boot/efi`
- **macOS:** queries `diskutil info /` to identify the boot disk

---

## Security Model

- VeraCrypt is the encryption boundary (AES-256, minimum)
- **No passwords are ever stored** — the operator is prompted interactively at container creation time, and the end user enters their password into VeraCrypt at mount time
- No plaintext sensitive data on the TOOLS partition
- No silent writes to any disk — all destructive operations require explicit confirmation
- VeraCrypt containers use PIM 0 and `/dev/urandom` as entropy source

---

## Architecture

```
tui.py                          — Interactive TUI wizard and scriptable CLI

launchers/
  SecureUSB.command             — macOS double-click launcher (goes on TOOLS partition)
  SecureUSB.sh                  — Linux launcher
  SecureUSB.bat                 — Windows launcher

templates/
  README.html                   — End-user instructions (placed on TOOLS partition)

dist/                           — Built artifacts (generated by tui.py dist, git-ignored)
```

---

## CI Pipeline

GitHub Actions (`.github/workflows/build.yml`) on every push:

1. Validates `tui.py` parses without errors
2. Builds the Linux launcher with PyInstaller
3. Generates SHA-256 checksums
4. Uploads the launcher as a build artifact

No destructive disk operations are performed in CI.

