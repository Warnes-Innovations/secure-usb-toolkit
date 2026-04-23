# 🔐 Secure USB Toolkit — Spec-Driven Development Checklist

## 0. Project Definition

### Goal
Build a cross-platform encrypted USB provisioning system using VeraCrypt with:

- Dual-partition USB layout
- Interactive CLI + TUI
- Safety-guarded disk operations
- Reproducible build + cloning system
- CI validation via GitHub Actions

---

# 1. System Architecture Specification

## 1.1 Repository Structure (MUST MATCH)

```

secure-usb-toolkit/
├── build/
│   ├── create_usb_layout.sh
│   ├── create_container.sh
│   ├── clone_usb.sh
│   ├── verify.sh
│   └── safety.py
│
├── cli.py
├── tui.py
├── Makefile
├── README.md
├── dist/
├── templates/
└── .github/workflows/build.yml

````

### ✔ Acceptance Criteria
- Repo matches structure exactly
- All scripts executable where applicable
- No missing entry points

---

# 2. USB Layout Specification

## 2.1 Partition Requirements

### Partition 1 (TOOLS)
- FAT32 or exFAT
- Contains:
  - README.html
  - CLI/TUI launchers
  - Optional VeraCrypt binaries

### Partition 2 (DATA)
- exFAT-compatible storage
- Contains:
  - `SECURE_DATA.vc`

### ✔ Acceptance Criteria
- Two partitions created correctly
- Cross-platform mountable

---

# 3. Encryption Layer Specification

## VeraCrypt Container

AES-256 minimum.

```bash
veracrypt --create SECURE_DATA.vc \
  --size <SIZE> \
  --encryption AES \
  --filesystem exfat
````

### ✔ Acceptance Criteria

* Container mounts on multiple OSs
* Data persists correctly

---

# 4. Safety System Specification (CRITICAL)

## Disk Enumeration

| OS      | Method         |
| ------- | -------------- |
| Linux   | lsblk -J       |
| macOS   | diskutil list  |
| Windows | wmic diskdrive |

---

## MUST BLOCK:

* System disk
* Boot disk
* Root volumes
* Primary NVMe OS drive (unless override enabled)

---

## Confirmation Protocol

Before destructive actions:

1. Display disks
2. Require typed device path
3. Require repeated confirmation
4. Abort on mismatch

### ✔ Acceptance Criteria

* No action without double confirmation
* System disks cannot be selected

---

# 5. CLI Specification

## Entry Point

```bash
python cli.py
```

## Features

* USB layout creation
* Container creation
* Populate tools partition
* Clone USB
* Verify integrity

### ✔ Acceptance Criteria

* Fully functional CLI
* Safety enforced

---

# 6. TUI Specification

## Entry Point

```bash
python tui.py
```

## Menu

1. List disks
2. Create USB layout
3. Create encrypted container
4. Populate tools partition
5. Clone USB
6. Verify
7. Exit

### UX Requirements

* Keyboard-driven
* Warning before destructive actions
* Uses safety module

### ✔ Acceptance Criteria

* All operations functional
* No bypass of safety layer

---

# 7. Build System Specification

## Makefile Targets

* tui
* container
* usb
* populate
* clone
* verify

### ✔ Acceptance Criteria

* All targets execute cleanly
* No unsafe defaults

---

# 8. Safety Module Specification

## File: build/safety.py

### Required Functions

* list_disks()
* print_disks()
* confirm_device(device)

### ✔ Acceptance Criteria

* Cross-platform support
* Prevents accidental system disk selection

---

# 9. Cloning System Specification

## Method

* Linux/macOS: dd
* Windows: imaging fallback (optional)

### ✔ Acceptance Criteria

* Bit-for-bit clone supported
* Verified integrity after clone

---

# 10. CI/CD Specification

## GitHub Actions Must:

* Install dependencies
* Validate scripts
* Build test container
* Generate checksums
* Upload artifacts

### ✔ Acceptance Criteria

* CI passes on clean runner
* No destructive operations in CI

---

# 11. Documentation Specification

## Required Docs

* README.md
* Security model
* Architecture overview
* Usage guide

### ✔ Acceptance Criteria

* Non-technical user can follow setup
* Security assumptions clearly stated

---

# 12. Security Model

* VeraCrypt is trust boundary
* No plaintext sensitive data stored
* Explicit user warnings required
* No silent disk writes

### ✔ Acceptance Criteria

* Threat model documented
* No hidden destructive behavior

---

# 13. End-to-End Validation

System must:

1. List disks safely
2. Create USB layout
3. Create encrypted container
4. Populate tools partition
5. Mount container cross-platform
6. Clone USB
7. Pass CI build

---

# 14. Optional Enhancements

* Rich TUI upgrade
* Auto disk filtering
* GPG signing
* Bootable ISO builder
* GUI wrapper

---

# 15. Completion Definition

Project is COMPLETE when:

* CLI + TUI fully functional
* Safety layer enforced
* Cross-platform encryption verified
* Cloning works reliably
* CI pipeline green
* Documentation is publishable
