from build import safety
import subprocess
import shlex
import sys


def run(cmd):
    subprocess.run(cmd, shell=True, check=True)


def menu():
    print("\n╔══════════════════════════════════╗")
    print("║    SECURE USB TOOLKIT  (TUI)     ║")
    print("╠══════════════════════════════════╣")
    print("║  1. List disks                   ║")
    print("║  2. Create USB layout            ║")
    print("║  3. Create encrypted container   ║")
    print("║  4. Populate tools partition     ║")
    print("║  5. Clone USB                    ║")
    print("║  6. Verify                       ║")
    print("║  7. Exit                         ║")
    print("╚══════════════════════════════════╝")


def main():
    while True:
        menu()
        c = input("\n> ").strip()

        if c == "1":
            safety.print_disks()

        elif c == "2":
            safety.print_disks()
            d = input("  Device (e.g. /dev/sdb or /dev/disk2): ").strip()
            safety.confirm_device(d)
            run(f"cd build && ./create_usb_layout.sh {shlex.quote(d)}")

        elif c == "3":
            run("cd build && ./create_container.sh")

        elif c == "4":
            m = input("  Mount path for tools partition: ").strip()
            run(f"cd build && ./populate_tools_partition.sh {shlex.quote(m)}")

        elif c == "5":
            safety.print_disks()
            s = input("  Source device: ").strip()
            t = input("  Target device: ").strip()
            safety.confirm_device(t)
            run(f"cd build && ./clone_usb.sh {shlex.quote(s)} {shlex.quote(t)}")

        elif c == "6":
            run("cd build && ./verify.sh")

        elif c == "7":
            print("  Goodbye.")
            sys.exit(0)

        else:
            print("  Invalid choice — enter 1–7.")


if __name__ == "__main__":
    main()
