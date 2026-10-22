"""Local enterprise QA control panel for reCheck360."""
from __future__ import annotations

from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import sys
import threading
from urllib.parse import urlparse

from device_inventory import discover

ROOT = Path(__file__).resolve().parent
WORKSPACE = ROOT.parent
STATE_LOCK = threading.Lock()
STATE = {"running": False, "module": "", "started_at": None, "finished_at": None,
         "exit_code": None, "error": "", "log": ""}


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return default


def test_catalog():
    catalog = read_json(ROOT / "test_catalog.json", {"frontend": {"pages": []}, "backend": {"features": []}})
    existing = {item["id"] for item in catalog["frontend"]["pages"]}
    contract = read_json(ROOT / "application_contract.json", {})
    for view in contract.get("views", []):
        if view["id"] in existing:
            continue
        catalog["frontend"]["pages"].append({
            "id": view["id"], "name": view["name"],
            "description": f"{view['category']} · {view['resource']} · {view['control_count']} packaged controls",
            "tests": ["navigate", "page_visible", "controls_enabled", "actions_available", "screenshot"],
        })
    return catalog


def latest_data():
    try:
        raw = (ROOT / "latest_report.txt").read_text(encoding="utf-8").strip()
        folder = Path(raw) if raw else None
    except OSError:
        folder = None
    if folder and folder.is_dir():
        data = read_json(folder / "results.json", {})
        return {"folder": str(folder), "report": data}
    return {"folder": "", "report": {}}


def execute(selection: dict):
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    selection_file = ROOT / f"selection_{stamp}.json"
    selection_file.write_text(json.dumps(selection, indent=2), encoding="utf-8")
    modules = []
    if selection.get("frontend_pages"):
        modules.append("Frontend")
    if selection.get("backend_features"):
        modules.append("Backend")
    with STATE_LOCK:
        STATE.update(running=True, module=" + ".join(modules),
                     started_at=datetime.now().astimezone().isoformat(timespec="seconds"),
                     finished_at=None, exit_code=None, error="", log="")
    try:
        done = subprocess.run(
            [sys.executable, str(ROOT / "enterprise_runner.py"), "--selection", str(selection_file)],
            cwd=WORKSPACE, capture_output=True, text=True, timeout=3600,
        )
        with STATE_LOCK:
            STATE["exit_code"] = done.returncode
            STATE["log"] = (done.stdout + "\n" + done.stderr)[-8000:]
            if done.returncode not in (0, 1):
                STATE["error"] = STATE["log"]
    except Exception as exc:
        with STATE_LOCK:
            STATE["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        selection_file.unlink(missing_ok=True)
        with STATE_LOCK:
            STATE["running"] = False
            STATE["finished_at"] = datetime.now().astimezone().isoformat(timespec="seconds")


HTML = r'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>reCheck360 Enterprise QA</title><style>
:root{--navy:#17365d;--teal:#00a99d;--bg:#f3f6fa;--line:#d8e0ea;--red:#b42318;--green:#17803d;--orange:#b54708;--muted:#667085}*{box-sizing:border-box}body{margin:0;background:var(--bg);font:14px Segoe UI,Arial;color:#172b4d}header{background:var(--navy);color:white;padding:22px 30px}header h1{margin:0 0 5px}main{max-width:1450px;margin:auto;padding:24px}.tabs{display:flex;gap:10px;margin-bottom:18px}.tab{font-size:16px;padding:12px 22px}.tab.active{background:var(--teal)}button{border:0;background:var(--navy);color:white;border-radius:7px;padding:9px 14px;font-weight:700;cursor:pointer}button:disabled{opacity:.5}.panel,.card,table{background:white;border:1px solid var(--line);border-radius:10px}.panel{padding:18px;margin-bottom:16px}.hidden{display:none}.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(285px,1fr));gap:12px}.choice{border:1px solid var(--line);padding:13px;border-radius:8px;display:flex;gap:10px;align-items:flex-start}.choice input{margin-top:4px}.choice b,.choice small{display:block}.choice small{color:var(--muted);margin-top:4px}.bar{display:flex;gap:12px;align-items:center;flex-wrap:wrap}.bar label{font-weight:600}.bar input{padding:8px;border:1px solid var(--line);border-radius:6px;width:110px}.bar .wide{width:360px}.primary{background:var(--teal);font-size:15px;padding:11px 20px}.start-btn{background:#16a34a;color:white;font-size:15px;padding:11px 24px;border-radius:8px;font-weight:700;display:inline-flex;align-items:center;gap:8px;cursor:pointer;border:0;box-shadow:0 3px 10px rgba(22,163,74,0.35);transition:all .15s ease}.start-btn:hover{background:#15803d;transform:translateY(-1px)}.start-btn:active{transform:translateY(0)}.start-btn:disabled{opacity:.6;cursor:not-allowed;transform:none}.cards{display:flex;gap:10px;flex-wrap:wrap;margin:16px 0}.card{padding:13px;min-width:135px}.card small,.card strong{display:block}.card strong{font-size:23px;margin-top:4px}.error{color:var(--red);font-weight:700}.notice{padding:12px;border-left:4px solid var(--orange);background:#fff8e6;margin-top:12px}table{width:100%;border-collapse:collapse;overflow:hidden}th{background:var(--navy);color:white;text-align:left}th,td{padding:8px;border:1px solid var(--line);vertical-align:top}.PASS{color:var(--green);font-weight:700}.FAIL,.ERROR,.TIMEOUT{color:var(--red);font-weight:700}.BLOCKED{color:var(--orange);font-weight:700}.device{font-family:Consolas,monospace;font-size:12px}@media(max-width:700px){.wide{max-width:100%}table{display:block;overflow:auto}}
</style></head><body><header style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:14px"><div><h1>reCheck360 Enterprise QA Harness</h1><div>Windows desktop automation · staging API/WebSocket contracts · up to 20 physical USB devices</div></div><button class="start-btn" id="startHeaderBtn" onclick="startAll()"><svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg><span>Start All Tests</span></button></header><main>
<div class="tabs" style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px">
<div style="display:flex;gap:10px"><button class="tab active" id="frontTab" onclick="showModule('front')">Frontend Desktop</button><button class="tab" id="backTab" onclick="showModule('back')">Backend & Load</button><button class="tab" id="resultTab" onclick="showModule('result')">Logs & Results</button></div>
<button class="start-btn" id="startTabsBtn" onclick="startAll()"><svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg><span>Start All Tests</span></button>
</div>
<section id="front" class="panel"><h2>Select desktop pages</h2><p>Selected workflows run against the installed reCheck360 Windows application. Each page captures navigation time, visible markers, screenshot evidence and blockers.</p><div id="frontChoices" class="grid"></div><div class="bar" style="margin-top:16px"><button onclick="allChecks('frontChoices',true)">Select all pages</button><button onclick="allChecks('frontChoices',false)">Clear</button><button onclick="calibrate()">Discover visible app controls</button><label><input type="checkbox" id="requireDevices"> Require connected devices</label><button class="primary" onclick="run('frontend')">Run selected frontend tests</button></div><div id="calibration"></div></section>
<section id="back" class="panel hidden"><h2>Select backend features and payloads</h2><div id="backChoices" class="grid"></div><div class="bar" style="margin-top:16px"><button onclick="allChecks('backChoices',true)">Select all features</button><button onclick="allChecks('backChoices',false)">Clear</button><label>Timeout <input id="timeout" type="number" min="1" max="300" value="40"> sec</label><label>Sessions <input id="users" type="number" min="1" max="100" value="1"></label><label>Device limit <input id="deviceLimit" type="number" min="1" max="20" value="20"></label><label>Captured payload JSON <input id="payload" class="wide" placeholder="C:\path\payloads.json"></label><button class="primary" onclick="run('backend')">Run selected backend tests</button></div><div class="notice">Real-device contracts use captured payloads. The runner will not claim a physical diagnostic PASS from invented device data.</div></section>
<section id="result" class="panel hidden"><div class="bar"><button class="start-btn" onclick="startAll()" style="padding:8px 16px;font-size:13px"><svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg><span>Start All Tests</span></button><button onclick="refresh()">Refresh</button><button onclick="clearTables()" style="background:#b42318;color:white;border-radius:7px;padding:8px 16px;border:0;font-weight:700;cursor:pointer">Clear Tables</button><a href="/report/results.csv" target="_blank">Download CSV</a><a href="/report/results.json" target="_blank">Download JSON</a><a href="/report/dashboard.html" target="_blank">Open HTML report</a><span id="state"></span><span id="error" class="error"></span></div><h3>USB device inventory</h3><div id="devices"></div><div id="summary" class="cards"></div><div id="results"></div></section>
</main><script>
let catalog={};const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
async function api(path,opt){const r=await fetch(path,opt);const j=await r.json();if(!r.ok)throw Error(j.error||r.statusText);return j}
function showModule(id){['front','back','result'].forEach(x=>document.querySelector('#'+x).classList.toggle('hidden',x!==id));['frontTab','backTab','resultTab'].forEach(x=>document.querySelector('#'+x).classList.remove('active'));document.querySelector('#'+({front:'frontTab',back:'backTab',result:'resultTab'}[id])).classList.add('active');if(id==='result')refresh()}
function choices(){document.querySelector('#frontChoices').innerHTML=catalog.frontend.pages.map(p=>`<label class=choice><input type=checkbox value="${esc(p.id)}"><span><b>${esc(p.name)}</b><small>${esc(p.description)}</small><small>${esc(p.tests.join(' · '))}</small></span></label>`).join('');document.querySelector('#backChoices').innerHTML=catalog.backend.features.map(p=>`<label class=choice><input type=checkbox value="${esc(p.id)}" ${p.safe_default?'checked':''}><span><b>${esc(p.name)}</b><small>${esc(p.transport)}${p.message_types?' · messages '+p.message_types.join(', '):''}</small></span></label>`).join('')}
function allChecks(id,v){document.querySelectorAll('#'+id+' input[type=checkbox]').forEach(x=>x.checked=v)}function selected(id){return [...document.querySelectorAll('#'+id+' input:checked')].map(x=>x.value)}
async function run(module){const body={frontend_pages:module==='frontend'?selected('frontChoices'):[],backend_features:module==='backend'?selected('backChoices'):[],timeout_seconds:Number(document.querySelector('#timeout').value),users:Number(document.querySelector('#users').value),device_limit:Number(document.querySelector('#deviceLimit').value),payload_file:document.querySelector('#payload').value,require_devices:document.querySelector('#requireDevices').checked};if(!(body.frontend_pages.length||body.backend_features.length)){alert('Select at least one page or feature');return}try{await api('/api/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});showModule('result');refresh()}catch(e){alert(e.message)}}
function updateStartButtons(running){document.querySelectorAll('#startHeaderBtn, #startTabsBtn').forEach(b=>{b.disabled=running;b.innerHTML=running?'<span>⏳ Running Tests…</span>':'<svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg><span>Start All Tests</span>'})}
async function startAll(){let front=selected('frontChoices');let back=selected('backChoices');if(!front.length){allChecks('frontChoices',true);front=selected('frontChoices')}if(!back.length){allChecks('backChoices',true);back=selected('backChoices')}const body={frontend_pages:front,backend_features:back,timeout_seconds:Number(document.querySelector('#timeout')?.value||40),users:Number(document.querySelector('#users')?.value||1),device_limit:Number(document.querySelector('#deviceLimit')?.value||20),payload_file:document.querySelector('#payload')?.value||'',require_devices:Boolean(document.querySelector('#requireDevices')?.checked)};try{updateStartButtons(true);await api('/api/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});showModule('result');refresh()}catch(e){alert(e.message);refresh()}}
async function clearTables(){try{await api('/api/clear',{method:'POST'});document.querySelector('#summary').innerHTML='';document.querySelector('#results').innerHTML='<p>No enterprise run has completed yet.</p>';document.querySelector('#state').textContent='Tables cleared';document.querySelector('#error').textContent='';refresh()}catch(e){alert(e.message)}}
async function calibrate(){const box=document.querySelector('#calibration');box.innerHTML='<div class=notice>Inspecting the visible reCheck360 window…</div>';try{const d=await api('/api/calibrate',{method:'POST'});box.innerHTML=`<div class=notice><b>${esc(d.status)}</b> · controls: ${esc(d.controls)} · ${esc(d.output||d.blocker)}</div>`}catch(e){box.innerHTML=`<div class=notice>${esc(e.message)}</div>`}}
function deviceTable(d){const rows=d.devices.map(x=>`<tr><td>${esc(x.name)}</td><td>${esc(x.platform)}</td><td class=device>${esc(x.udid||x.serial_number||'—')}</td><td class=device>${esc(x.imei_1||'—')}</td><td class=device>${esc(x.imei_2||'—')}</td><td>${esc(x.model)}</td><td>${esc(x.state)}</td></tr>`).join('');return `<div class=cards><div class=card><small>Total</small><strong>${d.counts.total}</strong></div><div class=card><small>Android</small><strong>${d.counts.android}</strong></div><div class=card><small>iOS</small><strong>${d.counts.ios}</strong></div><div class=card><small>Capacity</small><strong>${d.counts.capacity}</strong></div></div>${d.blockers.map(x=>`<div class=notice>${esc(x)}</div>`).join('')}<table><tr><th>Device</th><th>Platform</th><th>UDID / Serial</th><th>IMEI 1</th><th>IMEI 2</th><th>Model</th><th>State</th></tr>${rows||'<tr><td colspan=7>No physical devices detected by configured tools</td></tr>'}</table>`}
function resultTable(rows){if(!rows?.length)return '<p>No enterprise run has completed yet.</p>';return `<table><tr><th>Module</th><th>Group</th><th>Test</th><th>Status</th><th>ms</th><th>UDID / Serial</th><th>IMEI 1</th><th>IMEI 2</th><th>Sent</th><th>Received</th><th>Details / blocker</th></tr>${rows.map(r=>`<tr><td>${esc(r.module)}</td><td>${esc(r.group)}</td><td>${esc(r.test)}</td><td class="${esc(r.status)}">${esc(r.status)}</td><td>${esc(r.duration_ms)}</td><td class=device>${esc(r.udid||r.device||'—')}</td><td class=device>${esc(r.imei_1||'—')}</td><td class=device>${esc(r.imei_2||'—')}</td><td>${esc(r.messages_sent)}</td><td>${esc(r.messages_received)}</td><td>${esc(r.details)}${r.blocker?'<br><b>Blocker:</b> '+esc(r.blocker):''}${r.evidence?'<br><small>'+esc(r.evidence)+'</small>':''}</td></tr>`).join('')}</table>`}
async function refresh(){try{const d=await api('/api/status');updateStartButtons(Boolean(d.state.running));document.querySelector('#state').textContent=d.state.running?`Running ${d.state.module} since ${d.state.started_at}`:`Ready · latest: ${d.data.report.started_at||'none'} · ${d.data.folder||''}`;document.querySelector('#error').textContent=d.state.error||'';document.querySelector('#devices').innerHTML=deviceTable(d.inventory);const s=d.data.report.summary||{};let cardsHtml='';for(const [k,v] of Object.entries(s)){if(typeof v==='object')continue;cardsHtml+=`<div class=card><small>${esc(k.replaceAll('_',' '))}</small><strong>${esc(v)}</strong></div>`;if(k==='duration_ms'){const ms=Number(v)||0;if(!('duration_seconds' in s))cardsHtml+=`<div class=card><small>duration seconds</small><strong>${(ms/1000).toFixed(2)}</strong></div>`;if(!('duration_minutes' in s))cardsHtml+=`<div class=card><small>duration minutes</small><strong>${(ms/60000).toFixed(2)}</strong></div>`}}document.querySelector('#summary').innerHTML=cardsHtml;document.querySelector('#results').innerHTML=resultTable(d.data.report.results)}catch(e){document.querySelector('#error').textContent=e.message}}
async function init(){const d=await api('/api/catalog');catalog=d;choices();refresh()}init();setInterval(()=>{if(!document.querySelector('#result').classList.contains('hidden'))refresh()},2500);
</script></body></html>'''


class Handler(BaseHTTPRequestHandler):
    def send_json(self, value, status=200):
        body = json.dumps(value).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            body = HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        report_files = {"/report/results.csv": ("results.csv", "text/csv; charset=utf-8"),
                        "/report/results.json": ("results.json", "application/json; charset=utf-8"),
                        "/report/dashboard.html": ("dashboard.html", "text/html; charset=utf-8")}
        if path in report_files:
            latest = latest_data().get("folder", "")
            filename, content_type = report_files[path]
            source = Path(latest) / filename if latest else Path()
            if not latest or not source.is_file():
                self.send_json({"error": "No completed enterprise report is available"}, 404)
                return
            body = source.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Content-Disposition", f'inline; filename="{filename}"')
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/api/catalog":
            self.send_json(test_catalog())
            return
        if path == "/api/devices":
            self.send_json(discover(read_json(ROOT / "config.json", {})))
            return
        if path == "/api/status":
            with STATE_LOCK:
                state = dict(STATE)
            self.send_json({"state": state, "inventory": discover(read_json(ROOT / "config.json", {})),
                            "data": latest_data()})
            return
        self.send_json({"error": "Not found"}, 404)

    def do_POST(self):
        request_path = urlparse(self.path).path
        if request_path == "/api/calibrate":
            try:
                done = subprocess.run([sys.executable, str(ROOT / "calibrate_desktop.py")], cwd=WORKSPACE,
                                      capture_output=True, text=True, timeout=90)
                lines = [line for line in done.stdout.splitlines() if line.strip()]
                data = json.loads(lines[-1]) if lines else {"status": "ERROR", "blocker": done.stderr[-2000:]}
                self.send_json(data, 200 if data.get("status") == "PASS" else 409)
            except Exception as exc:
                self.send_json({"error": f"{type(exc).__name__}: {exc}"}, 500)
            return
        if request_path == "/api/clear":
            try:
                (ROOT / "latest_report.txt").unlink(missing_ok=True)
                with STATE_LOCK:
                    STATE.update(running=False, module="", started_at=None, finished_at=None,
                                 exit_code=None, error="", log="")
                self.send_json({"cleared": True}, 200)
            except Exception as exc:
                self.send_json({"error": f"{type(exc).__name__}: {exc}"}, 500)
            return
        if request_path != "/api/run":
            self.send_json({"error": "Not found"}, 404)
            return
        with STATE_LOCK:
            if STATE["running"]:
                self.send_json({"error": "A test run is already active"}, 409)
                return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            data = json.loads(self.rfile.read(length))
            catalog = test_catalog()
            valid_pages = {item["id"] for item in catalog["frontend"]["pages"]}
            valid_features = {item["id"] for item in catalog["backend"]["features"]}
            if not set(data.get("frontend_pages", [])).issubset(valid_pages):
                raise ValueError("Unknown frontend page")
            if not set(data.get("backend_features", [])).issubset(valid_features):
                raise ValueError("Unknown backend feature")
            if not data.get("frontend_pages") and not data.get("backend_features"):
                raise ValueError("Select at least one test")
            data["timeout_seconds"] = max(1, min(300, int(data.get("timeout_seconds", 40))))
            data["users"] = max(1, min(100, int(data.get("users", 1))))
            data["device_limit"] = max(1, min(20, int(data.get("device_limit", 20))))
            threading.Thread(target=execute, args=(data,), daemon=True).start()
            self.send_json({"started": True}, 202)
        except (ValueError, TypeError, json.JSONDecodeError, KeyError) as exc:
            self.send_json({"error": str(exc)}, 400)

    def log_message(self, fmt, *args):
        pass


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if args.host not in ("127.0.0.1", "localhost"):
        raise SystemExit("Harness is restricted to localhost")
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"reCheck360 Enterprise QA Harness: http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
