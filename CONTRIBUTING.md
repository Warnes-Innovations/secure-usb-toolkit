# Contributing to Secure USB Toolkit

Thank you for your interest in contributing. This document describes the project's requirements, design constraints, and acceptance criteria so contributors can make changes with confidence.

---

## Development Setup

```bash
git clone https://github.com/Warnes-Innovations/secure-usb-toolkit.git
cd secure-usb-toolkit
python3 tui.py            # run the interactive wizard
python3 tui.py --help     # see all CLI subcommands
```

Dependencies: Python 3.8+, VeraCrypt, `parted`, `mkfs.vfat`, `mkfs.exfat` (Linux). `pyinstaller` is only needed to build distribution launchers (`python3 tui.py dist`).

---

## Repository Structure

```
secure-usb-toolkit/
├── tui.py                            # interactive TUI wizard and CLI entry point
├── launchers/
│   ├── SecureUSB.command             # macOS double-click launcher
│   ├── SecureUSB.sh                  # Linux launcher
│   └── SecureUSB.bat                 # Windows launcher
├── templates/
│   └── README.html                   # end-user instructions for TOOLS partition
└── dist/                             # generated build artifacts (git-ignored)
```

---

## Safety Requirements (Non-Negotiable)

The safety system exists to prevent accidental destruction of the operator's own disks. **Any change that weakens these guarantees will not be merged.**

Before any destructive disk operation, the code must:

1. Enumerate and display all available disks
2. Require the operator to type the full device path
3. Require the operator to type it a second time to confirm
4. Abort immediately on any mismatch

The disk safety functions in `tui.py` (`get_system_disks()` → `confirm_device()`) must additionally **block** the following without any prompt:

- The OS boot disk
- Any disk with `/`, `/boot`, or `/boot/efi` mounted (Linux)
- The disk identified by `diskutil info /` (macOS)

Do not bypass or weaken these checks.

---

## Security Requirements

- **No passwords stored anywhere** — not in config files, environment variables, logs, or command-line arguments. VeraCrypt must prompt for passwords interactively.
- **No silent writes** — every destructive operation must print a clear warning and require explicit confirmation.
- All user-supplied values passed to shell commands must be quoted with `shlex.quote()`.

---

## USB Partition Layout

| Partition | Filesystem | Purpose |
|---|---|---|
| 1 (TOOLS) | FAT32 | `README.html`, launchers — readable on all OSes without drivers |
| 2 (DATA)  | exFAT | `SECURE_DATA.vc` — the VeraCrypt container |

The TOOLS partition must remain unencrypted and cross-platform mountable so non-technical users can find `README.html` and the launchers without any special software.

---

## End-User Experience

Non-technical recipients of the USB must be able to:

1. Plug in the USB and open the TOOLS partition (auto-mounts on all OSes)
2. Open `README.html` in a browser — no installation needed
3. Follow plain-language instructions to install VeraCrypt and access their files

`templates/README.html` is the canonical end-user guide. Keep it non-technical, jargon-free, and tested across Windows, macOS, and Linux.

---

## Acceptance Criteria

### Disk safety (`tui.py`)
- `list_disks()` returns disk data on Linux, macOS, and Windows
- `print_disks()` produces human-readable output with system disks labelled `[SYSTEM — BLOCKED]`
- `confirm_device()` blocks system disks outright; requires double-typed confirmation for all others

### USB layout
- Creates two partitions: FAT32 (TOOLS) and exFAT (DATA)
- Cross-platform mountable result

### Encrypted container
- AES-256 minimum
- Password entered interactively by VeraCrypt — never passed as an argument or stored
- Container mounts on Windows, macOS, and Linux

### CLI / TUI (`tui.py`)
- Subcommands: `disks`, `usb`, `container`, `populate`, `clone`, `verify`, `dist`, `fetch-veracrypt`, `clean`
- All destructive subcommands call `confirm_device()` before acting
- Running with no arguments launches the interactive TUI wizard

### CI (`.github/workflows/build.yml`)
- Validates `tui.py` parses without errors
- Builds Linux launcher with PyInstaller
- Generates and uploads SHA-256 checksums as an artifact
- **No destructive disk operations in CI — ever**

### Cloning
- Bit-for-bit copy via `dd`
- Requires double-typed device confirmation before executing

### Verify
- Uses `hashlib.sha256` over all `dist/` files
- Handles empty `dist/` gracefully

---

## Potential Enhancements

If you want to work on something new, these areas are in scope:

- **Rich TUI** — replace the plain `print()`-based TUI with [`rich`](https://github.com/Textualize/rich) for colour, tables, and progress bars
- **Auto disk filtering** — automatically exclude disks below a size threshold or internal NVMe drives from the selectable list
- **GPG-signed releases** — sign the PyInstaller launcher artifacts at release time
- **Bootable ISO builder** — generate a bootable rescue ISO that includes the toolkit
- **GUI wrapper** — a minimal desktop GUI (e.g. Tkinter or a web view) for less technical operators
- **Windows partition support** — `_create_usb_layout()` currently targets Linux and macOS; a Windows-native path using `diskpart` would improve cross-platform coverage

For any enhancement that touches disk operations, the safety requirements above apply without exception.

---

## Submitting Changes

1. Fork the repository and create a feature branch
2. Ensure `python3 -c "import ast; ast.parse(open('tui.py').read())"` passes
3. Ensure `python3 -c "from build import safety"` imports cleanly
4. Ensure CI passes before requesting a review
5. Document any new `Makefile` targets in this file and in `README.md`
