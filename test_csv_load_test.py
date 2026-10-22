"""Offline tests; no staging requests or physical device actions."""
import csv_load_test as app  # Apply gevent patching before other imports.
import csv
import json
from pathlib import Path
import tempfile
from unittest.mock import patch


def test_csv_flow():
    with tempfile.TemporaryDirectory() as directory:
        out = Path(directory)
        recorder = app.CsvRecorder(out)
        env = app.Environment(user_classes=[app.WebSocketUser])
        env.test_config = dict(login_url="http://mock", ws_url="ws://mock", username="test", password="secret",
                               timeout=.1, devices=[dict(udid="TEST", messagetype=1, device_operating_system="ios", device_info="invalid")])
        env.csv_recorder = recorder

        class Response:
            status_code = 200
            content = b"mock"
            def __enter__(self): return self
            def __exit__(self, *a): pass
            def json(self): return {"token": "secret-token"}

        class Socket:
            def send(self, raw):
                payload = json.loads(raw)
                self.replies = ["background", json.dumps({"messagetype": 99}),
                                json.dumps(dict(udid="TEST", messagetype=15, status="success", reply={"tests": [dict(code="A", test_name="WiFi", result="Pass")]})),
                                json.dumps(dict(payload, status="success"))]
            def recv(self): return self.replies.pop(0)
            def settimeout(self, seconds): pass
            def close(self, **kw): pass

        with patch.object(app.requests.Session, "post", return_value=Response()), patch.object(app.websocket, "create_connection", return_value=Socket()):
            user = app.WebSocketUser(env)
            user.on_start()
            user.task_send_message()
            # A second operation must register failure, not silently succeed.
            with patch.object(user.ws, "recv", side_effect=app.websocket.WebSocketTimeoutException()):
                try:
                    user.task_send_message()
                except app.StopUser:
                    pass
                else:
                    raise AssertionError("Timeout was not recorded")
            user.on_stop()
        summary = recorder.finish(1, 1, False)
        assert summary["failed_operations"] == 1
        assert summary["sessions_with_acknowledgments"] == 1
        with (out / "requests.csv").open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        assert len(rows) == 4
        assert rows[2]["background_messages"] == "3"
        assert rows[3]["success"] == "False"
        assert "secret-token" not in (out / "requests.csv").read_text(encoding="utf-8-sig")
        with (out / "diagnostic_results.csv").open(encoding="utf-8-sig", newline="") as handle:
            snapshots = list(csv.DictReader(handle))
        assert len(snapshots) == 1 and snapshots[0]["fresh_run_verified"] == "False"
        assert app.safe_cell("=1+1") == "'=1+1"
        assert not app.response_matches({"client_data": []}, env.test_config["devices"][0])


if __name__ == "__main__":
    test_csv_flow()
    print("PASS: request correlation, background messages, timeouts, diagnostic snapshots, CSV export and credential redaction")
