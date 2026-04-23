#!/usr/bin/env python3
"""Secure USB Toolkit — scriptable CLI interface."""

import argparse
import subprocess
import shlex
import sys

from build import safety


def run(cmd):
    subprocess.run(cmd, shell=True, check=True)


def cmd_disks(_args):
    safety.print_disks()


def cmd_usb(args):
    safety.print_disks()
    safety.confirm_device(args.device)
    run(f"cd build && ./create_usb_layout.sh {shlex.quote(args.device)}")


def cmd_container(_args):
    run("cd build && ./create_container.sh")


def cmd_populate(args):
    run(f"cd build && ./populate_tools_partition.sh {shlex.quote(args.mount)}")


def cmd_clone(args):
    safety.print_disks()
    safety.confirm_device(args.target)
    run(f"cd build && ./clone_usb.sh {shlex.quote(args.source)} {shlex.quote(args.target)}")


def cmd_verify(_args):
    run("cd build && ./verify.sh")


def main():
    parser = argparse.ArgumentParser(
        prog="secureusb",
        description="Secure USB Toolkit — provision encrypted USB drives with VeraCrypt",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("disks", help="List available disks")

    p_usb = sub.add_parser("usb", help="Create dual-partition USB layout")
    p_usb.add_argument("device", help="Target device (e.g. /dev/sdb, /dev/disk2)")

    sub.add_parser("container", help="Create encrypted VeraCrypt container")

    p_pop = sub.add_parser("populate", help="Populate tools partition with launchers and README")
    p_pop.add_argument("mount", help="Mount path of the tools partition")

    p_clone = sub.add_parser("clone", help="Clone USB device (bit-for-bit via dd)")
    p_clone.add_argument("source", help="Source device")
    p_clone.add_argument("target", help="Target device")

    sub.add_parser("verify", help="Verify integrity checksums in dist/")

    args = parser.parse_args()

    dispatch = {
        "disks":     cmd_disks,
        "usb":       cmd_usb,
        "container": cmd_container,
        "populate":  cmd_populate,
        "clone":     cmd_clone,
        "verify":    cmd_verify,
    }
    dispatch[args.command](args)


if __name__ == "__main__":
    main()
