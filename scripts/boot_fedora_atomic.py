#!/usr/bin/env python3
"""Boot Fedora Atomic in QEMU and capture a screenshot."""
from __future__ import annotations

import argparse
import os
import pathlib
import socket
import subprocess
import sys
import time

DEFAULT_BIOS = "/usr/share/qemu-efi-aarch64/QEMU_EFI.fd"
DEFAULT_OUTPUT = pathlib.Path("artifacts/boot")
DEFAULT_SCREENSHOT_NAME = "nova-fedora-atomic.png"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Boot Fedora Atomic in QEMU and capture a screenshot.",
    )
    parser.add_argument("--iso", type=pathlib.Path, required=True, help="Path to the Fedora Atomic ISO")
    parser.add_argument(
        "--bios",
        type=pathlib.Path,
        default=pathlib.Path(DEFAULT_BIOS),
        help=f"AArch64 UEFI firmware image (default: {DEFAULT_BIOS})",
    )
    parser.add_argument(
        "--output",
        type=pathlib.Path,
        default=DEFAULT_OUTPUT,
        help=f"Directory for logs, disk, and screenshots (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument("--memory", type=int, default=4096, help="Guest memory in MiB (default: 4096)")
    parser.add_argument("--smp", type=int, default=4, help="Number of virtual CPUs (default: 4)")
    parser.add_argument(
        "--disk-size",
        default="20G",
        help="Size of the writable qcow2 disk attached to the VM (default: 20G)",
    )
    parser.add_argument(
        "--boot-wait",
        type=float,
        default=90.0,
        help="Seconds to wait before capturing the screenshot (default: 90)",
    )
    parser.add_argument(
        "--screenshot",
        default=DEFAULT_SCREENSHOT_NAME,
        help=f"Filename for the screenshot (default: {DEFAULT_SCREENSHOT_NAME})",
    )
    parser.add_argument(
        "--keep-running",
        action="store_true",
        help="Do not shut down QEMU after capturing the screenshot.",
    )
    return parser.parse_args()


def ensure_exists(path: pathlib.Path, *, description: str) -> pathlib.Path:
    if not path.exists():
        raise FileNotFoundError(f"{description} not found: {path}")
    return path.resolve()


def wait_for_monitor(monitor_path: pathlib.Path, *, timeout: float = 30.0) -> socket.socket:
    deadline = time.time() + timeout
    while time.time() < deadline:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            sock.connect(str(monitor_path))
            sock.settimeout(0.5)
            try:
                sock.recv(4096)
            except socket.timeout:
                pass
            finally:
                sock.settimeout(None)
            return sock
        except (FileNotFoundError, ConnectionRefusedError):
            sock.close()
            time.sleep(0.1)
        except Exception:
            sock.close()
            time.sleep(0.1)
    raise TimeoutError(f"QEMU monitor did not become ready within {timeout} seconds")


def send_monitor_command(sock: socket.socket, command: str) -> str:
    sock.sendall((command + "\n").encode())
    time.sleep(0.1)
    # Try to read available data without blocking indefinitely.
    sock.setblocking(False)
    chunks = []
    try:
        while True:
            data = sock.recv(4096)
            if not data:
                break
            chunks.append(data)
    except BlockingIOError:
        pass
    finally:
        sock.setblocking(True)
    return b"".join(chunks).decode(errors="ignore")


def convert_ppm_to_png(ppm_path: pathlib.Path, png_path: pathlib.Path) -> None:
    subprocess.run(["convert", str(ppm_path), str(png_path)], check=True)


def boot_and_capture(args: argparse.Namespace) -> pathlib.Path:
    iso_path = ensure_exists(args.iso, description="ISO image")
    bios_path = ensure_exists(args.bios, description="UEFI firmware")

    output_dir = args.output.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    monitor_path = output_dir / "qemu-monitor.sock"
    if monitor_path.exists():
        monitor_path.unlink()

    serial_log = output_dir / "serial.log"
    disk_path = output_dir / "nova-os.qcow2"
    screenshot_ppm = output_dir / "screenshot.ppm"
    screenshot_png = output_dir / args.screenshot

    subprocess.run(
        ["qemu-img", "create", "-f", "qcow2", str(disk_path), str(args.disk_size)],
        check=True,
    )

    qemu_cmd = [
        "qemu-system-aarch64",
        "-machine",
        "virt,accel=tcg",
        "-cpu",
        "cortex-a72",
        "-smp",
        str(args.smp),
        "-m",
        f"{args.memory}M",
        "-bios",
        str(bios_path),
        "-display",
        "sdl",
        "-device",
        "virtio-gpu-pci",
        "-device",
        "qemu-xhci",
        "-device",
        "usb-kbd",
        "-device",
        "usb-tablet",
        "-drive",
        f"if=none,media=cdrom,readonly=on,file={iso_path},id=cdrom0",
        "-device",
        "virtio-blk-pci,drive=cdrom0",
        "-drive",
        f"if=none,file={disk_path},format=qcow2,id=nvroot",
        "-device",
        "virtio-blk-pci,drive=nvroot",
        "-monitor",
        f"unix:{monitor_path},server,nowait",
        "-serial",
        f"file:{serial_log}",
        "-no-reboot",
    ]

    env = os.environ.copy()
    env.setdefault("SDL_VIDEODRIVER", "dummy")
    env.setdefault("SDL_AUDIODRIVER", "dummy")

    qemu_proc = subprocess.Popen(
        qemu_cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
    )

    try:
        monitor_sock = wait_for_monitor(monitor_path)
    except Exception:
        qemu_proc.kill()
        raise RuntimeError("QEMU monitor did not start.")

    try:
        time.sleep(args.boot_wait)
        send_monitor_command(monitor_sock, f"screendump {screenshot_ppm}")
        convert_ppm_to_png(screenshot_ppm, screenshot_png)
    finally:
        if not args.keep_running:
            send_monitor_command(monitor_sock, "quit")
            monitor_sock.close()
            try:
                qemu_proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                qemu_proc.kill()
        else:
            monitor_sock.close()

    return screenshot_png


def main() -> int:
    args = parse_args()
    try:
        screenshot_path = boot_and_capture(args)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as exc:
        print(f"Command failed: {exc.cmd}\nExit status: {exc.returncode}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Failed to boot Fedora Atomic: {exc}", file=sys.stderr)
        return 1

    print(f"Screenshot saved to {screenshot_path}")
    print(f"Serial log saved to {args.output / 'serial.log'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
