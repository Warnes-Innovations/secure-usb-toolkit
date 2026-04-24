from build import safety
import subprocess
import shlex
import sys
import os
import zipfile
import shutil
import platform
from pathlib import Path

REPO_ROOT = Path(__file__).parent
DIST_DIR = REPO_ROOT / "dist"
CONTAINER_PATH = REPO_ROOT / "output.vc"
STAGING_ZIP = REPO_ROOT / "staging.zip"

# ── Terminal styling ──────────────────────────────────────────────────────────

_COLOR = sys.stdout.isatty()

def _ansi(code, text): return f"\033[{code}m{text}\033[0m" if _COLOR else text
def bold(t):   return _ansi("1", t)
def dim(t):    return _ansi("2", t)
def green(t):  return _ansi("32", t)
def red(t):    return _ansi("31", t)
def yellow(t): return _ansi("33", t)

def log(msg):  print(dim(f"    {msg}"))
def ok(msg):   print(green(f"  ✓  {msg}"))
def err(msg):  print(red(f"  ✗  {msg}"), file=sys.stderr)
def warn(msg): print(yellow(f"  !  {msg}"))


# ── Input helpers (all handle Ctrl-C gracefully) ──────────────────────────────

def _read(styled_prompt):
    try:
        return input(styled_prompt).strip()
    except KeyboardInterrupt:
        print()
        print(yellow("\n  Interrupted — exiting."))
        sys.exit(1)


def prompt(msg, default=None):
    suffix = dim(f" [{default}]") if default is not None else ""
    val = _read(bold(f"\n  ▶  {msg}") + suffix + bold(": "))
    return val if val else default


def prompt_required(msg):
    while True:
        val = _read(bold(f"\n  ▶  {msg}: "))
        if val:
            return val
        err("A value is required.")


def confirm(msg, default_yes=True):
    hint = dim(" [Y/n]" if default_yes else " [y/N]")
    ans = _read(bold(f"\n  ▶  {msg}") + hint + bold(": ")).lower()
    return (ans in ("y", "yes")) if ans else default_yes


def wait(msg="Press Enter to continue"):
    _read(bold(f"\n  ▶  {msg}... "))


# ── Collapsible output box ────────────────────────────────────────────────────

def _show_output_box(text, title="Output"):
    cols = shutil.get_terminal_size((80, 24)).columns
    width = min(cols - 4, 100)
    rule = dim("  " + "─" * (width - 2))
    print()
    print(dim(f"  ┬─ {title}"))
    print(rule)
    for line in text.splitlines():
        display = line if len(line) <= width - 4 else line[:width - 7] + "..."
        print(dim(f"  │ {display}"))
    print(rule)
    print()


def run_quiet(cmd, label):
    """Run a non-interactive command. Capture output; offer to expand on success."""
    log(f"{label} ...")
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    combined = (result.stdout + result.stderr).strip()
    n = len(combined.splitlines()) if combined else 0

    if result.returncode != 0:
        err(f"{label}  — failed")
        if combined:
            _show_output_box(combined, "Error output")
        raise subprocess.CalledProcessError(result.returncode, cmd)

    ok(label)
    if n > 0:
        ans = _read(dim(f"      ({n} lines of output — s to show, Enter to skip): "))
        if ans.lower() == "s":
            _show_output_box(combined, label)


def run(cmd):
    """Run an interactive command — output passes straight through."""
    subprocess.run(cmd, shell=True, check=True)


# ── Section headers ───────────────────────────────────────────────────────────

def banner():
    print()
    print(bold("  ╔═══════════════════════════════════════╗"))
    print(bold("  ║      SECURE USB TOOLKIT — Wizard      ║"))
    print(bold("  ╚═══════════════════════════════════════╝"))


def phase_header(phase, title):
    cols = shutil.get_terminal_size((80, 24)).columns
    rule = bold("  " + "━" * min(cols - 4, 60))
    print()
    print(rule)
    print(bold(f"  Phase {phase}:  {title}"))
    print(rule)


def step_header(n, total, title):
    print()
    print(bold(f"  Step {n}/{total}  —  {title}"))
    print(dim("  " + "·" * 38))


# ── Pre-flight checks ─────────────────────────────────────────────────────────

def check_prerequisites():
    """Verify all required external tools are present before any user interaction."""
    os_name = platform.system()

    # (tool, install hint per OS)
    checks = [
        ("veracrypt", {
            "Darwin": "brew install --cask veracrypt   or   https://veracrypt.io/en/Downloads.html",
            "Linux":  "https://veracrypt.io/en/Downloads.html",
        }),
    ]
    if os_name == "Linux":
        checks += [
            ("parted",     {"Linux": "sudo apt install parted              / sudo dnf install parted"}),
            ("mkfs.vfat",  {"Linux": "sudo apt install dosfstools          / sudo dnf install dosfstools"}),
            ("mkfs.exfat", {"Linux": "sudo apt install exfatprogs          / sudo dnf install exfatprogs"}),
        ]

    missing = [
        (tool, hints.get(os_name, "see https://veracrypt.io"))
        for tool, hints in checks
        if shutil.which(tool) is None
    ]

    if not missing:
        return

    print()
    err("Required tools are not installed. Install them, then re-run the wizard:")
    print()
    for tool, hint in missing:
        print(bold(f"    {tool}"))
        print(dim(f"      {hint}"))
    print()
    sys.exit(1)


# ── Phase 1: Build artifacts ──────────────────────────────────────────────────

def phase_build():
    phase_header("1 of 2", "Build artifacts  (done once per batch)")
    log("Launchers, the VeraCrypt installer, and the encrypted container are")
    log("built here. Every USB drive in Phase 2 receives a copy of these artifacts.")

    # Step 1 — Launchers
    step_header(1, 5, "Build launchers")
    if any(DIST_DIR.glob("SecureUSB*")):
        ok("Launchers already present in dist/")
    else:
        run_quiet("make dist", "Build PyInstaller launchers")

    # Step 2 — VeraCrypt Windows installer
    step_header(2, 5, "VeraCrypt Windows installer")
    vc_dir = DIST_DIR / "VeraCrypt"
    if vc_dir.exists() and any(vc_dir.glob("*.exe")):
        ok("VeraCrypt installer already in dist/VeraCrypt/")
    else:
        if confirm("Download VeraCrypt installer for Windows users?"):
            run_quiet("make fetch-veracrypt", "Fetch VeraCrypt installer")
        else:
            warn("Skipped — Windows users will be directed to download manually.")

    # Step 3 — Source payload
    step_header(3, 5, "Source files to encrypt")
    log("Choose a source folder (optionally compressed) or supply an existing zip.")
    print()
    print("      1.  Folder  (copy as-is, or compress to a zip first)")
    print("      2.  Existing zip file")

    src_type = prompt("Choice", "1")
    payload_path: Path
    payload_size_mb: int

    def expand(raw): return os.path.abspath(os.path.expandvars(os.path.expanduser(raw)))

    if src_type == "2":
        # Existing zip
        while True:
            p = expand(prompt_required("Path to zip file"))
            if os.path.isfile(p) and p.lower().endswith(".zip"):
                break
            err(f"Not found or not a .zip file: {p}")
        payload_path = Path(p)
        payload_size_mb = payload_path.stat().st_size // (1024 * 1024)
        ok(f"Zip file accepted  ({payload_size_mb} MB)")

    else:
        # Folder
        while True:
            p = expand(prompt_required("Source folder path"))
            if os.path.isdir(p):
                break
            err(f"Not a directory: {p}")
        src_dir = Path(p)
        raw_files = [f for f in src_dir.rglob("*") if f.is_file()]
        raw_mb = sum(f.stat().st_size for f in raw_files) // (1024 * 1024)
        ok(f"{len(raw_files)} file(s), {raw_mb} MB uncompressed")

        if confirm("Compress to a zip archive before loading into the container?"):
            need_compress = True
            if STAGING_ZIP.exists():
                warn(f"Existing staging.zip found ({STAGING_ZIP.stat().st_size // (1024 * 1024)} MB)")
                if not confirm("Overwrite it?"):
                    need_compress = False
                    payload_path = STAGING_ZIP
                    payload_size_mb = STAGING_ZIP.stat().st_size // (1024 * 1024)
                    ok(f"Using existing staging.zip  ({payload_size_mb} MB)")
            if need_compress:
                log(f"Compressing → {STAGING_ZIP} ...")
                with zipfile.ZipFile(STAGING_ZIP, "w", zipfile.ZIP_DEFLATED) as zf:
                    for f in sorted(raw_files):
                        zf.write(f, f.relative_to(src_dir.parent))
                payload_size_mb = STAGING_ZIP.stat().st_size // (1024 * 1024)
                ok(f"Compressed to {payload_size_mb} MB  (was {raw_mb} MB)")
                payload_path = STAGING_ZIP
        else:
            payload_path = src_dir
            payload_size_mb = raw_mb

    suggested_mb = max(50, int(payload_size_mb * 1.15) + 1)
    suggested_size = (
        f"{round(suggested_mb / 1024, 1)}G" if suggested_mb >= 1024
        else f"{suggested_mb}M"
    )
    log(f"Payload: ~{payload_size_mb} MB  →  suggested container size: {suggested_size}")

    # Step 4 — Create container
    step_header(4, 5, "Create encrypted container")
    if CONTAINER_PATH.exists():
        warn(f"Container already exists: {CONTAINER_PATH}")
        if not confirm("Use existing container?"):
            CONTAINER_PATH.unlink()
            _create_container(suggested_size)
    else:
        _create_container(suggested_size)

    # Step 5 — Load files
    step_header(5, 5, "Load files into container")
    print()
    print(bold("  Mount the container, copy your payload in, then dismount:"))
    print()
    print(f"    1.  Open VeraCrypt  →  Mount  →  {CONTAINER_PATH}")
    if payload_path.is_dir():
        print(f"    2.  Copy the contents of {payload_path} into the mounted volume")
    else:
        print(f"    2.  Copy {payload_path} into the mounted volume")
    print("    3.  Dismount the volume in VeraCrypt")
    wait("Press Enter when the container is loaded and dismounted")

    ok("Phase 1 complete")
    log(f"Container : {CONTAINER_PATH}")
    log(f"Payload   : {payload_path}")
    log(f"Launchers : {DIST_DIR}/")


def _create_container(suggested_size):
    size = prompt("Container size", suggested_size)
    print()
    log(f"Creating {size} container at {CONTAINER_PATH}")
    log("VeraCrypt will prompt you to enter and confirm a password.")
    print()
    run(
        f"cd build && ./create_container.sh"
        f" {shlex.quote(str(CONTAINER_PATH))}"
        f" {shlex.quote(size)}"
    )


# ── Phase 2: Provision USB drives ─────────────────────────────────────────────

def phase_provision():
    phase_header("2 of 2", "Provision USB drives  (repeats per drive)")

    if not CONTAINER_PATH.exists():
        err(f"Container not found: {CONTAINER_PATH}")
        err("Run Phase 1 first to build artifacts.")
        sys.exit(1)

    drive_count = 0
    while True:
        drive_count += 1

        # Step 1 — Device selection
        step_header(1, 4, "Select target USB device")
        safety.print_disks()
        device = prompt_required("Target USB device (e.g. /dev/sdb, /dev/disk2)")
        safety.confirm_device(device)

        # Step 2 — Format USB  (script has its own interactive YES prompt)
        step_header(2, 4, "Format USB")
        log("The formatting script will ask you to confirm before erasing the device.")
        print()
        run(f"cd build && ./create_usb_layout.sh {shlex.quote(device)}")
        print()
        log("USB formatted. Mount both partitions before continuing.")
        log("macOS : partitions auto-mount under /Volumes/")
        log("Linux : sudo mount <device>1 /mnt/tools && sudo mount <device>2 /mnt/data")
        wait("Press Enter when both partitions are mounted")

        # Step 3 — TOOLS partition
        step_header(3, 4, "Populate TOOLS partition")
        tools_mount = prompt_required("TOOLS partition mount path (partition 1)")
        run_quiet(
            f"cd build && ./populate_tools_partition.sh {shlex.quote(tools_mount)}",
            "Copy launchers and README to TOOLS partition",
        )

        # Step 4 — DATA partition
        step_header(4, 4, "Copy container to DATA partition")
        data_mount = prompt_required("DATA partition mount path (partition 2)")
        dest = os.path.join(data_mount, "SECURE_DATA.vc")
        run_quiet(
            f"cp {shlex.quote(str(CONTAINER_PATH))} {shlex.quote(dest)}",
            f"Copy {CONTAINER_PATH.name} → SECURE_DATA.vc",
        )
        run_quiet("cd build && ./verify.sh", "Verify checksums")
        ok(f"Drive #{drive_count} provisioned — safely eject before unplugging")

        if not confirm("Provision another USB drive?", default_yes=False):
            break

    ok(f"All done — {drive_count} drive(s) provisioned")


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    banner()
    check_prerequisites()
    print()
    log("Phase 1  Build artifacts on this machine (source files → encrypted container)")
    log("Phase 2  Provision one or more USB drives from those artifacts")

    if CONTAINER_PATH.exists():
        ok(f"Container found: {CONTAINER_PATH}")
        if confirm("Skip Phase 1 and go straight to provisioning?"):
            phase_provision()
            sys.exit(0)

    phase_build()

    if confirm("Proceed to provision a USB drive now?"):
        phase_provision()
    else:
        ok("Artifacts ready. Run the TUI again when you are ready to provision drives.")

    sys.exit(0)


if __name__ == "__main__":
    main()
