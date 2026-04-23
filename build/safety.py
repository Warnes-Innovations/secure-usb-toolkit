import subprocess
import platform
import json
import sys


def _run(cmd):
    return subprocess.check_output(cmd, shell=True, stderr=subprocess.DEVNULL).decode()


def _collect_mounts(dev):
    """Recursively collect all mount points from an lsblk device entry."""
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
            out = _run("lsblk -J -o NAME,TYPE,MOUNTPOINTS")
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
            out = _run("diskutil info / | grep 'Part of Whole'")
            disk = out.split(":")[-1].strip()
            if disk:
                blocked.add(f"/dev/{disk}")
        except Exception:
            pass

    return blocked


def list_disks():
    os_name = platform.system().lower()
    if os_name == "linux":
        out = _run("lsblk -J -o NAME,SIZE,TYPE,MOUNTPOINTS,MODEL")
        return json.loads(out)
    elif os_name == "darwin":
        out = _run("diskutil list")
        return {"raw": out}
    elif os_name == "windows":
        out = _run("wmic diskdrive get Size,Model,DeviceID /format:csv")
        return {"raw": out}
    else:
        raise RuntimeError(f"Unsupported OS: {platform.system()}")


def print_disks():
    os_name = platform.system().lower()
    blocked = get_system_disks()

    print("\n=== AVAILABLE DISKS ===")
    if os_name == "linux":
        data = list_disks()
        for dev in data.get("blockdevices", []):
            if dev.get("type") == "disk":
                path = f"/dev/{dev['name']}"
                flag = "  [SYSTEM — BLOCKED]" if path in blocked else ""
                size = dev.get("size", "?")
                model = dev.get("model") or ""
                print(f"  {path:<12} {size:>8}  {model}{flag}")
    else:
        info = list_disks()
        print(info.get("raw", ""))

    if blocked:
        print(f"\n  System disks (blocked): {', '.join(sorted(blocked))}")
    print()


def confirm_device(device):
    blocked = get_system_disks()

    if device in blocked:
        print(f"\n  ERROR: {device} is identified as a system disk and cannot be selected.")
        print("  If you are certain this is an external device, contact your system administrator.")
        sys.exit(1)

    print(f"\n  Selected device : {device}")
    print("  WARNING: ALL DATA ON THIS DEVICE WILL BE PERMANENTLY DESTROYED.\n")

    a = input(f"  Type the full device path to confirm ({device}): ").strip()
    if a != device:
        print("\n  Confirmation failed — aborting.")
        sys.exit(1)

    b = input("  Type it again: ").strip()
    if b != device:
        print("\n  Confirmation failed — aborting.")
        sys.exit(1)

    print()
    return True
