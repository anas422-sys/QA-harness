"""Capture reCheck360 UI Automation controls for locator calibration."""
from __future__ import annotations

from datetime import datetime
import csv
import json
from pathlib import Path

from enterprise_runner import desktop_window


ROOT = Path(__file__).resolve().parent


def main():
    mapping = json.loads((ROOT / "desktop_map.json").read_text(encoding="utf-8-sig"))
    window, error = desktop_window(mapping)
    stamp = datetime.now().astimezone()
    output = ROOT / "reports" / ("calibration_" + stamp.strftime("%Y-%m-%d_%H%M%S"))
    output.mkdir(parents=True)
    if not window:
        result = {"status": "BLOCKED", "blocker": error, "output": str(output.resolve()), "controls": 0}
        (output / "calibration.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result))
        return 1
    controls = []
    for index, control in enumerate(window.descendants()):
        try:
            info = control.element_info
            controls.append({"index": index, "name": info.name or "", "control_type": info.control_type or "",
                             "automation_id": info.automation_id or "", "class_name": info.class_name or "",
                             "rectangle": str(control.rectangle()), "enabled": bool(control.is_enabled()),
                             "visible": bool(control.is_visible())})
        except Exception:
            continue
    with (output / "controls.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(controls[0]) if controls else ["index", "name"])
        writer.writeheader(); writer.writerows(controls)
    screenshot = output / "application.png"
    screenshot_value = ""
    try:
        window.capture_as_image().save(screenshot)
        screenshot_value = str(screenshot)
    except Exception:
        pass
    usable = bool(controls or screenshot_value)
    result = {"status": "PASS" if usable else "BLOCKED",
              "blocker": "" if usable else "JavaFX window was found but it is minimized/off-screen and exposes no automation controls",
              "output": str(output.resolve()), "controls": len(controls),
              "window_title": window.window_text(), "screenshot": screenshot_value}
    (output / "calibration.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    (ROOT / "latest_calibration.txt").write_text(str(output.resolve()), encoding="utf-8")
    print(json.dumps(result))
    return 0 if usable else 1


if __name__ == "__main__":
    raise SystemExit(main())
