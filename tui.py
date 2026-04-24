import subprocess
import shlex
import sys
import os
import glob
import re
import time
import threading
import zipfile
import shutil
import platform
import argparse
import contextlib
import hashlib
import json
import math
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
CONTAINER_PATH = REPO_ROOT / "output.vc"
STAGING_ZIP = REPO_ROOT / "staging.zip"

VERACRYPT_VERSION = "1.26.24"
FUSE_T_VERSION = "1.2.1"

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
        log(f"{label}  ({total_mb:,} MB) ...")
    CHUNK = 4 * 1024 * 1024
    done = 0
    with src.open("rb") as fin, dst.open("wb") as fout:
        while True:
            chunk = fin.read(CHUNK)
            if not chunk:
                break
            fout.write(chunk)
            done += len(chunk)
            _bar(done // (1024 * 1024), total_mb, "MB")
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
        warn(f"Low disk space on {label}:  {free} MB free,  {needed_mb} MB needed")
        if not confirm("Continue anyway?", default_yes=False):
            sys.exit(1)
    else:
        log(f"Space OK on {label}: {free} MB free  ({needed_mb} MB needed)")


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
        ans = _read(bold(f"  ▶  Select disk [1") + (f"–{len(entries)}" if len(entries) > 1 else "") + bold("]: "))
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

def _macos_install_prerequisites():
    """On macOS, auto-download and launch FUSE-T and VeraCrypt installers if missing."""
    vc_base = f"https://launchpad.net/veracrypt/trunk/{VERACRYPT_VERSION}/+download"
    vc_dmg_name = f"VeraCrypt_FUSE-T_{VERACRYPT_VERSION}.dmg"
    vc_dmg_url = f"{vc_base}/{vc_dmg_name}"
    vc_checksum_url = f"{vc_base}/veracrypt-{VERACRYPT_VERSION}-sha256sum.txt"
    fuse_t_pkg_name = f"fuse-t-macos-installer-{FUSE_T_VERSION}.pkg"
    fuse_t_pkg_url = (
        f"https://github.com/macos-fuse-t/fuse-t/releases/download/"
        f"{FUSE_T_VERSION}/{fuse_t_pkg_name}"
    )

    def _dl_progress(n_blocks, block_size, total):
        if total > 0:
            done_mb = min(n_blocks * block_size, total) // (1024 * 1024)
            total_mb = max(1, total // (1024 * 1024))
            _bar(done_mb, total_mb, "MB")

    # Always download into dist/VeraCrypt/ so files persist across runs.
    dist_vc_dir = DIST_DIR / "VeraCrypt"
    dist_vc_dir.mkdir(parents=True, exist_ok=True)

    def _cached_or_download(name, url):
        """Return path to `name`, downloading into dist/VeraCrypt/ if not already present."""
        dest = dist_vc_dir / name
        if dest.exists():
            ok(f"Using cached {name}")
            return dest
        try:
            urllib.request.urlretrieve(url, dest, _dl_progress)
            _bar_done()
            ok(f"Downloaded {name}")
        except Exception as exc:
            err(f"Download failed: {exc}")
            sys.exit(1)
        return dest

    # ── FUSE-T ────────────────────────────────────────────────────────────────
    def _fuse_t_installed():
        r = subprocess.run(
            ["pkgutil", "--pkgs", "--regexp", r"org\.fuse-t\.core\..*"],
            capture_output=True,
        )
        return r.returncode == 0 and bool(r.stdout.strip())

    fuse_t_ok = _fuse_t_installed()

    if not fuse_t_ok:
        warn("FUSE-T is not installed — preparing installer ...")
        pkg_path = _cached_or_download(fuse_t_pkg_name, fuse_t_pkg_url)
        log("Opening FUSE-T installer — follow the prompts.")
        log("You may need to approve a system extension in:")
        log("  System Settings \u2192 Privacy & Security \u2192 Security")
        subprocess.run(["open", str(pkg_path)])
        wait("Press Enter once FUSE-T installation is complete")
        if not _fuse_t_installed():
            err("FUSE-T still not detected.")
            err("Install manually from https://www.fuse-t.org/ then re-run.")
            sys.exit(1)
        ok("FUSE-T installed")

    # ── VeraCrypt ─────────────────────────────────────────────────────────────
    vc_installed = (
        shutil.which("veracrypt") is not None
        or Path("/Applications/VeraCrypt.app").exists()
    )

    if not vc_installed:
        warn("VeraCrypt is not installed — preparing installer ...")
        vc_checksum_path = _cached_or_download("veracrypt-sha256sums.txt", vc_checksum_url)
        vc_dmg_path = _cached_or_download(vc_dmg_name, vc_dmg_url)
        log("Verifying checksum ...")
        checksum_text = vc_checksum_path.read_text()
        expected = next(
            (line.split()[0] for line in checksum_text.splitlines()
             if vc_dmg_name.lower() in line.lower()),
            None,
        )
        if expected:
            actual = hashlib.sha256(vc_dmg_path.read_bytes()).hexdigest()
            if actual != expected:
                err("Checksum MISMATCH — download may be corrupt or tampered with.")
                err(f"  Expected : {expected}")
                err(f"  Actual   : {actual}")
                sys.exit(1)
            ok("Checksum verified")
        log("Mounting VeraCrypt DMG ...")
        attach_result = subprocess.run(
            ["hdiutil", "attach", str(vc_dmg_path), "-nobrowse"],
            capture_output=True, text=True, check=True,
        )
        # hdiutil output lines are tab-separated: device, fstype, mountpoint
        mount_point = attach_result.stdout.strip().splitlines()[-1].split("\t")[-1].strip()
        try:
            pkg_files = list(Path(mount_point).glob("*.pkg"))
            if not pkg_files:
                err("No .pkg installer found in VeraCrypt DMG.")
                sys.exit(1)
            vc_pkg = pkg_files[0]
            log(f"Opening VeraCrypt installer ({vc_pkg.name}) — follow the prompts.")
            subprocess.run(["open", str(vc_pkg)])
            wait("Press Enter once VeraCrypt installation is complete")
        finally:
            subprocess.run(["hdiutil", "detach", mount_point], capture_output=True)
        vc_ok = (
            shutil.which("veracrypt") is not None
            or Path("/Applications/VeraCrypt.app").exists()
        )
        if not vc_ok:
            err("VeraCrypt not detected after installation.")
            err("Install manually from https://veracrypt.io/en/Downloads.html then re-run.")
            sys.exit(1)
        ok("VeraCrypt installed")


def check_prerequisites():
    """Verify all required external tools are present before any user interaction."""
    os_name = platform.system()

    if os_name == "Darwin":
        _macos_install_prerequisites()
        return

    # Linux: check required tools and show install hints if missing
    checks = [
        ("veracrypt", {"Linux": "https://veracrypt.io/en/Downloads.html"}),
        ("parted",    {"Linux": "sudo apt install parted      / sudo dnf install parted"}),
        ("mkfs.vfat", {"Linux": "sudo apt install dosfstools  / sudo dnf install dosfstools"}),
        ("mkfs.exfat",{"Linux": "sudo apt install exfatprogs  / sudo dnf install exfatprogs"}),
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
        cmd_dist(None)

    # Step 2 — VeraCrypt Windows installer
    step_header(2, 5, "VeraCrypt Windows installer")
    vc_dir = DIST_DIR / "VeraCrypt"
    if vc_dir.exists() and any(vc_dir.glob("*.exe")):
        ok("VeraCrypt installer already in dist/VeraCrypt/")
    else:
        if confirm("Download VeraCrypt installer for Windows users?"):
            cmd_fetch_veracrypt(None)
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
            p = expand(prompt_path_required("Path to zip file"))
            if os.path.isfile(p) and p.lower().endswith(".zip"):
                break
            err(f"Not found or not a .zip file: {p}")
        payload_path = Path(p)
        payload_size_mb = payload_path.stat().st_size // (1024 * 1024)
        ok(f"Zip file accepted  ({payload_size_mb} MB)")

    else:
        # Folder
        while True:
            p = expand(prompt_path_required("Source folder path"))
            if os.path.isdir(p):
                break
            err(f"Not a directory: {p}")
        src_dir = Path(p)
        with _spinner("Scanning source folder"):
            raw_files = [f for f in src_dir.rglob("*") if f.is_file()]
            raw_mb = sum(f.stat().st_size for f in raw_files) // (1024 * 1024)
        ok(f"{len(raw_files):,} file(s), {raw_mb:,} MB uncompressed")

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
                sorted_files = sorted(raw_files)
                total = len(sorted_files)
                with zipfile.ZipFile(STAGING_ZIP, "w", zipfile.ZIP_DEFLATED,
                                     strict_timestamps=False) as zf:
                    for done, f in enumerate(sorted_files, 1):
                        zf.write(f, f.relative_to(src_dir.parent))
                        _bar(done, total, "files")
                _bar_done()
                payload_size_mb = STAGING_ZIP.stat().st_size // (1024 * 1024)
                ok(f"Compressed to {payload_size_mb} MB  (was {raw_mb} MB)")
                payload_path = STAGING_ZIP
        else:
            payload_path = src_dir
            payload_size_mb = raw_mb

    container_mb = max(50, int(payload_size_mb * 1.15) + 1)
    container_size_str = (
        f"{math.ceil(container_mb / 1024)}G" if container_mb >= 1024
        else f"{container_mb}M"
    )
    log(f"Payload: ~{payload_size_mb} MB  →  container size: {container_size_str} (payload + 15% headroom)")

    # Step 4 — Create container
    step_header(4, 5, "Create encrypted container")
    if CONTAINER_PATH.exists():
        warn(f"Container already exists: {CONTAINER_PATH}")
        if not confirm("Use existing container?"):
            CONTAINER_PATH.unlink()
            _check_space(REPO_ROOT, container_mb, "build volume")
            _create_container(container_size_str)
    else:
        _check_space(REPO_ROOT, container_mb, "build volume")
        _create_container(container_size_str)

    # Step 5 — Load files
    step_header(5, 5, "Load files into container")
    _load_container(payload_path)

    ok("Phase 1 complete")
    log(f"Container : {CONTAINER_PATH}")
    log(f"Payload   : {payload_path}")
    log(f"Launchers : {DIST_DIR}/")


def _check_fuse_t():
    """Abort on macOS if FUSE-T is not installed (required for VeraCrypt mounts)."""
    if platform.system() != "Darwin":
        return
    r = subprocess.run(
        ["pkgutil", "--pkgs", "--regexp", r"org\.fuse-t\.core\..*"],
        capture_output=True,
    )
    if r.returncode != 0 or not r.stdout.strip():
        err("FUSE-T is required on macOS to create and mount VeraCrypt containers.")
        err("Install from: https://www.fuse-t.org/")
        sys.exit(1)


def _create_container(size):
    _check_fuse_t()
    log(f"Creating {size} container at {CONTAINER_PATH}")
    log("VeraCrypt will prompt you to enter and confirm a password.")
    print()
    run(
        f"veracrypt --text --create {shlex.quote(str(CONTAINER_PATH))}"
        f" --size {shlex.quote(size)}"
        f" --volume-type Normal"
        f" --encryption AES"
        f" --hash SHA-512"
        f" --filesystem exfat"
        f" --pim 0"
        f" --random-source /dev/urandom"
    )


def _mount_container():
    """Mount CONTAINER_PATH to a temp directory and return the mount point path."""
    _check_fuse_t()
    mount_dir = Path(f"/tmp/vc_secure_{os.getpid()}")
    mount_dir.mkdir(exist_ok=True)
    log("Mounting container — VeraCrypt will prompt for the password.")
    print()
    run(
        f"veracrypt --text --mount {shlex.quote(str(CONTAINER_PATH))}"
        f" {shlex.quote(str(mount_dir))}"
        f" --pim 0"
        f" --protect-hidden no"
    )
    ok(f"Mounted at {mount_dir}")
    return mount_dir


def _dismount_container(mount_dir):
    """Dismount the container and remove the temp mount directory."""
    run_quiet(
        f"veracrypt --text --dismount {shlex.quote(str(mount_dir))}",
        "Dismounting container",
    )
    with contextlib.suppress(Exception):
        Path(mount_dir).rmdir()


def _load_container(payload_path):
    """Mount the container, copy the payload in, then dismount."""
    mount_dir = _mount_container()
    try:
        if payload_path.is_file():
            dest = mount_dir / payload_path.name
            _copy_with_progress(payload_path, dest,
                                 label=f"Copy {payload_path.name} \u2192 container")
        else:
            all_files = sorted(f for f in payload_path.rglob("*") if f.is_file())
            total = len(all_files)
            log(f"Copying {total:,} files \u2192 container ...")
            for i, src in enumerate(all_files, 1):
                rel = src.relative_to(payload_path)
                dst = mount_dir / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                _bar(i, total, "files")
            _bar_done()
            ok(f"Copied {total:,} files")
    finally:
        _dismount_container(mount_dir)


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
        try:
            # Step 1 — Device selection
            step_header(1, 4, "Select target USB device")
            device = select_disk()
            confirm_device(device)

            # Step 2 — Format USB
            step_header(2, 4, "Format USB")
            _create_usb_layout(device)

            # Step 3 — Mount partitions and populate TOOLS
            step_header(3, 4, "Populate TOOLS partition")
            tools_mount, data_mount = _mount_usb_partitions(device)
            try:
                tools_needed_mb = _dir_size_mb(DIST_DIR) + 1 if DIST_DIR.exists() else 1
                _check_space(tools_mount, tools_needed_mb, "TOOLS partition")
                _populate_tools(tools_mount)

                # Step 4 — DATA partition
                step_header(4, 4, "Copy container to DATA partition")
                container_needed_mb = CONTAINER_PATH.stat().st_size // (1024 * 1024) + 1
                _check_space(data_mount, container_needed_mb, "DATA partition")
                dest = data_mount / "SECURE_DATA.vc"
                _copy_with_progress(CONTAINER_PATH, dest,
                                     label=f"Copy {CONTAINER_PATH.name} \u2192 SECURE_DATA.vc")
                _verify_dist()
            finally:
                _eject_usb(device, tools_mount, data_mount)

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


# ── Operation helpers (previously shell scripts) ─────────────────────────────

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


def _mount_usb_partitions(device):
    """Mount both USB partitions and return (tools_mount, data_mount) Paths."""
    os_name = platform.system()
    if os_name == "Darwin":
        tools_part = f"{device}s1"
        data_part  = f"{device}s2"
        # diskutil partitionDisk auto-mounts; give it a moment, then verify
        time.sleep(1)
        tools_mount = _macos_mount_point(tools_part)
        if not tools_mount:
            run_quiet(f"diskutil mount {shlex.quote(tools_part)}", f"Mount TOOLS ({tools_part})")
            tools_mount = _macos_mount_point(tools_part)
        data_mount = _macos_mount_point(data_part)
        if not data_mount:
            run_quiet(f"diskutil mount {shlex.quote(data_part)}", f"Mount DATA ({data_part})")
            data_mount = _macos_mount_point(data_part)
        if not tools_mount or not data_mount:
            err("Could not determine partition mount points — check diskutil info output")
            sys.exit(1)
    elif os_name == "Linux":
        tools_part = _linux_partition(device, 1)
        data_part  = _linux_partition(device, 2)
        tools_mount = Path(f"/tmp/vc_tools_{os.getpid()}")
        data_mount  = Path(f"/tmp/vc_data_{os.getpid()}")
        tools_mount.mkdir(exist_ok=True)
        data_mount.mkdir(exist_ok=True)
        run_quiet(f"mount {shlex.quote(tools_part)} {shlex.quote(str(tools_mount))}",
                  f"Mount TOOLS ({tools_part})")
        run_quiet(f"mount {shlex.quote(data_part)} {shlex.quote(str(data_mount))}",
                  f"Mount DATA ({data_part})")
    else:
        err(f"Unsupported OS for auto-mount: {os_name}")
        sys.exit(1)
    ok(f"TOOLS → {tools_mount}")
    ok(f"DATA  → {data_mount}")
    return Path(tools_mount), Path(data_mount)


def _eject_usb(device, tools_mount, data_mount):
    """Flush, unmount, and eject the USB device."""
    os_name = platform.system()
    if os_name == "Darwin":
        run_quiet(f"diskutil eject {shlex.quote(device)}", f"Eject {device}")
    elif os_name == "Linux":
        run_quiet(f"umount {shlex.quote(str(tools_mount))}", "Unmount TOOLS")
        run_quiet(f"umount {shlex.quote(str(data_mount))}", "Unmount DATA")
        run_quiet("sync", "Flush writes")
        for mp in (tools_mount, data_mount):
            with contextlib.suppress(Exception):
                Path(mp).rmdir()


def _create_usb_layout(device):
    os_name = platform.system()
    print()
    log(f"Target device : {device}")
    log("Partition 1   : FAT32  (TOOLS — unencrypted, ~1 GiB)")
    log("Partition 2   : exFAT  (DATA  — VeraCrypt container)")

    if os_name == "Linux":
        run_quiet(f"parted {shlex.quote(device)} --script mklabel msdos", "Create partition table")
        run_quiet(f"parted {shlex.quote(device)} --script mkpart primary fat32 1MiB 1024MiB", "Create TOOLS partition")
        run_quiet(f"parted {shlex.quote(device)} --script mkpart primary exfat 1024MiB 100%", "Create DATA partition")
        run_quiet(f"mkfs.vfat -F32 {shlex.quote(device + '1')}", "Format TOOLS (FAT32)")
        run_quiet(f"mkfs.exfat {shlex.quote(device + '2')}", "Format DATA (exFAT)")
    elif os_name == "Darwin":
        # diskutil handles partition + format in one shot on macOS
        run_quiet(
            f"diskutil partitionDisk {shlex.quote(device)} 2 MBR"
            f" FAT32 TOOLS 1G"
            f" ExFAT DATA R",
            "Partition and format USB",
        )
    else:
        err(f"Unsupported OS for USB formatting: {os_name}")
        sys.exit(1)

    ok(f"USB layout created on {device}")
    log(f"  Partition 1 (FAT32 / TOOLS) : {device}s1  (macOS) / {device}1  (Linux)")
    log(f"  Partition 2 (exFAT / DATA)  : {device}s2  (macOS) / {device}2  (Linux)")


def _populate_tools(mount):
    if not DIST_DIR.exists() or not any(DIST_DIR.iterdir()):
        err("dist/ is empty — run 'python3 tui.py dist' first to build launchers.")
        sys.exit(1)
    mount_path = Path(mount)
    for src in DIST_DIR.iterdir():
        dst = mount_path / src.name
        if src.is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            shutil.copy2(src, dst)
    shutil.copy2(REPO_ROOT / "templates" / "README.html", mount_path / "README.html")
    ok(f"Tools partition populated at {mount}")


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

def cmd_disks(_args):
    print_disks()


def cmd_usb(args):
    print_disks()
    confirm_device(args.device)
    _create_usb_layout(args.device)


def cmd_container(args):
    _create_container(args.size)


def cmd_populate(args):
    _populate_tools(args.mount)


def cmd_update_tools(args):
    """Mount the TOOLS partition, refresh its content, then unmount."""
    if args.mount:
        _populate_tools(Path(args.mount))
        return
    # Auto-mount partition 1
    device = args.device
    confirm_device(device)
    os_name = platform.system()
    if os_name == "Darwin":
        tools_part = f"{device}s1"
        run_quiet(f"diskutil mount {shlex.quote(tools_part)}", f"Mount TOOLS ({tools_part})")
        tools_mount = _macos_mount_point(tools_part)
        if not tools_mount:
            err("Could not determine TOOLS mount point.")
            sys.exit(1)
        _populate_tools(tools_mount)
        run_quiet(f"diskutil eject {shlex.quote(device)}", f"Eject {device}")
    elif os_name == "Linux":
        tools_part = _linux_partition(device, 1)
        tools_mount = Path(f"/tmp/vc_tools_{os.getpid()}")
        tools_mount.mkdir(exist_ok=True)
        try:
            run_quiet(f"mount {shlex.quote(tools_part)} {shlex.quote(str(tools_mount))}",
                      f"Mount TOOLS ({tools_part})")
            _populate_tools(tools_mount)
            run_quiet(f"umount {shlex.quote(str(tools_mount))}", "Unmount TOOLS")
            run_quiet("sync", "Flush writes")
            run_quiet(f"eject {shlex.quote(device)}", f"Eject {device}")
        finally:
            with contextlib.suppress(Exception):
                tools_mount.rmdir()
    else:
        err(f"Unsupported OS: {os_name}")
        sys.exit(1)
    ok("TOOLS partition updated")


def cmd_clone(args):
    print_disks()
    confirm_device(args.target)
    _clone_usb(args.source, args.target)


def cmd_verify(_args):
    _verify_dist()


def cmd_dist(_args):
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    run_quiet(
        f"pyinstaller --onedir --name SecureUSB --distpath {shlex.quote(str(DIST_DIR))} tui.py",
        "Build PyInstaller launcher",
    )
    for launcher in ("SecureUSB.command", "SecureUSB.sh", "SecureUSB.bat"):
        shutil.copy(REPO_ROOT / "launchers" / launcher, DIST_DIR / launcher)
    (DIST_DIR / "SecureUSB.command").chmod(0o755)
    (DIST_DIR / "SecureUSB.sh").chmod(0o755)
    ok("dist/ built")


def cmd_fetch_veracrypt(_args):
    VERSION = VERACRYPT_VERSION
    base = f"https://launchpad.net/veracrypt/trunk/{VERSION}/+download"
    checksum_url = f"{base}/veracrypt-{VERSION}-sha256sum.txt"

    dest_dir = DIST_DIR / "VeraCrypt"
    dest_dir.mkdir(parents=True, exist_ok=True)
    checksum_path = dest_dir / "sha256sums.txt"

    def _progress(n_blocks, block_size, total):
        if total > 0:
            pct = min(100, n_blocks * block_size * 100 // total)
            print(f"\r    {pct:3d}%", end="", flush=True)

    def _download_and_verify(url, path, display_name):
        checksum_text = checksum_path.read_text()
        expected = next(
            (line.split()[0] for line in checksum_text.splitlines()
             if display_name.lower() in line.lower()),
            None,
        )
        if path.exists() and expected:
            if hashlib.sha256(path.read_bytes()).hexdigest() == expected:
                ok(f"Already present (checksum OK): {display_name}")
                return
        log(f"Downloading {display_name} ...")
        urllib.request.urlretrieve(url, path, _progress)
        print()
        ok(f"Downloaded: {display_name}")
        if not expected:
            err(f"Could not find checksum entry for '{display_name}'")
            path.unlink(missing_ok=True)
            sys.exit(1)
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            err("Checksum MISMATCH — file may be corrupt or tampered with.")
            err(f"  Expected : {expected}")
            err(f"  Actual   : {actual}")
            path.unlink(missing_ok=True)
            sys.exit(1)
        ok(f"Checksum verified: {display_name}")

    log(f"VeraCrypt {VERSION} — fetching official SHA-256 checksums ...")
    urllib.request.urlretrieve(checksum_url, checksum_path)
    ok("Checksums downloaded")

    # Windows installer
    win_name = f"VeraCrypt Setup {VERSION}.exe"
    _download_and_verify(
        f"{base}/VeraCrypt%20Setup%20{VERSION}.exe",
        dest_dir / win_name,
        win_name,
    )

    # macOS — FUSE-T build (works on Intel and Apple Silicon)
    mac_name = f"VeraCrypt_FUSE-T_{VERSION}.dmg"
    _download_and_verify(
        f"{base}/VeraCrypt_FUSE-T_{VERSION}.dmg",
        dest_dir / mac_name,
        mac_name,
    )

    # FUSE-T installer (required on macOS before running VeraCrypt)
    fuse_t_name = f"fuse-t-macos-installer-{FUSE_T_VERSION}.pkg"
    fuse_t_url = (
        f"https://github.com/macos-fuse-t/fuse-t/releases/download/"
        f"{FUSE_T_VERSION}/{fuse_t_name}"
    )
    fuse_t_path = dest_dir / fuse_t_name
    if fuse_t_path.exists():
        ok(f"Already present: {fuse_t_name}")
    else:
        log(f"Downloading {fuse_t_name} ...")
        urllib.request.urlretrieve(fuse_t_url, fuse_t_path, _progress)
        print()
        ok(f"Downloaded: {fuse_t_name}  (macOS Gatekeeper will verify the signature on install)")


def cmd_clean(_args):
    """Remove generated and temporary files."""
    targets = [
        # PyInstaller output
        DIST_DIR,
        REPO_ROOT / "build" / "SecureUSB",
        REPO_ROOT / "SecureUSB.spec",
        # VeraCrypt container and staging zip
        CONTAINER_PATH,
        STAGING_ZIP,
    ]
    # __pycache__ trees anywhere under the repo
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
        description="Secure USB Toolkit — provision encrypted USB drives with VeraCrypt",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("disks", help="List available disks")

    p_usb = sub.add_parser("usb", help="Partition and format a USB drive")
    p_usb.add_argument("device", help="Target device (e.g. /dev/sdb, /dev/disk2)")

    p_con = sub.add_parser("container", help="Create encrypted VeraCrypt container")
    p_con.add_argument("--size", default="1G", help="Container size e.g. 2G, 500M  (default: 1G)")

    p_pop = sub.add_parser("populate", help="Copy launchers and README to TOOLS partition")
    p_pop.add_argument("mount", help="Mount path of the TOOLS partition (partition 1)")

    p_upd = sub.add_parser("update-tools", help="Refresh the TOOLS partition on an already-provisioned drive")
    _upd_target = p_upd.add_mutually_exclusive_group(required=True)
    _upd_target.add_argument("--device", metavar="DEV",
                              help="Device to update (e.g. /dev/disk2) — auto-mounts partition 1")
    _upd_target.add_argument("--mount", metavar="PATH",
                              help="Already-mounted TOOLS partition path (skips mount/unmount)")

    p_clone = sub.add_parser("clone", help="Clone a provisioned USB drive (dd bit-copy)")
    p_clone.add_argument("source", help="Source device")
    p_clone.add_argument("target", help="Target device")

    sub.add_parser("verify",          help="Verify integrity checksums in dist/")
    sub.add_parser("dist",            help="Build the PyInstaller launcher bundle into dist/")
    sub.add_parser("fetch-veracrypt", help="Download and verify VeraCrypt Windows installer")
    sub.add_parser("clean",           help="Remove generated files (dist/, output.vc, staging.zip, __pycache__)")

    args = parser.parse_args()
    dispatch = {
        "disks":           cmd_disks,
        "usb":             cmd_usb,
        "container":       cmd_container,
        "populate":        cmd_populate,
        "update-tools":    cmd_update_tools,
        "clone":           cmd_clone,
        "verify":          cmd_verify,
        "dist":            cmd_dist,
        "fetch-veracrypt": cmd_fetch_veracrypt,
        "clean":           cmd_clean,
    }
    dispatch[args.command](args)


# ── Entry point ───────────────────────────────────────────────────────────────

def _tui_main():
    banner()
    check_prerequisites()
    print()
    log("Phase 1  Build artifacts on this machine (source files → encrypted container)")
    log("Phase 2  Provision one or more USB drives from those artifacts")

    if CONTAINER_PATH.exists():
        print()
        size_mb = CONTAINER_PATH.stat().st_size // (1024 * 1024)
        print(bold(f"  ┌─ Existing encrypted container found ({'─' * 20}"))
        print(bold(f"  │  {CONTAINER_PATH}  ({size_mb:,} MB)"))
        print(bold(f"  └{'─' * 50}"))
        print()
        print(dim("    1.  Use existing container  (skip Phase 1, go straight to provisioning)"))
        print(dim("    2.  Create a new container  (run Phase 1 from scratch)"))
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
