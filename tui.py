from build import safety
import subprocess
import shlex
import sys
import os
from pathlib import Path

REPO_ROOT = Path(__file__).parent
DIST_DIR = REPO_ROOT / "dist"
CONTAINER_PATH = REPO_ROOT / "output.vc"


def run(cmd):
    subprocess.run(cmd, shell=True, check=True)


def banner():
    print("\n╔═══════════════════════════════════════╗")
    print("║      SECURE USB TOOLKIT — Wizard      ║")
    print("╚═══════════════════════════════════════╝")


def phase_header(label):
    print(f"\n  ══ {label} ══")


def step_header(n, total, title):
    print(f"\n  ── Step {n}/{total}: {title} ──")


def ask(prompt, default=None):
    suffix = f" [{default}]" if default is not None else ""
    val = input(f"  {prompt}{suffix}: ").strip()
    return val if val else default


def ask_required(prompt):
    while True:
        val = input(f"  {prompt}: ").strip()
        if val:
            return val
        print("  [!] Required.")


def confirm(prompt, default_yes=True):
    hint = "[Y/n]" if default_yes else "[y/N]"
    ans = input(f"  {prompt} {hint}: ").strip().lower()
    return (ans in ("y", "yes")) if ans else default_yes


# ── Phase 1: Build artifacts (done once per batch) ───────────────────────────

def phase_build():
    phase_header("PHASE 1 OF 2: BUILD ARTIFACTS  (done once per batch)")
    print("  Build the container and launchers on this machine.")
    print("  Every USB drive provisioned in Phase 2 gets a copy of these artifacts.")

    # Step 1 — Launchers
    step_header(1, 5, "Build launchers")
    if any(DIST_DIR.glob("SecureUSB*")):
        print("  ✓ Launchers already present in dist/")
    else:
        print("  Running 'make dist'...")
        run("make dist")

    # Step 2 — VeraCrypt Windows installer
    step_header(2, 5, "VeraCrypt Windows installer")
    vc_dir = DIST_DIR / "VeraCrypt"
    if vc_dir.exists() and any(vc_dir.glob("*.exe")):
        print("  ✓ VeraCrypt installer already in dist/VeraCrypt/")
    else:
        if confirm("  Download VeraCrypt installer for Windows users?"):
            run("make fetch-veracrypt")
        else:
            print("  Skipped — Windows users will be directed to download VeraCrypt manually.")

    # Step 3 — Source files
    step_header(3, 5, "Source files to encrypt")
    print("  Enter the folder whose contents will be placed in the encrypted container.")
    while True:
        src = ask_required("Source folder path")
        if os.path.isdir(src):
            break
        print(f"  [!] Not a directory: {src}")
    src = os.path.abspath(src)

    try:
        files = [f for f in Path(src).rglob("*") if f.is_file()]
        total_mb = sum(f.stat().st_size for f in files) // (1024 * 1024)
        suggested_mb = max(50, int(total_mb * 1.15) + 1)
        suggested_size = (
            f"{round(suggested_mb / 1024, 1)}G" if suggested_mb >= 1024
            else f"{suggested_mb}M"
        )
        print(f"  {len(files)} file(s), ~{total_mb} MB  →  suggested size: {suggested_size}")
    except Exception:
        suggested_size = "1G"

    # Step 4 — Create container
    step_header(4, 5, "Create encrypted container")
    if CONTAINER_PATH.exists():
        print(f"  Container already exists: {CONTAINER_PATH}")
        if not confirm("  Use existing container?"):
            CONTAINER_PATH.unlink()
            _create_container(suggested_size)
    else:
        _create_container(suggested_size)

    # Step 5 — Load files into container
    step_header(5, 5, "Load files into container")
    print()
    print(f"  Container: {CONTAINER_PATH}")
    print(f"  Source:    {src}")
    print()
    print("  Mount the container with VeraCrypt, copy your files in, then dismount:")
    print(f"    1. Open VeraCrypt → Mount → select  {CONTAINER_PATH}")
    print(f"    2. Copy the contents of  {src}  into the mounted volume")
    print("    3. Dismount the volume in VeraCrypt before continuing")
    print()
    input("  Press Enter when the container is loaded and dismounted... ")
    print("\n  ✓ Phase 1 complete.")
    print(f"    Container: {CONTAINER_PATH}")
    print(f"    Launchers: {DIST_DIR}/")


def _create_container(suggested_size):
    size = ask("  Container size", suggested_size)
    print(f"\n  Creating {size} container at {CONTAINER_PATH}")
    print("  VeraCrypt will prompt you to set a password.")
    run(
        f"cd build && ./create_container.sh"
        f" {shlex.quote(str(CONTAINER_PATH))}"
        f" {shlex.quote(size)}"
    )


# ── Phase 2: Provision USB drives (loop) ─────────────────────────────────────

def phase_provision():
    phase_header("PHASE 2 OF 2: PROVISION USB DRIVES  (repeats per drive)")

    if not CONTAINER_PATH.exists():
        print(f"\n  [!] Container not found: {CONTAINER_PATH}")
        print("      Run Phase 1 first to build artifacts.")
        sys.exit(1)

    drive_count = 0
    while True:
        drive_count += 1

        # Step 1 — Device selection
        step_header(1, 4, "Select target USB device")
        safety.print_disks()
        device = ask_required("Target USB device (e.g. /dev/sdb, /dev/disk2)")
        safety.confirm_device(device)

        # Step 2 — Format
        step_header(2, 4, "Format USB")
        run(f"cd build && ./create_usb_layout.sh {shlex.quote(device)}")
        print()
        print("  USB formatted. Mount both partitions before continuing.")
        print("  macOS: partitions auto-mount under /Volumes/")
        print("  Linux: sudo mount <device>1 /mnt/tools && sudo mount <device>2 /mnt/data")
        input("  Press Enter when both partitions are mounted... ")

        # Step 3 — TOOLS partition
        step_header(3, 4, "Populate TOOLS partition")
        tools_mount = ask_required("TOOLS partition mount path (partition 1)")
        run(f"cd build && ./populate_tools_partition.sh {shlex.quote(tools_mount)}")

        # Step 4 — DATA partition
        step_header(4, 4, "Copy encrypted container to DATA partition")
        data_mount = ask_required("DATA partition mount path (partition 2)")
        dest = os.path.join(data_mount, "SECURE_DATA.vc")
        print(f"  Copying {CONTAINER_PATH.name} → {dest} ...")
        run(f"cp {shlex.quote(str(CONTAINER_PATH))} {shlex.quote(dest)}")

        print("\n  Verifying checksums...")
        run("cd build && ./verify.sh")
        print(f"\n  ✓ Drive #{drive_count} provisioned. Safely eject before unplugging.")

        if not confirm("\n  Provision another USB drive?", default_yes=False):
            break

    print(f"\n  All done — {drive_count} drive(s) provisioned.")


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    banner()
    print()
    print("  Phase 1  Build artifacts on this machine (source files → encrypted container)")
    print("  Phase 2  Provision one or more USB drives from those artifacts")

    if CONTAINER_PATH.exists():
        print(f"\n  ✓ Container found: {CONTAINER_PATH}")
        if confirm("  Skip Phase 1 and go straight to provisioning?"):
            phase_provision()
            sys.exit(0)

    phase_build()

    if confirm("\n  Proceed to provision a USB drive now?"):
        phase_provision()
    else:
        print("\n  Artifacts ready. Run the TUI again to provision USB drives.")

    sys.exit(0)


if __name__ == "__main__":
    main()
