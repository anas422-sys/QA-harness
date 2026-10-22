"""Extract packaged JavaFX views and control metadata from the installed reCheck360 JAR."""
from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
import re
import xml.etree.ElementTree as ET
import zipfile


ROOT = Path(__file__).resolve().parent
JAR = Path("C:/Program Files/reCheck360/app/app.jar")


def words(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("-", " ").replace("_", " ")).strip().title()


def main():
    if not JAR.is_file():
        raise SystemExit(f"Installed app JAR not found: {JAR}")
    views = []
    with zipfile.ZipFile(JAR) as archive:
        names = [name for name in archive.namelist()
                 if name.startswith("views/") and name.lower().endswith(".fxml")]
        for name in sorted(names):
            raw = archive.read(name)
            try:
                root = ET.fromstring(raw)
            except ET.ParseError:
                continue
            controls = []
            labels = []
            actions = []
            for element in root.iter():
                tag = element.tag.rsplit("}", 1)[-1]
                fx_id = element.attrib.get("{http://javafx.com/fxml/1}id", "")
                text = element.attrib.get("text", "")
                action = element.attrib.get("onAction", "")
                if fx_id or text or action:
                    controls.append({"type": tag, "fx_id": fx_id, "text": text, "action": action})
                if text and not text.startswith("%") and len(text) <= 100:
                    labels.append(text)
                if action:
                    actions.append(action.lstrip("#"))
            rel = PurePosixPath(name).relative_to("views")
            view_id = str(rel.with_suffix("")).replace("/", "__")
            category = "Control Center" if str(rel).startswith("controlcenter/") else (
                "Popup" if str(rel).startswith("popups/") or "dialog" in rel.stem else "Application")
            views.append({
                "id": view_id,
                "name": words(rel.stem),
                "category": category,
                "resource": name,
                "control_count": len(controls),
                "controls": controls,
                "expected_text": list(dict.fromkeys(labels))[:12],
                "actions": list(dict.fromkeys(actions)),
            })
    contract = {"source": str(JAR), "framework": "JavaFX/FXML", "view_count": len(views), "views": views}
    (ROOT / "application_contract.json").write_text(json.dumps(contract, indent=2), encoding="utf-8")
    print(json.dumps({"output": str((ROOT / 'application_contract.json').resolve()), "views": len(views),
                      "controls": sum(view["control_count"] for view in views)}))


if __name__ == "__main__":
    main()
