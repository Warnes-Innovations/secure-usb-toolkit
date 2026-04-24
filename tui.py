import subprocess
import shlex
import sys
import os
import glob
import re
import time
import threading
import zipfile
import tarfile
import shutil
import platform
import argparse
import contextlib
import hashlib
import json
import getpass
import urllib.request
from pathlib import Path

try:
    import readline as _rl
    _READLINE = True
except ImportError:
    _rl = None  # type: ignore
    _READLINE = False

REPO_ROOT = Path(__file__).parent
DIST_DIR = REPO_ROOT / "dist"
ARCHIVE_PATH = REPO_ROOT / "secure_data.7z"

PEAZIP_VERSION = "11.0.0"
_PZ_BASE = f"https://github.com/peazip/PeaZip/releases/download/{PEAZIP_VERSION}"
_PZ_SHA256_FILE = "SHA256.txt"
_PZ_SHA256_HASH = "beef980b5d40c183b40a768e4840a0d91b9d56d0724db026b36957fc8c46cf4c"
PEAZIP_DIST_DIR = DIST_DIR / "PeaZip"

# (filename, sha256, dest_name, extract)
PEAZIP_ASSETS = [
    (f"peazip_portable-{PEAZIP_VERSION}.WIN64.zip",
     "4e3ef7bbfc6607bbb08c29ce0178feb7845444c7d019fa6cfea8fc9081c103da",
     "PeaZip-Windows", True),
    (f"peazip-{PEAZIP_VERSION}.DARWIN.x86_64.zip",
     "1daad9a82bbc97775ae1b7df91c613d7425dd49b0c91c2ce6a3105ff16298641",
     "PeaZip-macOS-Intel.zip", False),
    (f"peazip-{PEAZIP_VERSION}.DARWIN.aarch64.dmg",
     "a9fc877533dcbb00a4e85a8c05579c3fc54f6391d540d58d7863f84f3c6170e4",
     "PeaZip-macOS-ARM.dmg", False),
    (f"peazip_portable-{PEAZIP_VERSION}.LINUX.GTK2.x86_64.tar.gz",
     "1a61e57302ef7c8e3539ceabfc05db4faa26283589d531962f0867f6b435e5b5",
     "PeaZip-Linux-x86", True),
    (f"peazip_portable-{PEAZIP_VERSION}.LINUX.GTK2.aarch64.tar.gz",
     "eb916b656edbe85bde722e6a1fa52c7e31519d9fe46b7a502be837e4deb3b3e7",
     "PeaZip-Linux-ARM", True),
]

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


# ── Progress helpers ─────────────────────────────────────────────────────────

_BAR_W = 40
_SPINNER_CHARS = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


def _bar(done, total, unit=""):
    """Overwrite the current line with a progress bar (TTY only)."""
    if not _COLOR or total == 0:
        return
    pct = done / total
    filled = int(_BAR_W * pct)
    bar = "█" * filled + "░" * (_BAR_W - filled)
    suffix = f"  {done:,}/{total:,}{(' ' + unit) if unit else ''}  ({int(pct * 100):3d}%)"
    sys.stdout.write(f"\r    [{bar}]{suffix}")
    sys.stdout.flush()


def _bar_done():
    """Finish a progress bar line (TTY only)."""
    if _COLOR:
        sys.stdout.write("\n")
        sys.stdout.flush()


@contextlib.contextmanager
def _spinner(label):
    """Show a spinning indicator while inside the context (TTY only)."""
    if not _COLOR:
        print(dim(f"    {label} ..."))
        yield
        return
    stop = threading.Event()

    def _spin():
        i = 0
        while not stop.is_set():
            ch = _SPINNER_CHARS[i % len(_SPINNER_CHARS)]
            sys.stdout.write(f"\r    {ch}  {dim(label + ' ...')}")
            sys.stdout.flush()
            time.sleep(0.1)
            i += 1

    t = threading.Thread(target=_spin, daemon=True)
    t.start()
    try:
        yield
    finally:
        stop.set()
        t.join()
        sys.stdout.write("\r" + " " * 80 + "\r")
        sys.stdout.flush()


def _copy_with_progress(src, dst, label=None):
    """Copy src → dst in 4 MiB chunks with a byte-level progress bar."""
    src, dst = Path(src), Path(dst)
    total = src.stat().st_size
    total_mb = max(1, total // (1024 * 1024))
    if label:
        log(f"{label}  ({_fmt_size(total_mb)}) ...")
    # Choose display unit once so the bar is consistent throughout the copy.
    if total_mb >= 1000:
        divisor, unit, total_units = 1024 * 1024 * 1024, "GB", max(1, total // (1024 * 1024 * 1024))
    else:
        divisor, unit, total_units = 1024 * 1024, "MB", total_mb
    CHUNK = 4 * 1024 * 1024
    done = 0
    with src.open("rb") as fin, dst.open("wb") as fout:
        while True:
            chunk = fin.read(CHUNK)
            if not chunk:
                break
            fout.write(chunk)
            done += len(chunk)
            _bar(done // divisor, total_units, unit)
    _bar_done()
    shutil.copystat(src, dst)
    if label:
        ok(label)


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


# ── Readline path completion ──────────────────────────────────────────────────

@contextlib.contextmanager
def _path_completion():
    """Context manager that enables tab-completion for filesystem paths."""
    if not _READLINE:
        yield
        return

    def _completer(text, state):
        expanded = os.path.expanduser(text)
        matches = glob.glob(expanded + "*")
        annotated = [m + ("/" if os.path.isdir(m) else "") for m in matches]
        if text.startswith("~"):
            home = os.path.expanduser("~")
            annotated = [
                "~" + m[len(home):] if m.startswith(home) else m
                for m in annotated
            ]
        try:
            return annotated[state]
        except IndexError:
            return None

    old_completer = _rl.get_completer()
    old_delims = _rl.get_completer_delims()
    _rl.set_completer(_completer)
    _rl.set_completer_delims(" \t\n")
    bind_cmd = (
        "bind ^I rl_complete" if "libedit" in (_rl.__doc__ or "")
        else "tab: complete"
    )
    _rl.parse_and_bind(bind_cmd)
    try:
        yield
    finally:
        _rl.set_completer(old_completer)
        _rl.set_completer_delims(old_delims)


def prompt_path(msg, default=None):
    """Like prompt() but with tab-completion for filesystem paths."""
    with _path_completion():
        return prompt(msg, default)


def prompt_path_required(msg):
    """Like prompt_required() but with tab-completion for filesystem paths."""
    with _path_completion():
        return prompt_required(msg)


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
    with _spinner(label):
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    combined = (result.stdout + result.stderr).strip()
    n = len(combined.splitlines()) if combined else 0

    if result.returncode != 0:
        err(f"{label}  — failed")
        if combined:
            _show_output_box(combined, "Error output")
        raise subprocess.CalledProcessError(result.returncode, cmd)

    ok(label)


def run(cmd):
    """Run an interactive command — output passes straight through."""
    subprocess.run(cmd, shell=True, check=True)


# ── Disk space helpers ────────────────────────────────────────────────────────

def _fmt_size(mb):
    """Return a human-readable size string: GB when >= 1000 MB, else MB."""
    if mb >= 1000:
        return f"{mb / 1024:.1f} GB"
    return f"{mb:,} MB"


def _free_mb(path):
    """Free space in MiB on the filesystem containing path."""
    return shutil.disk_usage(path).free // (1024 * 1024)


def _dir_size_mb(path):
    """Total size in MiB of all files recursively under path."""
    return sum(f.stat().st_size for f in Path(path).rglob("*") if f.is_file()) // (1024 * 1024)


def _check_space(path, needed_mb, label):
    """Warn if path's filesystem has less than needed_mb free; ask to confirm."""
    free = _free_mb(path)
    if free < needed_mb:
        warn(f"Low disk space on {label}:  {_fmt_size(free)} free,  {_fmt_size(needed_mb)} needed")
        if not confirm("Continue anyway?", default_yes=False):
            sys.exit(1)
    else:
        log(f"Space OK on {label}: {_fmt_size(free)} free  ({_fmt_size(needed_mb)} needed)")


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


# ── Disk safety ──────────────────────────────────────────────────────────────

def _safety_run(cmd):
    return subprocess.check_output(cmd, shell=True, stderr=subprocess.DEVNULL).decode()


def _collect_mounts(dev):
    mounts = set()
    for mp in dev.get("mountpoints") or []:
        if mp:
            mounts.add(mp)
    for child in dev.get("children") or []:
        mounts.update(_collect_mounts(child))
    return mounts


def get_system_disks():
    """Return a set of device paths that must never be written to."""
    os_name = platform.system().lower()
    blocked = set()
    if os_name == "linux":
        try:
            out = _safety_run("lsblk -J -o NAME,TYPE,MOUNTPOINTS")
            data = json.loads(out)
            for dev in data.get("blockdevices", []):
                if dev.get("type") == "disk":
                    mounts = _collect_mounts(dev)
                    if any(m in ("/", "/boot", "/boot/efi") for m in mounts):
                        blocked.add(f"/dev/{dev['name']}")
        except Exception:
            pass
    elif os_name == "darwin":
        try:
            out = _safety_run("diskutil info / | grep 'Part of Whole'")
            disk = out.split(":")[-1].strip()
            if disk:
                blocked.add(f"/dev/{disk}")
        except Exception:
            pass
    return blocked


def _list_external_disks_macos():
    """Return list of (dev_path, size_str, name) for external physical disks on macOS."""
    disks = []
    try:
        raw = _safety_run("diskutil list external physical")
    except Exception:
        return disks
    # Each disk block starts with "/dev/diskN (external, physical):"
    current_dev = None
    current_size = "?"
    current_name = ""
    for line in raw.splitlines():
        m = re.match(r"^(/dev/disk\d+)\s", line)
        if m:
            if current_dev:
                disks.append((current_dev, current_size, current_name))
            current_dev = m.group(1)
            current_size = "?"
            current_name = ""
        elif current_dev:
            # Line 0 is the disk-level entry: "   0:  FDisk_partition_scheme  *15.6 GB  disk2"
            # The asterisk (*) marks the total disk size — capture it only from line 0.
            if re.match(r"\s*0:", line):
                size_m = re.search(r"\*(\d+\.\d+ (?:GB|MB|TB))\s", line)
                if size_m:
                    current_size = size_m.group(1)
            else:
                # Grab a human-readable name from the first non-zero partition entry.
                name_m = re.search(r"\d:\s+\S+\s+(\S[^\s].+?)\s{2,}", line)
                if name_m and not current_name:
                    candidate = name_m.group(1).strip()
                    if candidate and candidate != "-":
                        current_name = candidate
    if current_dev:
        disks.append((current_dev, current_size, current_name))
    return disks


def list_disks():
    os_name = platform.system().lower()
    if os_name == "linux":
        return json.loads(_safety_run("lsblk -J -o NAME,SIZE,TYPE,MOUNTPOINTS,MODEL"))
    elif os_name == "darwin":
        return {"raw": _safety_run("diskutil list")}
    elif os_name == "windows":
        return {"raw": _safety_run("wmic diskdrive get Size,Model,DeviceID /format:csv")}
    else:
        raise RuntimeError(f"Unsupported OS: {platform.system()}")


def _external_disk_entries():
    """Return list of (dev_path, label) for selectable external disks (cross-platform)."""
    blocked = get_system_disks()
    entries = []
    os_name = platform.system().lower()
    if os_name == "darwin":
        for dev, size, name in _list_external_disks_macos():
            if dev not in blocked:
                label = f"{dev}  ({size}{'  — ' + name if name else ''})"
                entries.append((dev, label))
    elif os_name == "linux":
        data = list_disks()
        for dev in data.get("blockdevices", []):
            if dev.get("type") == "disk":
                path = f"/dev/{dev['name']}"
                if path in blocked:
                    continue
                size = dev.get("size", "?")
                model = dev.get("model") or ""
                label = f"{path}  ({size}{'  — ' + model if model else ''})"
                entries.append((path, label))
    return entries


def print_disks():
    """Print available (non-system) external disks. Used by CLI subcommands."""
    blocked = get_system_disks()
    entries = _external_disk_entries()
    print()
    if entries:
        print(bold("  External disks:"))
        for dev, label in entries:
            print(f"    {label}")
    else:
        print(dim("  No external disks detected."))
    if blocked:
        print(dim(f"\n  System disks (blocked): {', '.join(sorted(blocked))}"))
    print()


def select_disk():
    """Show a numbered list of external disks and return the chosen device path."""
    while True:
        blocked = get_system_disks()
        entries = _external_disk_entries()
        print()
        if not entries:
            print(dim("  No external disks detected."))
            if blocked:
                print(dim(f"  System disks (blocked): {', '.join(sorted(blocked))}"))
            wait("Insert a USB drive, then press Enter to refresh")
            continue
        print(bold("  Available external disks:"))
        for i, (dev, label) in enumerate(entries, 1):
            print(f"    {bold(str(i))}.  {label}")
        if blocked:
            print(dim(f"\n  System disks (blocked): {', '.join(sorted(blocked))}"))
        print()
        ans = _read(bold(f"  ▶  Select disk [1") + (f"–{len(entries)}" if len(entries) > 1 else "") + bold("]: ")).strip() or "1"
        if ans.isdigit() and 1 <= int(ans) <= len(entries):
            return entries[int(ans) - 1][0]
        err(f"Enter a number between 1 and {len(entries)}.")


def confirm_device(device):
    blocked = get_system_disks()
    if device in blocked:
        err(f"{device} is identified as a system disk and cannot be selected.")
        sys.exit(1)
    print(f"\n  Selected device : {device}")
    print(red(bold("  !  ALL DATA ON THIS DEVICE WILL BE PERMANENTLY DESTROYED.")))
    print()
    a = _read(bold(f"  ▶  Type the full device path to confirm ({device}): "))
    if a.strip() != device:
        err("Confirmation failed — aborting.")
        sys.exit(1)
    print()


# ── Pre-flight checks ───────────────────────────────────────────────────────────────

def _find_7z():
    """Return the path to a 7-Zip binary, or abort with install instructions."""
    for name in ("7zz", "7z", "7za"):
        path = shutil.which(name)
        if path:
            return path
    err("7-Zip is required to create the encrypted archive but was not found.")
    if platform.system() == "Darwin":
        err("  Install with:  brew install 7zip")
    else:
        err("  Install with:  sudo apt install 7zip    (Debian/Ubuntu)")
        err("                 sudo dnf install 7zip    (Fedora/RHEL)")
    sys.exit(1)


def check_prerequisites():
    """Verify required partition/format tools are present (Linux only)."""
    os_name = platform.system()
    if os_name != "Linux":
        return

    checks = [
        ("parted",     "sudo apt install parted      / sudo dnf install parted"),
        ("mkfs.exfat", "sudo apt install exfatprogs  / sudo dnf install exfatprogs"),
    ]
    missing = [(tool, hint) for tool, hint in checks if shutil.which(tool) is None]
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

def _prompt_password(msg):
    """Prompt for a password without echoing it to the terminal."""
    try:
        return getpass.getpass(bold(f"\n  ▶  {msg}: "))
    except KeyboardInterrupt:
        print()
        warn("Interrupted — exiting.")
        sys.exit(1)


def _create_encrypted_archive(payload_path, output_path, password):
    """Create an AES-256 encrypted .7z archive from payload_path."""
    seven_z = _find_7z()
    payload_path = Path(payload_path)
    output_path = Path(output_path).resolve()

    # Run 7z from the payload's parent so stored paths are relative.
    if payload_path.is_dir():
        cwd = str(payload_path.parent)
        source_arg = payload_path.name
    else:
        cwd = None
        source_arg = str(payload_path)

    label = f"Create encrypted archive ({output_path.name})"

    if _COLOR:
        # -bsp1 sends progress percentages to stdout; -bso0 suppresses
        # normal stdout messages so only progress lines appear on that stream.
        cmd = [
            seven_z, "a", "-t7z", "-mhe=on", "-mx=5",
            f"-p{password}",
            "-bsp1", "-bso0",
            str(output_path),
            source_arg,
        ]
        log(f"{label} ...")
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=cwd)
        buf = b""
        while True:
            chunk = proc.stdout.read(32)
            if not chunk:
                break
            buf += chunk
            # Progress lines are delimited by \r and/or \n.
            parts = re.split(b"[\r\n]", buf)
            buf = parts[-1]
            for part in parts[:-1]:
                m = re.search(rb"(\d+)%", part)
                if m:
                    _bar(int(m.group(1)), 100)
        _bar_done()
        proc.wait()
        if proc.returncode != 0:
            err("Archive creation failed")
            stderr_out = proc.stderr.read().decode(errors="replace").strip()
            if stderr_out:
                _show_output_box(stderr_out, "7z output")
            raise subprocess.CalledProcessError(proc.returncode, str(seven_z))
    else:
        cmd = [
            seven_z, "a", "-t7z", "-mhe=on", "-mx=5",
            f"-p{password}",
            str(output_path),
            source_arg,
        ]
        with _spinner(label):
            result = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
        if result.returncode != 0:
            err("Archive creation failed")
            combined = (result.stdout + result.stderr).strip()
            if combined:
                _show_output_box(combined, "7z output")
            raise subprocess.CalledProcessError(result.returncode, str(seven_z))

    ok(f"Created {output_path.name}")


def _ask_password_and_create_archive(payload_path):
    """Prompt for an encryption password (with confirmation) and create the archive."""
    log("Choose a strong password for the encrypted archive.")
    log("Users will need this password to open their files.")
    while True:
        pw1 = _prompt_password("Password")
        pw2 = _prompt_password("Confirm password")
        if pw1 == pw2:
            break
        err("Passwords do not match — try again.")
    if payload_path.is_dir():
        archive_mb = max(10, _dir_size_mb(payload_path) + 1)
    else:
        archive_mb = max(10, payload_path.stat().st_size // (1024 * 1024) + 1)
    _check_space(REPO_ROOT, archive_mb, "build volume")
    _create_encrypted_archive(payload_path, ARCHIVE_PATH, pw1)


def phase_build():
    phase_header("1 of 2", "Build artifacts  (done once per batch)")
    log("PeaZip portables and the encrypted archive are prepared here.")
    log("Every USB drive in Phase 2 receives a copy of these artifacts.")

    # Step 1 — PeaZip portables
    step_header(1, 3, "Fetch PeaZip portables")
    if PEAZIP_DIST_DIR.exists() and any(PEAZIP_DIST_DIR.iterdir()):
        ok("PeaZip portables already present in dist/PeaZip/")
    else:
        if confirm("Download PeaZip portables for all platforms?"):
            cmd_fetch_peazip(None)
        else:
            warn("Skipped — USB drives will not include PeaZip portables.")

    # Step 2 — Source payload
    step_header(2, 3, "Source files to encrypt")
    log("Provide a folder or file. 7z will compress and encrypt it in one pass.")

    def expand(raw): return os.path.abspath(os.path.expandvars(os.path.expanduser(raw)))

    while True:
        p = expand(prompt_path_required("Source folder or file path"))
        if os.path.exists(p):
            break
        err(f"Not found: {p}")
    payload_path = Path(p)

    if payload_path.is_dir():
        with _spinner("Scanning source folder"):
            raw_files = [f for f in payload_path.rglob("*") if f.is_file()]
            raw_mb = sum(f.stat().st_size for f in raw_files) // (1024 * 1024)
        ok(f"{len(raw_files):,} file(s), {_fmt_size(raw_mb)}")
    else:
        size_mb = payload_path.stat().st_size // (1024 * 1024)
        ok(f"File accepted  ({_fmt_size(size_mb)})")

    # Step 3 — Create encrypted archive
    step_header(3, 3, "Create encrypted archive")
    if ARCHIVE_PATH.exists():
        warn(f"Archive already exists: {ARCHIVE_PATH}")
        if not confirm("Use existing archive?"):
            ARCHIVE_PATH.unlink()
            _ask_password_and_create_archive(payload_path)
        else:
            ok("Using existing archive")
    else:
        _ask_password_and_create_archive(payload_path)

    ok("Phase 1 complete")
    log(f"Archive   : {ARCHIVE_PATH}")
    log(f"Portables : {PEAZIP_DIST_DIR}/")


# ── Phase 2: Provision USB drives ─────────────────────────────────────────────

def phase_provision():
    phase_header("2 of 2", "Provision USB drives  (repeats per drive)")

    if not ARCHIVE_PATH.exists():
        err(f"Archive not found: {ARCHIVE_PATH}")
        err("Run Phase 1 first to build the encrypted archive.")
        sys.exit(1)

    if not PEAZIP_DIST_DIR.exists() or not any(PEAZIP_DIST_DIR.iterdir()):
        warn("PeaZip portables not found in dist/PeaZip/")
        warn("Run 'python3 tui.py fetch-peazip' to download them.")
        if not confirm("Continue without PeaZip portables?", default_yes=False):
            sys.exit(1)

    drive_count = 0
    while True:
        drive_count += 1
        try:
            # Step 1 — Device selection
            step_header(1, 3, "Select target USB device")
            device = select_disk()
            confirm_device(device)

            # Step 2 — Format USB
            step_header(2, 3, "Format USB")
            _create_usb_layout(device)

            # Step 3 — Mount and populate
            step_header(3, 3, "Populate USB")
            mount = _mount_usb(device)
            try:
                _populate_usb_tools(mount)
                archive_needed_mb = ARCHIVE_PATH.stat().st_size // (1024 * 1024) + 1
                _check_space(mount, archive_needed_mb, "USB")
                _copy_with_progress(ARCHIVE_PATH, mount / ARCHIVE_PATH.name,
                                     label=f"Copy {ARCHIVE_PATH.name} \u2192 USB")
            finally:
                _eject_usb(device, mount)

            ok(f"Drive #{drive_count} provisioned and ejected — safe to unplug")

        except (subprocess.CalledProcessError, OSError) as exc:
            print()
            err(f"Operation failed: {exc}")
            print()
            if not confirm("Retry this drive?", default_yes=True):
                warn("Skipping drive.")
                drive_count -= 1  # don't count failed drives
            continue

        if not confirm("Provision another USB drive?", default_yes=False):
            break

    # ── Batch summary ──────────────────────────────────────────────────────────
    print()
    print(bold("  ╔═══════════════════════════════════════╗"))
    print(bold(f"  ║   Batch complete: {drive_count} drive(s) provisioned".ljust(42) + "║"))
    print(bold("  ╚═══════════════════════════════════════╝"))
    print()


# ── Operation helpers ─────────────────────────────────────────────────────────

def _linux_partition(device, n):
    """Return the Linux partition device path for partition n.
    Handles both sdb-style (sdb1) and nvme/mmcblk-style (nvme0n1p1).
    """
    if device[-1].isdigit():  # nvme0n1, mmcblk0 — append 'p' before number
        return f"{device}p{n}"
    return f"{device}{n}"


def _macos_mount_point(part):
    """Return the current mount point for a macOS disk identifier, or None."""
    r = subprocess.run(["diskutil", "info", part], capture_output=True, text=True)
    for line in r.stdout.splitlines():
        if "Mount Point" in line:
            mp = line.split(":", 1)[1].strip()
            if mp and mp not in ("(null)", "None", ""):
                return Path(mp)
    return None


def _mount_usb(device):
    """Mount the USB partition and return its mount point Path."""
    os_name = platform.system()
    if os_name == "Darwin":
        part = f"{device}s1"
        time.sleep(1)
        mount = _macos_mount_point(part)
        if not mount:
            run_quiet(f"diskutil mount {shlex.quote(part)}", f"Mount {part}")
            mount = _macos_mount_point(part)
        if not mount:
            err("Could not determine USB mount point — check diskutil info output")
            sys.exit(1)
    elif os_name == "Linux":
        part = _linux_partition(device, 1)
        mount = Path(f"/tmp/secure_usb_{os.getpid()}")
        mount.mkdir(exist_ok=True)
        run_quiet(f"mount {shlex.quote(part)} {shlex.quote(str(mount))}", f"Mount {part}")
    else:
        err(f"Unsupported OS: {os_name}")
        sys.exit(1)
    ok(f"USB → {mount}")
    return Path(mount)


def _eject_usb(device, mount):
    """Flush, unmount, and eject the USB device."""
    os_name = platform.system()
    if os_name == "Darwin":
        # Force-unmount first so Spotlight/CoreServices cannot dissent the eject.
        run_quiet(f"diskutil unmountDisk force {shlex.quote(device)}", f"Unmount {device}")
        run_quiet(f"diskutil eject {shlex.quote(device)}", f"Eject {device}")
    elif os_name == "Linux":
        run_quiet(f"umount {shlex.quote(str(mount))}", "Unmount USB")
        run_quiet("sync", "Flush writes")
        with contextlib.suppress(Exception):
            Path(mount).rmdir()


def _create_usb_layout(device):
    os_name = platform.system()
    print()
    log(f"Target device : {device}")
    log("Layout        : single exFAT partition (SECURE_USB)")

    if os_name == "Linux":
        run_quiet(f"parted {shlex.quote(device)} --script mklabel msdos", "Create partition table")
        run_quiet(f"parted {shlex.quote(device)} --script mkpart primary 1MiB 100%", "Create partition")
        part = _linux_partition(device, 1)
        run_quiet(f"mkfs.exfat -n SECURE_USB {shlex.quote(part)}", "Format (exFAT)")
    elif os_name == "Darwin":
        run_quiet(
            f"diskutil partitionDisk {shlex.quote(device)} 1 MBR ExFAT SECURE_USB R",
            "Partition and format USB",
        )
    else:
        err(f"Unsupported OS for USB formatting: {os_name}")
        sys.exit(1)

    ok(f"USB formatted on {device}  (exFAT / SECURE_USB)")


def _populate_usb_tools(mount):
    """Copy PeaZip portables and README.html to the USB (leaves archive untouched)."""
    mount = Path(mount)
    if PEAZIP_DIST_DIR.exists() and any(PEAZIP_DIST_DIR.iterdir()):
        for src in PEAZIP_DIST_DIR.iterdir():
            if src.name.startswith("."):
                continue
            dst = mount / src.name
            if src.is_dir():
                if dst.exists():
                    shutil.rmtree(dst)
                with _spinner(f"Copy {src.name}/ → USB"):
                    shutil.copytree(src, dst)
                ok(f"Copied {src.name}/")
            else:
                _copy_with_progress(src, dst, label=f"Copy {src.name} → USB")
    else:
        warn("No PeaZip portables found — skipping.")
    shutil.copy2(REPO_ROOT / "templates" / "README.html", mount / "README.html")
    ok("README.html copied")


def _verify_dist():
    if not DIST_DIR.exists() or not any(DIST_DIR.iterdir()):
        warn("dist/ is empty — nothing to verify.")
        return
    checksum_file = DIST_DIR / "checksums.txt"
    files = sorted(p for p in DIST_DIR.rglob("*") if p.is_file() and p != checksum_file)
    total = len(files)
    log(f"Checksumming {total:,} files ...")
    lines = []
    for i, f in enumerate(files, 1):
        digest = hashlib.sha256(f.read_bytes()).hexdigest()
        lines.append(f"{digest}  {f.relative_to(DIST_DIR)}")
        _bar(i, total, "files")
    _bar_done()
    checksum_file.write_text("\n".join(lines) + "\n")
    for line in lines:
        digest, rel = line.split("  ", 1)
        actual = hashlib.sha256((DIST_DIR / rel).read_bytes()).hexdigest()
        if actual != digest:
            err(f"Checksum mismatch: {rel}")
            sys.exit(1)
    ok(f"Integrity verified ({total:,} files)")


def _clone_usb(source, target):
    run(
        f"dd if={shlex.quote(source)} of={shlex.quote(target)}"
        f" bs=4m conv=sync status=progress"
    )
    ok(f"Clone complete: {source} → {target}")


# ── CLI subcommands ──────────────────────────────────────────────────────────

def cmd_fetch_peazip(_args):
    """Download and verify all PeaZip portable packages for all platforms."""
    PEAZIP_DIST_DIR.mkdir(parents=True, exist_ok=True)
    cache_dir = PEAZIP_DIST_DIR / ".cache"
    cache_dir.mkdir(exist_ok=True)

    def _dl_progress(n_blocks, block_size, total):
        if total > 0:
            done_bytes = min(n_blocks * block_size, total)
            if total >= 1024 * 1024:
                _bar(done_bytes // (1024 * 1024), max(1, total // (1024 * 1024)), "MB")
            else:
                _bar(done_bytes // 1024, max(1, total // 1024), "KB")

    # Fetch and verify the SHA256.txt manifest first.
    sha256_path = cache_dir / _PZ_SHA256_FILE
    if sha256_path.exists():
        if hashlib.sha256(sha256_path.read_bytes()).hexdigest() != _PZ_SHA256_HASH:
            sha256_path.unlink()
    if not sha256_path.exists():
        log(f"Downloading {_PZ_SHA256_FILE} ...")
        urllib.request.urlretrieve(f"{_PZ_BASE}/{_PZ_SHA256_FILE}", sha256_path, _dl_progress)
        _bar_done()
        actual = hashlib.sha256(sha256_path.read_bytes()).hexdigest()
        if actual != _PZ_SHA256_HASH:
            err("SHA256.txt checksum mismatch — download may be tampered.")
            sha256_path.unlink(missing_ok=True)
            sys.exit(1)
        ok(f"Downloaded {_PZ_SHA256_FILE}")
    else:
        ok(f"Using cached {_PZ_SHA256_FILE}")

    sha256_text = sha256_path.read_text()

    def _get_expected_hash(filename):
        for line in sha256_text.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[-1].lstrip("*") == filename:
                return parts[0]
        return None

    for filename, hardcoded_sha256, dest_name, should_extract in PEAZIP_ASSETS:
        cached = cache_dir / filename
        dest = PEAZIP_DIST_DIR / dest_name
        expected = _get_expected_hash(filename) or hardcoded_sha256

        # Skip if already in place.
        if not should_extract and dest.exists():
            if hashlib.sha256(dest.read_bytes()).hexdigest() == expected:
                ok(f"Already present: {dest_name}")
                continue
        elif should_extract and dest.exists() and any(dest.iterdir()):
            ok(f"Already extracted: {dest_name}/")
            continue

        # Download if not cached or checksum mismatch.
        if not cached.exists() or hashlib.sha256(cached.read_bytes()).hexdigest() != expected:
            log(f"Downloading {filename} ...")
            urllib.request.urlretrieve(f"{_PZ_BASE}/{filename}", cached, _dl_progress)
            _bar_done()
            actual = hashlib.sha256(cached.read_bytes()).hexdigest()
            if actual != expected:
                err(f"Checksum MISMATCH: {filename}")
                err(f"  Expected : {expected}")
                err(f"  Actual   : {actual}")
                cached.unlink(missing_ok=True)
                sys.exit(1)
            ok(f"Downloaded and verified: {filename}")
        else:
            ok(f"Using cached: {filename}")

        # Extract or copy to final destination.
        if should_extract:
            dest.mkdir(parents=True, exist_ok=True)
            if filename.endswith(".zip"):
                with _spinner(f"Extract {filename}"):
                    with zipfile.ZipFile(cached) as zf:
                        for member in zf.infolist():
                            name = member.filename
                            if name.startswith("/") or ".." in name.split("/"):
                                err(f"Unsafe path in archive: {name}")
                                sys.exit(1)
                            zf.extract(member, dest)
            else:  # .tar.gz
                with _spinner(f"Extract {filename}"):
                    with tarfile.open(cached) as tf:
                        tf.extractall(dest, filter="data")
            ok(f"Extracted: {dest_name}/")
        else:
            _copy_with_progress(cached, dest, label=f"Copy {dest_name}")

    ok(f"All PeaZip {PEAZIP_VERSION} portables ready in dist/PeaZip/")


def cmd_disks(_args):
    print_disks()


def cmd_usb(args):
    print_disks()
    confirm_device(args.device)
    _create_usb_layout(args.device)


def cmd_populate(args):
    _populate_usb_tools(Path(args.mount))


def cmd_update_tools(args):
    """Mount the USB, refresh PeaZip portables and README.html, then unmount."""
    if args.mount:
        _populate_usb_tools(Path(args.mount))
        return
    device = args.device
    blocked = get_system_disks()
    if device in blocked:
        err(f"{device} is identified as a system disk and cannot be selected.")
        sys.exit(1)
    if not confirm(f"Update PeaZip portables on {device}?"):
        warn("Aborted.")
        sys.exit(0)
    mount = _mount_usb(device)
    try:
        _populate_usb_tools(mount)
    finally:
        _eject_usb(device, mount)
    ok("USB tools updated")


def cmd_clone(args):
    print_disks()
    confirm_device(args.target)
    _clone_usb(args.source, args.target)


def cmd_verify(_args):
    _verify_dist()


def cmd_clean(_args):
    """Remove generated and temporary files."""
    targets = [
        DIST_DIR,
        ARCHIVE_PATH,
    ]
    pycache_dirs = list(REPO_ROOT.rglob("__pycache__"))
    to_remove = [p for p in targets if p.exists()] + pycache_dirs

    if not to_remove:
        ok("Nothing to clean.")
        return

    print()
    log("Will remove:")
    for p in to_remove:
        print(dim(f"    {p.relative_to(REPO_ROOT)}"))
    print()
    if not confirm("Proceed?", default_yes=False):
        warn("Aborted.")
        return

    for p in to_remove:
        if p.is_dir():
            shutil.rmtree(p)
        else:
            p.unlink()
        ok(f"Removed {p.relative_to(REPO_ROOT)}")


def _cli_main():
    parser = argparse.ArgumentParser(
        prog="tui.py",
        description="Secure USB Toolkit — provision encrypted USB drives with PeaZip",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("disks", help="List available disks")

    p_usb = sub.add_parser("usb", help="Partition and format a USB drive")
    p_usb.add_argument("device", help="Target device (e.g. /dev/sdb, /dev/disk2)")

    p_pop = sub.add_parser("populate", help="Copy PeaZip portables and README to USB")
    p_pop.add_argument("mount", help="Mount path of the USB partition")

    p_upd = sub.add_parser("update-tools",
                            help="Refresh PeaZip portables on an already-provisioned drive")
    _upd_target = p_upd.add_mutually_exclusive_group(required=True)
    _upd_target.add_argument("--device", metavar="DEV",
                              help="Device to update (e.g. /dev/disk2) — auto-mounts partition 1")
    _upd_target.add_argument("--mount", metavar="PATH",
                              help="Already-mounted USB path (skips mount/unmount)")

    p_clone = sub.add_parser("clone", help="Clone a provisioned USB drive (dd bit-copy)")
    p_clone.add_argument("source", help="Source device")
    p_clone.add_argument("target", help="Target device")

    sub.add_parser("verify",       help="Verify integrity checksums in dist/")
    sub.add_parser("fetch-peazip", help="Download and verify PeaZip portables for all platforms")
    sub.add_parser("clean",
                   help="Remove generated files (dist/, secure_data.7z, __pycache__)")

    args = parser.parse_args()
    dispatch = {
        "disks":        cmd_disks,
        "usb":          cmd_usb,
        "populate":     cmd_populate,
        "update-tools": cmd_update_tools,
        "clone":        cmd_clone,
        "verify":       cmd_verify,
        "fetch-peazip": cmd_fetch_peazip,
        "clean":        cmd_clean,
    }
    dispatch[args.command](args)


# ── Entry point ───────────────────────────────────────────────────────────────

def _tui_main():
    banner()
    check_prerequisites()
    print()
    log("Phase 1  Build artifacts on this machine (source files → encrypted archive)")
    log("Phase 2  Provision one or more USB drives from those artifacts")

    if ARCHIVE_PATH.exists():
        print()
        size_mb = ARCHIVE_PATH.stat().st_size // (1024 * 1024)
        print(bold(f"  ┌─ Existing encrypted archive found ({'─' * 20}"))
        print(bold(f"  │  {ARCHIVE_PATH}  ({_fmt_size(size_mb)})"))
        print(bold(f"  └{'─' * 50}"))
        print()
        print(dim("    1.  Use existing archive  (skip Phase 1, go straight to provisioning)"))
        print(dim("    2.  Create a new archive  (run Phase 1 from scratch)"))
        print()
        choice = _read(bold("  ▶  Choice [1]: ")).strip() or "1"
        if choice == "1":
            phase_provision()
            sys.exit(0)

    phase_build()

    if confirm("Proceed to provision a USB drive now?"):
        phase_provision()
    else:
        ok("Artifacts ready. Run the TUI again when you are ready to provision drives.")

    sys.exit(0)


def main():
    if len(sys.argv) > 1:
        _cli_main()
    else:
        _tui_main()


if __name__ == "__main__":
    main()

