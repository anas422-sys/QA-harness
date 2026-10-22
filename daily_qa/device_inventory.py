"""Discover physical Android and iOS devices connected to this Windows host."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any


def _tool(config: dict[str, Any], name: str, candidates: list[Path]) -> str | None:
    configured = str(config.get("device_tools", {}).get(name, "")).strip()
    if configured and Path(configured).is_file():
        return configured
    found = shutil.which(name) or shutil.which(name + ".exe")
    if found:
        return found
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return None


def tool_paths(config: dict[str, Any]) -> dict[str, str | None]:
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    program_files = Path(os.environ.get("ProgramFiles", "C:/Program Files"))
    program_files_x86 = Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)"))
    return {
        "adb": _tool(config, "adb", [
            Path("C:/Program Files/reCheck360/app/native-dev/windows/adb.exe"),
            local / "Android/Sdk/platform-tools/adb.exe",
            Path("C:/Android/platform-tools/adb.exe"),
        ]),
        "idevice_id": _tool(config, "idevice_id", [
            Path("C:/Program Files/reCheck360/app/native-dev/windows/idevice_id.exe"),
            program_files / "libimobiledevice/idevice_id.exe",
            program_files_x86 / "libimobiledevice/idevice_id.exe",
        ]),
        "ideviceinfo": _tool(config, "ideviceinfo", [
            Path("C:/Program Files/reCheck360/app/native-dev/windows/ideviceinfo.exe"),
            program_files / "libimobiledevice/ideviceinfo.exe",
            program_files_x86 / "libimobiledevice/ideviceinfo.exe",
        ]),
    }


def _run(command: list[str], timeout: int = 12) -> tuple[int, str, str]:
    try:
        done = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        return done.returncode, done.stdout.strip(), done.stderr.strip()
    except Exception as exc:
        return -1, "", f"{type(exc).__name__}: {exc}"


def _android(adb: str | None) -> tuple[list[dict[str, Any]], list[str]]:
    if not adb:
        return [], ["Android tooling unavailable: configure device_tools.adb or install Android platform-tools"]
    code, output, error = _run([adb, "devices", "-l"])
    if code:
        return [], [f"adb devices failed: {error or output}"]
    devices = []
    for line in output.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 2 or parts[1] != "device":
            continue
        attributes = dict(token.split(":", 1) for token in parts[2:] if ":" in token)
        devices.append({
            "platform": "android",
            "id": parts[0],
            "udid": parts[0],
            "serial_number": parts[0],
            "name": attributes.get("model", attributes.get("device", "Android Device")).replace("_", " "),
            "model": attributes.get("model", ""),
            "state": "connected",
            "transport": attributes.get("transport_id", ""),
        })
    return devices, []


def _ios(idevice_id: str | None, ideviceinfo: str | None) -> tuple[list[dict[str, Any]], list[str]]:
    if not idevice_id:
        return [], ["iOS tooling unavailable: configure device_tools.idevice_id or install libimobiledevice"]
    code, output, error = _run([idevice_id, "-l"])
    if code and "unknown option" in error.lower():
        code, output, error = _run([idevice_id])
    if code and (output or error):
        return [], [f"idevice_id failed: {error or output}"]
    devices = []
    for udid in [line.strip() for line in output.splitlines() if line.strip()]:
        values: dict[str, str] = {}
        if ideviceinfo:
            for key in ("DeviceName", "ProductType", "ProductVersion", "SerialNumber"):
                _, value, _ = _run([ideviceinfo, "-u", udid, "-k", key], timeout=8)
                values[key] = value
        devices.append({
            "platform": "ios",
            "id": udid,
            "udid": udid,
            "serial_number": values.get("SerialNumber", ""),
            "name": values.get("DeviceName") or values.get("ProductType") or "Apple iOS Device",
            "model": values.get("ProductType", ""),
            "os_version": values.get("ProductVersion", ""),
            "state": "connected",
            "transport": "usb",
        })
    return devices, []


def discover(config: dict[str, Any]) -> dict[str, Any]:
    paths = tool_paths(config)
    android, android_issues = _android(paths["adb"])
    ios, ios_issues = _ios(paths["idevice_id"], paths["ideviceinfo"])
    devices = android + ios
    maximum = int(config.get("maximum_real_devices", 20))
    return {
        "devices": devices[:maximum],
        "counts": {
            "total": len(devices),
            "android": len(android),
            "ios": len(ios),
            "selected": min(len(devices), maximum),
            "capacity": maximum,
        },
        "tools": {name: path or "" for name, path in paths.items()},
        "blockers": android_issues + ios_issues,
    }


if __name__ == "__main__":
    root = Path(__file__).resolve().parent
    cfg = json.loads((root / "config.json").read_text(encoding="utf-8-sig"))
    print(json.dumps(discover(cfg), indent=2))
