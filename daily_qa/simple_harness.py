"""Clear four-mode local QA harness for reCheck360."""
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
LOCK = threading.Lock()
STATE = {"running": False, "mode": "", "started_at": None, "finished_at": None,
         "exit_code": None, "error": ""}


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return default


def catalog():
    base = read_json(ROOT / "test_catalog.json", {"frontend": {"pages": []}})
    existing = {item["id"] for item in base["frontend"]["pages"]}
    for view in read_json(ROOT / "application_contract.json", {}).get("views", []):
        if view["id"] not in existing:
            base["frontend"]["pages"].append({"id": view["id"], "name": view["name"],
                "description": f"{view['category']} · {view['control_count']} packaged controls", "tests": []})
    return base


def latest():
    try:
        folder = Path((ROOT / "latest_report.txt").read_text(encoding="utf-8").strip())
    except OSError:
        folder = Path()
    return {"folder": str(folder) if folder.is_dir() else "",
            "report": read_json(folder / "results.json", {}) if folder.is_dir() else {}}


def run_selection(selection: dict):
    temp = ROOT / ("selection_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f") + ".json")
    temp.write_text(json.dumps(selection, indent=2), encoding="utf-8")
    with LOCK:
        STATE.update(running=True, mode=selection["mode"],
                     started_at=datetime.now().astimezone().isoformat(timespec="seconds"),
                     finished_at=None, exit_code=None, error="")
    try:
        done = subprocess.run([sys.executable, str(ROOT / "enterprise_runner.py"), "--selection", str(temp)],
                              cwd=WORKSPACE, capture_output=True, text=True, timeout=3600)
        with LOCK:
            STATE["exit_code"] = done.returncode
            if done.returncode not in (0, 1):
                STATE["error"] = (done.stderr or done.stdout)[-4000:]
    except Exception as exc:
        with LOCK:
            STATE["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        temp.unlink(missing_ok=True)
        with LOCK:
            STATE["running"] = False
            STATE["finished_at"] = datetime.now().astimezone().isoformat(timespec="seconds")


HTML = r'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>reCheck360 QA</title><style>
:root{--navy:#17365d;--teal:#00aa9b;--bg:#f4f7fb;--line:#d7e0ea;--muted:#667085;--red:#b42318;--green:#17803d;--orange:#b54708;--blue:#175cd3}*{box-sizing:border-box}body{margin:0;background:var(--bg);font:14px Segoe UI,Arial;color:#172b4d}header{background:var(--navy);color:white;padding:22px 30px}header h1{margin:0 0 4px}main{max-width:1450px;margin:auto;padding:24px}.toptabs{display:flex;gap:10px;background:white;border:1px solid var(--line);border-radius:12px;padding:10px;position:sticky;top:0;z-index:3}.toptabs button{flex:1;border:0;border-radius:8px;background:#eef2f6;color:#172b4d;padding:14px;font-size:17px;font-weight:750}.toptabs button.active{background:var(--teal);color:white}.tabpage{display:block}.panel{background:white;border:1px solid var(--line);border-radius:12px;padding:20px;margin-top:16px}.panel h2{margin-top:0}.hidden{display:none}.step{display:inline-block;background:var(--navy);color:white;border-radius:14px;padding:4px 10px;font-size:12px;margin-right:7px}.bar{display:flex;gap:12px;align-items:end;flex-wrap:wrap}.bar label{font-weight:650}.bar input{display:block;margin-top:5px;padding:9px;border:1px solid var(--line);border-radius:7px;width:120px}.bar .path{width:480px}.run{background:var(--teal);color:white;border:0;border-radius:8px;padding:11px 19px;font-weight:750;cursor:pointer}button{cursor:pointer}.note{background:#eef8ff;border-left:4px solid var(--blue);padding:12px;margin:14px 0}.warn{background:#fff8e6;border-left-color:var(--orange)}.devices,.cards{display:flex;gap:10px;flex-wrap:wrap}.card{background:white;border:1px solid var(--line);border-radius:9px;padding:12px;min-width:125px}.card small,.card b{display:block}.card b{font-size:22px;margin-top:4px}.pagebox{max-height:310px;overflow:auto;border:1px solid var(--line);padding:10px;border-radius:8px;display:grid;grid-template-columns:repeat(3,1fr);gap:6px}.pagebox label{padding:7px;background:#f8fafc}.resulttabs{display:flex;gap:8px;margin:18px 0}.resulttabs button,.minor{border:1px solid var(--line);background:white;border-radius:7px;padding:8px 12px}.resulttabs button.active{background:var(--navy);color:white}table{width:100%;border-collapse:collapse;background:white}th{background:var(--navy);color:white;text-align:left}th,td{border:1px solid var(--line);padding:8px;vertical-align:top}.PASS,.CONNECTED{color:var(--green);font-weight:750}.ACKNOWLEDGED{color:var(--blue);font-weight:750}.FAIL,.ERROR,.TIMEOUT,.REJECTED{color:var(--red);font-weight:750}.BLOCKED{color:var(--orange);font-weight:750}.mono{font:12px Consolas,monospace;word-break:break-all}.error{color:var(--red);font-weight:700}@media(max-width:900px){.toptabs{position:static}.pagebox{grid-template-columns:1fr}.bar .path{width:100%}} 
</style></head><body><header><h1>reCheck360 QA Harness</h1><div>Choose one test type. Every result states exactly what was verified.</div></header><main>
<nav class="toptabs"><button id="frontendButton" class="active" onclick="showTab('frontendTab',this)">Frontend</button><button id="backendButton" onclick="showTab('backendTab',this)">Backend</button><button id="logsButton" onclick="showTab('logsTab',this)">Logs & Results</button></nav>
<div id="frontendTab" class="tabpage"><section id="real" class="panel"><h2><span class="step">Frontend 1</span>Real USB Devices</h2><div class="note">This section uses actual Android serial numbers and iOS UDIDs returned by the USB tools bundled with reCheck360.</div><div id="inventory"></div><div class="bar"><label>Required real devices<input id="realCount" type="number" value="20" min="1" max="20"></label><label>Optional matching payload file<input id="realFile" class="path" placeholder="Leave empty for connection verification only"></label><label>Timeout seconds<input id="realTimeout" type="number" value="40" min="1" max="300"></label><button class="minor" onclick="refresh()">Refresh Devices</button><button class="run" onclick="runReal()">Test Real Devices</button></div></section><section id="desktop" class="panel"><h2><span class="step">Frontend 2</span>Desktop Application Pages</h2><div class="note">Choose reCheck360 pages. Packaged-view checks and live Windows navigation are shown as separate results.</div><div class="bar" style="margin-bottom:10px"><button class="minor" onclick="selectCore()">Core Pages</button><button class="minor" onclick="selectAllPages()">All Pages</button><button class="minor" onclick="clearPages()">Clear</button><button class="run" onclick="runDesktop()">Test Selected Pages</button></div><div id="pages" class="pagebox"></div></section></div>
<div id="backendTab" class="tabpage hidden"><section id="fullLoad" class="panel"><h2><span class="step">Backend 1</span>Full 15-Device Protocol Load</h2><div class="note"><b>Three sequential phases:</b> devices 1-5, then 6-10, then 11-15. Five devices run concurrently inside each phase. Every iOS device sends message types 1 through 8, for 120 WebSocket payloads total.</div><div class="bar"><label>Timeout per message<input id="batchTimeout" type="number" value="40" min="1" max="300"></label><button class="run" onclick="runFixedBatch()">Run Full 15-Device Test</button></div></section><section id="fixedProtocol" class="panel"><h2><span class="step">Backend 2</span>Single iOS Device Protocol</h2><div class="note"><b>Exactly 8 messages per device:</b> 1 Connect, 2 Device Info Result, 3 Battery Request, 4 Battery Result, 5 OEM Request, 6 OEM Result, 7 Validation Request, 8 Validation Result. Login (134), app version (119), and old-device lookup (139) are setup messages and are not counted in these eight.</div><div class="bar"><label>Timeout per message<input id="fixedTimeout" type="number" value="40" min="1" max="300"></label><button class="run" onclick="runFixedProtocol()">Run Fixed 8 Messages</button></div></section><section id="messages" class="panel"><h2><span class="step">Backend 3</span>Custom API / WebSocket Log</h2><div class="note">Use this only when you need to replay another log. PASS requires the same message type and reference, successful status, and matching UDID when supplied.</div><div class="bar"><label>Payload or application log<input id="msgFile" class="path" placeholder="C:\path\messages.json or application.log"></label><label>Maximum messages<input id="maxMessages" type="number" value="500" min="1" max="500"></label><label>Timeout seconds<input id="msgTimeout" type="number" value="40" min="1" max="300"></label><button class="run" onclick="runMessages()">Run Custom Log</button></div></section><section id="dummy" class="panel"><h2><span class="step">Backend 4</span>Dummy Device Connect Load</h2><div class="note warn"><b>Accuracy rule:</b> ACKNOWLEDGED means staging accepted a synthetic payload. It does not mean physical hardware passed.</div><div class="bar"><label>Dummy iOS<input id="dummyIos" type="number" value="10" min="0" max="20"></label><label>Dummy Android<input id="dummyAndroid" type="number" value="10" min="0" max="20"></label><label>Rounds per device<input id="dummyRounds" type="number" value="1" min="1" max="20"></label><label>Timeout seconds<input id="dummyTimeout" type="number" value="40" min="1" max="300"></label><button class="run" onclick="runDummy()">Run Dummy Load</button></div></section></div>
<div id="logsTab" class="tabpage hidden"><section class="panel"><div class="bar"><h2 style="margin:0">Logs & Results</h2><span id="state"></span><span id="error" class="error"></span><a href="/report/batch_summary.csv" target="_blank">Batch Summary</a><a href="/report/device_summary.csv" target="_blank">Device Summary</a><a href="/report/results.csv" target="_blank">All Tests CSV</a><a href="/report/api_calls.csv" target="_blank">API Calls CSV</a><a href="/report/messages_sent.csv" target="_blank">Sent CSV</a><a href="/report/messages_received.csv" target="_blank">Received CSV</a><a href="/report/messages_readable.log" target="_blank">Readable Log</a><a href="/report/results.json" target="_blank">Full JSON</a></div><div class="note">API Calls shows every HTTP and WebSocket request with its response, status and duration. Test Results identifies the batch, device name, UDID and each of its eight protocol messages.</div><div id="summary" class="cards"></div><div class="resulttabs"><button data-kind="tests" class="active" onclick="showResult('tests',this)">Test Results</button><button data-kind="api" onclick="showResult('api',this)">API Calls</button><button data-kind="sent" onclick="showResult('sent',this)">Sent Messages</button><button data-kind="received" onclick="showResult('received',this)">Received Messages</button></div><div id="resultView"></div></section></div>
</main><script>
let data={},cat={},currentResult='tests';const core=['login','dashboard','device_connection','device_details','diagnostic_results','manual_tests','issues','reports','settings'];const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));async function api(p,o){const r=await fetch(p,o),j=await r.json();if(!r.ok)throw Error(j.error||r.statusText);return j}function showTab(id,button){['frontendTab','backendTab','logsTab'].forEach(x=>document.querySelector('#'+x).classList.toggle('hidden',x!==id));document.querySelectorAll('.toptabs button').forEach(x=>x.classList.remove('active'));button.classList.add('active');if(id==='logsTab')refresh()}function openLogs(){showTab('logsTab',document.querySelector('#logsButton'))}function send(body){return api('/api/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}).then(()=>{openLogs();refresh()}).catch(e=>document.querySelector('#error').textContent=e.message)}
function runFixedBatch(){send({mode:'fixed_batch',timeout_seconds:+batchTimeout.value})}function runFixedProtocol(){send({mode:'messages',fixed_protocol:true,max_messages:8,timeout_seconds:+fixedTimeout.value})}function runMessages(){send({mode:'messages',payload_file:msgFile.value,max_messages:+maxMessages.value,timeout_seconds:+msgTimeout.value})}function runDummy(){const i=+dummyIos.value,a=+dummyAndroid.value;if(i+a<1||i+a>20){alert('Total dummy devices must be 1 to 20');return}send({mode:'dummy',dummy_ios:i,dummy_android:a,rounds:+dummyRounds.value,timeout_seconds:+dummyTimeout.value})}function runReal(){send({mode:'real',real_device_count:+realCount.value,payload_file:realFile.value,timeout_seconds:+realTimeout.value,max_messages:500})}function chosenPages(){return [...document.querySelectorAll('#pages input:checked')].map(x=>x.value)}function runDesktop(){const p=chosenPages();if(!p.length){alert('Select at least one page');return}send({mode:'desktop',frontend_pages:p,device_limit:20,require_devices:false})}function selectCore(){document.querySelectorAll('#pages input').forEach(x=>x.checked=core.includes(x.value))}function selectAllPages(){document.querySelectorAll('#pages input').forEach(x=>x.checked=true)}function clearPages(){document.querySelectorAll('#pages input').forEach(x=>x.checked=false)}
function inventoryView(i){return `<div class=devices><div class=card><small>Total connected</small><b>${i.counts.total}</b></div><div class=card><small>iOS</small><b>${i.counts.ios}</b></div><div class=card><small>Android</small><b>${i.counts.android}</b></div><div class=card><small>Capacity</small><b>${i.counts.capacity}</b></div></div><table><tr><th>Name</th><th>Platform</th><th>UDID / Serial</th><th>Model</th></tr>${i.devices.map(d=>`<tr><td>${esc(d.name)}</td><td>${esc(d.platform)}</td><td class=mono>${esc(d.udid)}</td><td>${esc(d.model)}</td></tr>`).join('')||'<tr><td colspan=4>No physical device currently detected</td></tr>'}</table>`}
function testTable(rows){return `<table><tr><th>Module</th><th>Test</th><th>Status</th><th>ms</th><th>Device</th><th>Sent</th><th>Received</th><th>Exact result / blocker</th></tr>${(rows||[]).map(r=>`<tr><td>${esc(r.module)}<br><small>${esc(r.group)}</small></td><td>${esc(r.test)}</td><td class=${esc(r.status)}>${esc(r.status)}</td><td>${esc(r.duration_ms)}</td><td class=mono>${esc(r.device)}</td><td>${esc(r.messages_sent)}</td><td>${esc(r.messages_received)}</td><td>${esc(r.details)}${r.blocker?'<br><b>Blocker:</b> '+esc(r.blocker):''}</td></tr>`).join('')||'<tr><td colspan=8>No completed test</td></tr>'}</table>`}function messageTable(rows,title){return `<h3>${title}</h3><table><tr><th>Time</th><th>User</th><th>Session / Device</th><th>Platform</th><th>UDID</th><th>Type</th><th>Reference</th><th>ms</th><th>Message JSON</th></tr>${(rows||[]).map(r=>`<tr><td>${esc(r.timestamp)}${r.source_timestamp?'<br><small>Source: '+esc(r.source_timestamp)+'</small>':''}</td><td>${esc(r.user)}</td><td>${esc(r.session||r.device_name)}</td><td>${esc(r.device_type)}</td><td class=mono>${esc(r.udid)}</td><td>${esc(r.message_type)}</td><td class=mono>${esc(r.ref)}</td><td>${esc(r.duration_ms)}</td><td class=mono>${esc(r.json)}</td></tr>`).join('')||'<tr><td colspan=9>No messages in this direction</td></tr>'}</table>`}
function apiTable(rows){return `<table><tr><th>Time</th><th>Transport</th><th>Method</th><th>Endpoint / Operation</th><th>Device</th><th>Type / Ref</th><th>Result</th><th>HTTP / Response</th><th>ms</th><th>Request</th><th>Response / Error</th></tr>${(rows||[]).map(r=>`<tr><td>${esc(r.timestamp)}</td><td>${esc(r.transport)}</td><td>${esc(r.method)}</td><td class=mono>${esc(r.endpoint)}<br><b>${esc(r.operation)}</b></td><td class=mono>${esc(r.device)}</td><td>${esc(r.message_type)}<br><small>${esc(r.ref)}</small></td><td class=${esc(r.result)}>${esc(r.result)}</td><td>${esc(r.status_code||r.response_status)}${r.response_status?'<br>'+esc(r.response_status):''}</td><td>${esc(r.duration_ms)}</td><td class=mono>${esc(r.request_json)}</td><td class=mono>${esc(r.response_json)}${r.error?'<br><b>'+esc(r.error)+'</b>':''}</td></tr>`).join('')||'<tr><td colspan=11>No API calls recorded</td></tr>'}</table>`}function showResult(kind,button){currentResult=kind;document.querySelectorAll('.resulttabs button').forEach(x=>x.classList.remove('active'));if(button)button.classList.add('active');resultView.innerHTML=kind==='api'?apiTable(data.report?.api_calls):kind==='sent'?messageTable(data.report?.sent_messages,'Sent Messages'):kind==='received'?messageTable(data.report?.received_messages,'Received Messages'):testTable(data.report?.results)}async function refresh(){try{data=await api('/api/status');inventory.innerHTML=inventoryView(data.inventory);state.textContent=data.state.running?`Running ${data.state.mode}…`:`Ready · latest mode: ${data.report?.mode||'none'} · ${data.folder||''}`;error.textContent=data.state.error||'';const s=data.report?.summary||{};summary.innerHTML=Object.entries(s).filter(([k,v])=>typeof v!=='object').map(([k,v])=>`<div class=card><small>${esc(k.replaceAll('_',' '))}</small><b>${esc(v)}</b></div>`).join('');showResult(currentResult,document.querySelector(`.resulttabs button[data-kind="${currentResult}"]`))}catch(e){error.textContent=e.message}}async function init(){cat=await api('/api/catalog');pages.innerHTML=cat.frontend.pages.map(p=>`<label><input type=checkbox value="${esc(p.id)}"> ${esc(p.name)} <small>(${esc(p.description)})</small></label>`).join('');selectCore();refresh()}init();setInterval(refresh,2500);
// Add human-readable duration cards beside the existing millisecond value.
const refreshWithDurationCards=refresh;
function syncDurationCards(){const summaryNode=document.getElementById('summary');if(!summaryNode)return;const duration=Number(data.report?.summary?.duration_ms);const sourceCard=[...summaryNode.querySelectorAll('.card')].find(card=>card.querySelector('small')?.textContent==='duration ms');if(Number.isFinite(duration)&&sourceCard&&!summaryNode.querySelector('[data-duration-card]'))sourceCard.insertAdjacentHTML('afterend',`<div class="card" data-duration-card><small>duration seconds</small><b>${(duration/1000).toFixed(2)}</b></div><div class="card" data-duration-card><small>duration minutes</small><b>${(duration/60000).toFixed(2)}</b></div>`);const serverResult=(data.report?.results||[]).find(row=>row.test==='Staging server status');if(serverResult&&!summaryNode.querySelector('[data-server-status-card]')){const statusText=String(serverResult.details||serverResult.status).replace(/^HTTP\s+\d+;\s*/,'');summaryNode.insertAdjacentHTML('beforeend',`<div class="card" data-server-status-card><small>server status</small><b>${esc(statusText)}</b></div>`)}}
refresh=async function(){await refreshWithDurationCards();syncDurationCards()};
new MutationObserver(syncDurationCards).observe(document.getElementById('summary'),{childList:true});
refresh();
// Device-identification columns for each result row.
const baseTestTableWithDeviceColumns=testTable;
function resultMessageType(test){const match=String(test||'').match(/type\s+(\d+)/i);return match?Number(match[1]):null}
function resultReference(row){const type=resultMessageType(row.test);const event=(data.report?.sent_messages||[]).find(item=>item.udid===row.device&&(type===null||Number(item.message_type)===type));return event?.ref??'—'}
function resultIdentifier(row,name){return row[name]||'—'}
testTable=rows=>`<table><tr><th>Module</th><th>Test</th><th>Status</th><th>ms</th><th>UDID / Serial</th><th>IMEI 1</th><th>IMEI 2</th><th>Color</th><th>Reference number</th><th>Sent</th><th>Received</th><th>Exact result / blocker</th></tr>${(rows||[]).map(row=>`<tr><td>${esc(row.module)}<br><small>${esc(row.group)}</small></td><td>${esc(row.test)}</td><td class=${esc(row.status)}>${esc(row.status)}</td><td>${esc(row.duration_ms)}</td><td class=mono>${esc(row.device)}</td><td class=mono>${esc(resultIdentifier(row,'imei_1'))}</td><td class=mono>${esc(resultIdentifier(row,'imei_2'))}</td><td>${esc(resultIdentifier(row,'color'))}</td><td class=mono>${esc(resultReference(row))}</td><td>${esc(row.messages_sent)}</td><td>${esc(row.messages_received)}</td><td>${esc(row.details)}${row.blocker?'<br><b>Blocker:</b> '+esc(row.blocker):''}</td></tr>`).join('')||'<tr><td colspan=12>No completed test</td></tr>'}</table>`;
// Clear the previous display and show progress while the new test is running.
document.head.insertAdjacentHTML('beforeend','<style>.run-loader{display:flex;align-items:center;gap:12px;padding:18px;font-weight:700;color:#17365d}.run-spinner{width:22px;height:22px;border:3px solid #d7e0ea;border-top-color:#00aa9b;border-radius:50%;animation:spin .8s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}</style>');
let activeRun=false;
function showRunProgress(){if(document.querySelector('#summary [data-run-loader]'))return;summary.innerHTML='<div class="card run-loader" data-run-loader><span class="run-spinner"></span><span>Test is running. Waiting for the new results…</span></div>';resultView.innerHTML='<div class="note" data-run-loader>The previous logs and results are cleared from this view while the test runs.</div>';state.textContent='Test running…';}
send=function(body){activeRun=true;showRunProgress();return api('/api/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}).then(()=>{openLogs();showRunProgress()}).catch(err=>{activeRun=false;document.getElementById('error').textContent=err.message;refresh()})};
new MutationObserver(()=>{if(data.state?.running){activeRun=true;showRunProgress()}}).observe(document.getElementById('summary'),{childList:true});
// Select one detected USB device and verify its connection through the harness.
document.querySelector('#real').insertAdjacentHTML('beforeend',`<section class="panel" id="connectDevicePanel"><h2><span class="step">Connect</span>Selected USB Device</h2><div class="note">Select a detected USB device, then verify that the harness can see its identifier. A backend protocol test still needs a matching captured payload file.</div><div class="bar"><label>Detected device<select id="selectedDevice"><option value="">Refresh devices to choose one</option></select></label><button class="minor" onclick="refresh()">Refresh devices</button><button class="run" onclick="connectSelectedDevice()">Verify Device Connection</button></div><p id="connectDeviceStatus" class="error"></p></section>`);
function syncSelectedDevice(){const select=document.getElementById('selectedDevice');if(!select||!data.inventory)return;const previous=select.value;select.innerHTML='<option value="">Select a detected device</option>'+(data.inventory.devices||[]).map(device=>`<option value="${esc(device.udid)}">${esc(device.name)} · ${esc(device.platform)} · ${esc(device.udid)}</option>`).join('');select.value=previous}
function connectSelectedDevice(){const device=document.getElementById('selectedDevice').value;if(!device){document.getElementById('connectDeviceStatus').textContent='Select a detected device first.';return}document.getElementById('connectDeviceStatus').textContent='';send({mode:'real',real_device_count:1,selected_udids:[device],payload_file:realFile.value,timeout_seconds:+realTimeout.value,max_messages:500})}
new MutationObserver(syncSelectedDevice).observe(document.getElementById('inventory'),{childList:true});
setTimeout(syncSelectedDevice,500);
</script></body></html>'''


class Handler(BaseHTTPRequestHandler):
    def send_json(self, value, status=200):
        body = json.dumps(value).encode("utf-8")
        self.send_response(status); self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body))); self.send_header("Cache-Control", "no-store")
        self.end_headers(); self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            body = HTML.encode("utf-8"); self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body); return
        report_files = {"/report/results.csv": ("results.csv", "text/csv; charset=utf-8"),
                        "/report/api_calls.csv": ("api_calls.csv", "text/csv; charset=utf-8"),
                        "/report/batch_summary.csv": ("batch_summary.csv", "text/csv; charset=utf-8"),
                        "/report/device_summary.csv": ("device_summary.csv", "text/csv; charset=utf-8"),
                        "/report/messages_sent.csv": ("messages_sent.csv", "text/csv; charset=utf-8"),
                        "/report/messages_received.csv": ("messages_received.csv", "text/csv; charset=utf-8"),
                        "/report/messages_readable.log": ("messages_readable.log", "text/plain; charset=utf-8"),
                        "/report/results.json": ("results.json", "application/json; charset=utf-8")}
        if path in report_files:
            folder = latest()["folder"]; filename, content_type = report_files[path]
            source = Path(folder) / filename if folder else Path()
            if not folder or not source.is_file(): self.send_json({"error": "No report available"}, 404); return
            body = source.read_bytes(); self.send_response(200); self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body); return
        if path == "/api/catalog": self.send_json(catalog()); return
        if path == "/api/status":
            report = latest()
            with LOCK: state = dict(STATE)
            self.send_json({"state": state, "inventory": discover(read_json(ROOT / "config.json", {})),
                            "folder": report["folder"], "report": report["report"]}); return
        self.send_json({"error": "Not found"}, 404)

    def do_POST(self):
        if urlparse(self.path).path != "/api/run": self.send_json({"error": "Not found"}, 404); return
        with LOCK:
            if STATE["running"]: self.send_json({"error": "A test is already running"}, 409); return
        try:
            length = int(self.headers.get("Content-Length", "0")); data = json.loads(self.rfile.read(length))
            mode = data.get("mode")
            if mode not in ("messages", "fixed_batch", "dummy", "real", "desktop"): raise ValueError("Choose a valid test mode")
            data["timeout_seconds"] = max(1, min(300, int(data.get("timeout_seconds", 40))))
            if mode == "dummy":
                data["dummy_ios"] = max(0, min(20, int(data.get("dummy_ios", 0))))
                data["dummy_android"] = max(0, min(20, int(data.get("dummy_android", 0))))
                if not 1 <= data["dummy_ios"] + data["dummy_android"] <= 20: raise ValueError("Dummy device total must be 1 to 20")
            if mode == "real": data["real_device_count"] = max(1, min(20, int(data.get("real_device_count", 20))))
            if mode == "desktop":
                valid = {item["id"] for item in catalog()["frontend"]["pages"]}
                if not data.get("frontend_pages") or not set(data["frontend_pages"]).issubset(valid): raise ValueError("Select valid pages")
            threading.Thread(target=run_selection, args=(data,), daemon=True).start(); self.send_json({"started": True}, 202)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            self.send_json({"error": str(exc)}, 400)

    def log_message(self, fmt, *args): pass


def main():
    server = ThreadingHTTPServer(("127.0.0.1", 8765), Handler)
    print("reCheck360 clear QA harness: http://127.0.0.1:8765", flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()


if __name__ == "__main__": main()
