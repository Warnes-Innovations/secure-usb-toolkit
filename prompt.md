# 🔐 Secure USB Toolkit — Agent Handoff Prompt

## 1. Objective

Build a **Secure USB Toolkit** for provisioning encrypted USB drives using VeraCrypt with:

- Dual-partition USB layout
- Cross-platform support (Windows / macOS / Linux)
- Interactive CLI + TUI
- Safety system preventing accidental disk destruction
- Reproducible build + cloning system
- GitHub Actions CI validation

---

## 2. System Requirements

### Core Capabilities

- Create USB partitions:
  - Partition 1: tools + instructions (unencrypted)
  - Partition 2: encrypted VeraCrypt container
- Create and manage VeraCrypt containers
- Clone USB devices reproducibly
- Verify integrity via checksums
- Provide CLI + TUI interfaces

---

## 3. Critical Safety Requirements

### MUST IMPLEMENT SAFETY LAYER

Before any destructive operation:

#### Required steps:
1. Enumerate disks
2. Display full disk list
3. Require typed device selection
4. Require repeated confirmation
5. Abort on mismatch

#### MUST BLOCK:
- System disk
- Boot disk
- Root volume
- Primary NVMe OS disk (unless explicit override)

---

## 4. Repository Structure

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

---

## 5. CLI Specification

### Entry Point
```bash
python cli.py
````

### Required features:

* Create USB layout
* Create encrypted container
* Populate tools partition
* Clone USB
* Verify build

---

## 6. TUI Specification

### Entry Point

```bash
python tui.py
```

### Menu:

1. List disks
2. Create USB layout
3. Create encrypted container
4. Populate tools partition
5. Clone USB
6. Verify
7. Exit

### Requirements:

* Keyboard-driven interface
* Uses safety module
* Must display warnings before destructive operations

---

## 7. Encryption Layer

Use VeraCrypt:

```bash
veracrypt --create SECURE_DATA.vc \
  --size <SIZE> \
  --encryption AES \
  --filesystem exfat
```

### Requirements:

* AES-256 minimum
* Cross-platform mountability
* CLI + GUI support

---

## 8. Build System

### Makefile targets:

* `tui`
* `container`
* `usb`
* `populate`
* `clone`
* `verify`

---

## 9. Safety Module (`build/safety.py`)

### Required functions:

* `list_disks()`
* `print_disks()`
* `confirm_device(device)`

### Responsibilities:

* OS-specific disk enumeration
* System disk detection prevention
* Double confirmation enforcement

---

## 10. Cloning System

### Supported methods:

* Linux/macOS: `dd`
* Windows: imaging fallback (optional)

### Requirements:

* Bit-for-bit replication
* Verified integrity after clone

---

## 11. CI/CD Requirements (GitHub Actions)

Pipeline must:

* Install dependencies
* Validate scripts
* Build test container safely
* Generate checksums
* Upload artifacts

### Restrictions:

* NO destructive operations in CI

---

## 12. Documentation Requirements

Must include:

* README.md (user-facing)
* Security model
* Architecture overview
* Usage guide

---

## 13. Security Model

* VeraCrypt is encryption boundary
* No plaintext sensitive data stored on tools partition
* Explicit user warnings required for all disk operations
* No silent writes to system disks

---

## 14. End-to-End Validation

System is complete when:

1. Disk enumeration works safely
2. USB layout creation works
3. Container creation works
4. Tools partition populated
5. Container mounts cross-platform
6. USB cloning works
7. CI pipeline passes

---

## 15. Optional Enhancements

* Rich-based TUI upgrade
* Device auto-filtering logic
* GPG signed releases
* Bootable ISO builder
* GUI wrapper

---

## 16. Completion Criteria

Project is complete when:

* CLI + TUI fully functional
* Safety layer prevents disk misuse
* Cross-platform encryption verified
* Cloning system reliable
* CI pipeline green
* Documentation ready for public release

