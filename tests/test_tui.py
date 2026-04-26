"""
Unit tests for tui.py — Secure USB Toolkit.

Covers pure logic, text parsers, disk-safety helpers, and CLI prerequisite
checks.  External calls (subprocess, shutil.which, platform) are patched so
tests run without any real hardware or OS-specific tools.

Run with:  pytest tests/
"""

import json
import shutil
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import tui


# ── _collect_mounts ────────────────────────────────────────────────────────────


class TestCollectMounts:
    """_collect_mounts(dev) traverses a lsblk dict and returns all mount-point strings."""

    def test_empty_dict_returns_empty_set(self):
        assert tui._collect_mounts({}) == set()

    def test_single_mount_point(self):
        assert tui._collect_mounts({"mountpoints": ["/mnt/usb"]}) == {"/mnt/usb"}

    def test_multiple_mount_points(self):
        assert tui._collect_mounts({"mountpoints": ["/mnt/a", "/mnt/b"]}) == {"/mnt/a", "/mnt/b"}

    def test_none_values_filtered_out(self):
        assert tui._collect_mounts({"mountpoints": [None, "/mnt/usb", None]}) == {"/mnt/usb"}

    def test_null_mountpoints_value(self):
        assert tui._collect_mounts({"mountpoints": None}) == set()

    def test_missing_mountpoints_key(self):
        assert tui._collect_mounts({"type": "disk", "name": "sdb"}) == set()

    def test_children_mounts_included(self):
        dev = {
            "mountpoints": ["/"],
            "children": [
                {"mountpoints": ["/boot"], "children": []},
                {"mountpoints": ["/home"], "children": []},
            ],
        }
        assert tui._collect_mounts(dev) == {"/", "/boot", "/home"}

    def test_deeply_nested_children(self):
        dev = {
            "mountpoints": [],
            "children": [
                {
                    "mountpoints": ["/mnt/outer"],
                    "children": [
                        {"mountpoints": ["/mnt/inner"], "children": []},
                    ],
                }
            ],
        }
        assert tui._collect_mounts(dev) == {"/mnt/outer", "/mnt/inner"}

    def test_no_children_key_does_not_raise(self):
        dev = {"mountpoints": ["/mnt/usb"]}
        assert tui._collect_mounts(dev) == {"/mnt/usb"}

    def test_all_none_mountpoints_returns_empty(self):
        dev = {"mountpoints": [None, None], "children": [{"mountpoints": [None]}]}
        assert tui._collect_mounts(dev) == set()


# ── _linux_partition ───────────────────────────────────────────────────────────


class TestLinuxPartition:
    """_linux_partition(device, n) builds the correct device path for partition n."""

    def test_sda_partition_1(self):
        assert tui._linux_partition("/dev/sda", 1) == "/dev/sda1"

    def test_sdb_partition_2(self):
        assert tui._linux_partition("/dev/sdb", 2) == "/dev/sdb2"

    def test_sdc_partition_1(self):
        assert tui._linux_partition("/dev/sdc", 1) == "/dev/sdc1"

    def test_nvme_partition_1(self):
        # nvme0n1 ends with a digit → append 'p' before number
        assert tui._linux_partition("/dev/nvme0n1", 1) == "/dev/nvme0n1p1"

    def test_nvme_partition_2(self):
        assert tui._linux_partition("/dev/nvme0n1", 2) == "/dev/nvme0n1p2"

    def test_mmcblk_partition_1(self):
        assert tui._linux_partition("/dev/mmcblk0", 1) == "/dev/mmcblk0p1"

    def test_mmcblk_partition_3(self):
        assert tui._linux_partition("/dev/mmcblk0", 3) == "/dev/mmcblk0p3"

    def test_loop_device(self):
        # /dev/loop0 ends with a digit → same 'p' rule
        assert tui._linux_partition("/dev/loop0", 1) == "/dev/loop0p1"


# ── _list_external_disks_macos ─────────────────────────────────────────────────

# Representative `diskutil list external physical` output.
_DISKUTIL_ONE_DISK = """\
/dev/disk2 (external, physical):
   #:                       TYPE NAME                    SIZE       IDENTIFIER
   0:      FDisk_partition_scheme                        *15.6 GB   disk2
   1:                      exFAT SECURE_USB               15.5 GB   disk2s1
"""

_DISKUTIL_TWO_DISKS = """\
/dev/disk2 (external, physical):
   #:                       TYPE NAME                    SIZE       IDENTIFIER
   0:      FDisk_partition_scheme                        *15.6 GB   disk2
   1:                      exFAT SECURE_USB               15.5 GB   disk2s1
/dev/disk3 (external, physical):
   #:                       TYPE NAME                    SIZE       IDENTIFIER
   0:      FDisk_partition_scheme                        *32.0 GB   disk3
   1:                      exFAT MyDrive                  31.9 GB   disk3s1
"""

_DISKUTIL_NO_PARTITIONS = """\
/dev/disk2 (external, physical):
   #:                       TYPE NAME                    SIZE       IDENTIFIER
   0:      FDisk_partition_scheme                        *8.0 GB    disk2
"""


class TestListExternalDisksMacos:
    """_list_external_disks_macos() parses diskutil text into (dev, size, name) tuples."""

    def test_single_disk_parsed_correctly(self):
        with patch.object(tui, "_safety_run", return_value=_DISKUTIL_ONE_DISK):
            result = tui._list_external_disks_macos()
        assert len(result) == 1
        dev, size, name = result[0]
        assert dev == "/dev/disk2"
        assert size == "15.6 GB"
        assert name == "SECURE_USB"

    def test_two_disks_both_returned(self):
        with patch.object(tui, "_safety_run", return_value=_DISKUTIL_TWO_DISKS):
            result = tui._list_external_disks_macos()
        assert len(result) == 2
        devs = [r[0] for r in result]
        assert "/dev/disk2" in devs
        assert "/dev/disk3" in devs

    def test_second_disk_name_parsed(self):
        with patch.object(tui, "_safety_run", return_value=_DISKUTIL_TWO_DISKS):
            result = tui._list_external_disks_macos()
        by_dev = {r[0]: r for r in result}
        assert by_dev["/dev/disk3"][2] == "MyDrive"

    def test_no_named_partition_returns_empty_name(self):
        with patch.object(tui, "_safety_run", return_value=_DISKUTIL_NO_PARTITIONS):
            result = tui._list_external_disks_macos()
        assert len(result) == 1
        dev, size, name = result[0]
        assert dev == "/dev/disk2"
        assert size == "8.0 GB"
        assert name == ""

    def test_empty_output_returns_empty_list(self):
        with patch.object(tui, "_safety_run", return_value=""):
            result = tui._list_external_disks_macos()
        assert result == []

    def test_exception_returns_empty_list(self):
        with patch.object(tui, "_safety_run", side_effect=Exception("diskutil failed")):
            result = tui._list_external_disks_macos()
        assert result == []


# ── _macos_mount_point ─────────────────────────────────────────────────────────


class TestMacosMountPoint:
    """_macos_mount_point(part) extracts the mount path from diskutil info output."""

    def _run_result(self, stdout):
        m = MagicMock()
        m.stdout = stdout
        return m

    def test_returns_path_when_mounted(self):
        stdout = "   Mount Point:              /Volumes/SECURE_USB\n"
        with patch("subprocess.run", return_value=self._run_result(stdout)):
            result = tui._macos_mount_point("disk2s1")
        assert result == Path("/Volumes/SECURE_USB")

    def test_returns_none_for_null_mount_point(self):
        stdout = "   Mount Point:              (null)\n"
        with patch("subprocess.run", return_value=self._run_result(stdout)):
            result = tui._macos_mount_point("disk2s1")
        assert result is None

    def test_returns_none_for_literal_none(self):
        stdout = "   Mount Point:              None\n"
        with patch("subprocess.run", return_value=self._run_result(stdout)):
            result = tui._macos_mount_point("disk2s1")
        assert result is None

    def test_returns_none_when_line_absent(self):
        stdout = "   Device Identifier:        disk2s1\n   File System:             ExFAT\n"
        with patch("subprocess.run", return_value=self._run_result(stdout)):
            result = tui._macos_mount_point("disk2s1")
        assert result is None

    def test_returns_none_for_blank_mount_point(self):
        stdout = "   Mount Point:              \n"
        with patch("subprocess.run", return_value=self._run_result(stdout)):
            result = tui._macos_mount_point("disk2s1")
        assert result is None


# ── _find_7z ──────────────────────────────────────────────────────────────────


class TestFind7z:
    """_find_7z() resolves a 7-Zip binary or calls sys.exit(1)."""

    def test_prefers_7zz(self):
        with patch("shutil.which", side_effect=lambda n: "/usr/bin/7zz" if n == "7zz" else None):
            assert tui._find_7z() == "/usr/bin/7zz"

    def test_falls_back_to_7z(self):
        def which(name):
            return "/usr/bin/7z" if name == "7z" else None

        with patch("shutil.which", side_effect=which):
            assert tui._find_7z() == "/usr/bin/7z"

    def test_falls_back_to_7za(self):
        def which(name):
            return "/usr/local/bin/7za" if name == "7za" else None

        with patch("shutil.which", side_effect=which):
            assert tui._find_7z() == "/usr/local/bin/7za"

    def test_not_found_raises_system_exit(self):
        with patch("shutil.which", return_value=None):
            with pytest.raises(SystemExit):
                tui._find_7z()

    def test_not_found_exit_code_is_nonzero(self):
        with patch("shutil.which", return_value=None):
            with pytest.raises(SystemExit) as exc_info:
                tui._find_7z()
        assert exc_info.value.code != 0


# ── check_prerequisites ────────────────────────────────────────────────────────


class TestCheckPrerequisites:
    """check_prerequisites() validates Linux tool availability; no-ops on other OSes."""

    def test_non_linux_skips_checks(self):
        for os_name in ("Darwin", "Windows"):
            with patch("platform.system", return_value=os_name):
                with patch("shutil.which") as mock_which:
                    tui.check_prerequisites()
                    mock_which.assert_not_called()

    def test_linux_all_tools_present_no_exit(self):
        with patch("platform.system", return_value="Linux"):
            with patch("shutil.which", return_value="/usr/sbin/tool"):
                tui.check_prerequisites()  # must not raise

    def test_linux_missing_parted_exits(self):
        def which(name):
            return None if name == "parted" else "/usr/sbin/mkfs.exfat"

        with patch("platform.system", return_value="Linux"):
            with patch("shutil.which", side_effect=which):
                with pytest.raises(SystemExit):
                    tui.check_prerequisites()

    def test_linux_missing_mkfs_exfat_exits(self):
        def which(name):
            return None if name == "mkfs.exfat" else "/usr/sbin/parted"

        with patch("platform.system", return_value="Linux"):
            with patch("shutil.which", side_effect=which):
                with pytest.raises(SystemExit):
                    tui.check_prerequisites()

    def test_linux_both_missing_exits(self):
        with patch("platform.system", return_value="Linux"):
            with patch("shutil.which", return_value=None):
                with pytest.raises(SystemExit):
                    tui.check_prerequisites()


# ── get_system_disks ───────────────────────────────────────────────────────────


class TestGetSystemDisks:
    """get_system_disks() returns the set of device paths that must never be written to."""

    def test_macos_returns_boot_disk(self):
        diskutil_out = "   Part of Whole:          disk0\n"
        with patch("platform.system", return_value="Darwin"):
            with patch.object(tui, "_safety_run", return_value=diskutil_out):
                result = tui.get_system_disks()
        assert "/dev/disk0" in result

    def test_macos_only_boot_disk_blocked(self):
        diskutil_out = "   Part of Whole:          disk0\n"
        with patch("platform.system", return_value="Darwin"):
            with patch.object(tui, "_safety_run", return_value=diskutil_out):
                result = tui.get_system_disks()
        assert "/dev/disk1" not in result
        assert "/dev/disk2" not in result

    def test_macos_exception_returns_empty_set(self):
        with patch("platform.system", return_value="Darwin"):
            with patch.object(tui, "_safety_run", side_effect=Exception("fail")):
                result = tui.get_system_disks()
        assert result == set()

    def test_linux_root_disk_blocked(self):
        lsblk_json = json.dumps({
            "blockdevices": [
                {
                    "name": "sda", "type": "disk",
                    "mountpoints": [None],
                    "children": [
                        {"name": "sda1", "mountpoints": ["/"], "children": []},
                        {"name": "sda2", "mountpoints": ["/boot"], "children": []},
                    ],
                },
                {
                    "name": "sdb", "type": "disk",
                    "mountpoints": [None],
                    "children": [
                        {"name": "sdb1", "mountpoints": ["/mnt/usb"], "children": []},
                    ],
                },
            ]
        })
        with patch("platform.system", return_value="Linux"):
            with patch.object(tui, "_safety_run", return_value=lsblk_json):
                result = tui.get_system_disks()
        assert "/dev/sda" in result
        assert "/dev/sdb" not in result

    def test_linux_boot_efi_disk_blocked(self):
        lsblk_json = json.dumps({
            "blockdevices": [
                {
                    "name": "nvme0n1", "type": "disk",
                    "mountpoints": [None],
                    "children": [
                        {"name": "nvme0n1p1", "mountpoints": ["/boot/efi"], "children": []},
                        {"name": "nvme0n1p2", "mountpoints": ["/"], "children": []},
                    ],
                },
            ]
        })
        with patch("platform.system", return_value="Linux"):
            with patch.object(tui, "_safety_run", return_value=lsblk_json):
                result = tui.get_system_disks()
        assert "/dev/nvme0n1" in result

    def test_linux_exception_returns_empty_set(self):
        with patch("platform.system", return_value="Linux"):
            with patch.object(tui, "_safety_run", side_effect=Exception("lsblk failed")):
                result = tui.get_system_disks()
        assert result == set()

    def test_unsupported_os_returns_empty_set(self):
        with patch("platform.system", return_value="FreeBSD"):
            result = tui.get_system_disks()
        assert result == set()


# ── PEAZIP_ASSETS / constants ──────────────────────────────────────────────────


class TestPeazipAssets:
    """Validate that the PEAZIP_ASSETS constant is well-formed."""

    def test_exactly_five_assets(self):
        assert len(tui.PEAZIP_ASSETS) == 5

    def test_all_sha256_hashes_are_64_char_lowercase_hex(self):
        valid = set("0123456789abcdef")
        for filename, sha256, dest_name, _ in tui.PEAZIP_ASSETS:
            assert len(sha256) == 64, f"{dest_name}: expected 64-char SHA-256"
            assert all(c in valid for c in sha256), f"{dest_name}: non-hex char in SHA-256"

    def test_dest_names_are_unique(self):
        dest_names = [d for _, _, d, _ in tui.PEAZIP_ASSETS]
        assert len(dest_names) == len(set(dest_names))

    def test_filenames_are_unique(self):
        filenames = [f for f, _, _, _ in tui.PEAZIP_ASSETS]
        assert len(filenames) == len(set(filenames))

    def test_extract_flags(self):
        extract_map = {dest: ex for _, _, dest, ex in tui.PEAZIP_ASSETS}
        assert extract_map["PeaZip-Windows"] is True
        assert extract_map["PeaZip-macOS-Intel.zip"] is False
        assert extract_map["PeaZip-macOS-ARM.dmg"] is False
        assert extract_map["PeaZip-Linux-x86"] is True
        assert extract_map["PeaZip-Linux-ARM"] is True

    def test_sha256_txt_manifest_hash_is_valid(self):
        h = tui._PZ_SHA256_HASH
        valid = set("0123456789abcdef")
        assert len(h) == 64
        assert all(c in valid for c in h)

    def test_version_is_semver(self):
        import re
        assert re.match(r"^\d+\.\d+\.\d+$", tui.PEAZIP_VERSION)

    def test_base_url_contains_version(self):
        assert tui.PEAZIP_VERSION in tui._PZ_BASE

    def test_all_filenames_contain_version(self):
        for filename, _, _, _ in tui.PEAZIP_ASSETS:
            assert tui.PEAZIP_VERSION in filename, f"{filename} does not contain version"


# ── _free_mb / _dir_size_mb ────────────────────────────────────────────────────


class TestFmtSize:
    """_fmt_size(mb) returns GB for large values and MB otherwise."""

    def test_zero_mb(self):
        assert tui._fmt_size(0) == "0 MB"

    def test_small_mb(self):
        assert tui._fmt_size(512) == "512 MB"

    def test_999_mb_stays_mb(self):
        assert tui._fmt_size(999) == "999 MB"

    def test_exactly_1000_mb_switches_to_gb(self):
        assert tui._fmt_size(1000) == "0.977 GB" or tui._fmt_size(1000).endswith("GB")

    def test_1024_mb_is_1_0_gb(self):
        assert tui._fmt_size(1024) == "1.0 GB"

    def test_large_value_gb(self):
        assert tui._fmt_size(15 * 1024) == "15.0 GB"

    def test_commas_in_mb_range(self):
        assert tui._fmt_size(1) == "1 MB"
        assert tui._fmt_size(999) == "999 MB"

    def test_gb_has_one_decimal(self):
        result = tui._fmt_size(2048)
        assert result == "2.0 GB"


class TestDiskHelpers:
    """_free_mb and _dir_size_mb operate on real filesystem paths."""

    def test_dir_size_mb_empty_dir(self, tmp_path):
        assert tui._dir_size_mb(tmp_path) == 0

    def test_dir_size_mb_single_file_exact(self, tmp_path):
        (tmp_path / "data.bin").write_bytes(b"\x00" * (2 * 1024 * 1024))
        assert tui._dir_size_mb(tmp_path) == 2

    def test_dir_size_mb_nested_files(self, tmp_path):
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "a.bin").write_bytes(b"\x00" * (1 * 1024 * 1024))
        (tmp_path / "b.bin").write_bytes(b"\x00" * (1 * 1024 * 1024))
        assert tui._dir_size_mb(tmp_path) == 2

    def test_dir_size_mb_partial_mib_rounds_down(self, tmp_path):
        # 0.5 MiB → integer division → 0
        (tmp_path / "small.bin").write_bytes(b"\x00" * (512 * 1024))
        assert tui._dir_size_mb(tmp_path) == 0

    def test_free_mb_returns_non_negative_integer(self, tmp_path):
        result = tui._free_mb(tmp_path)
        assert isinstance(result, int)
        assert result >= 0


# ── Terminal styling helpers ───────────────────────────────────────────────────


class TestAnsiHelpers:
    """_ansi and colour helper functions respect the _COLOR flag."""

    def _set_color(self, value):
        original = tui._COLOR
        tui._COLOR = value
        return original

    def test_plain_text_when_color_disabled(self):
        orig = self._set_color(False)
        try:
            assert tui._ansi("1", "hello") == "hello"
            assert tui.bold("world") == "world"
            assert tui.dim("quiet") == "quiet"
            assert tui.red("error") == "error"
            assert tui.green("ok") == "ok"
            assert tui.yellow("warn") == "warn"
        finally:
            tui._COLOR = orig

    def test_escape_codes_present_when_color_enabled(self):
        orig = self._set_color(True)
        try:
            result = tui._ansi("1", "hello")
            assert "\033[1m" in result
            assert "hello" in result
            assert "\033[0m" in result
        finally:
            tui._COLOR = orig

    def test_bold_wraps_in_ansi_1(self):
        orig = self._set_color(True)
        try:
            assert "\033[1m" in tui.bold("x")
        finally:
            tui._COLOR = orig

    def test_red_wraps_in_ansi_31(self):
        orig = self._set_color(True)
        try:
            assert "\033[31m" in tui.red("x")
        finally:
            tui._COLOR = orig

    def test_green_wraps_in_ansi_32(self):
        orig = self._set_color(True)
        try:
            assert "\033[32m" in tui.green("x")
        finally:
            tui._COLOR = orig
