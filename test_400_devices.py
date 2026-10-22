"""Offline protocol check: reordered responses, background frames, 400 identities."""
import contextlib
import csv
import io
import json
from pathlib import Path
import tempfile
from unittest.mock import patch
import run_400_devices as app
from validate_message_flow import schema


class Login:
    status_code = 200
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def json(self): return {'token': 'offline-secret'}


class Socket:
    def __init__(self): self.pending = []; self.background = True
    def send(self, raw): self.pending.append(json.loads(raw))
    def settimeout(self, value): pass
    def close(self, **kwargs): pass
    def recv(self):
        if self.background:
            self.background = False
            return json.dumps({'messagetype': 15, 'token': 'must-not-appear'})
        request = self.pending.pop()  # deliberately reverse order
        return json.dumps(dict(request, username='offline', status='success', reply=None))


def test():
    contract = {'payload': {'messagetype': 60}, 'schemas':[schema(None)], 'fingerprints':[app.fingerprint(None)]}
    cfg = dict(LOGIN_URL='https://staging.phone-diagnostics.com/v1/login', WS_URL='wss://staging.phone-diagnostics.com/v1/ws', USERNAME='offline', PASSWORD='offline-secret')
    with tempfile.TemporaryDirectory(dir=app.ROOT) as directory:
        with patch.object(app,'ROOT',Path(directory)), patch.object(app,'settings',return_value=cfg), patch.object(app,'build_reference',return_value=([contract],[])), patch.object(app.requests,'post',return_value=Login()), patch.object(app.websocket,'create_connection',side_effect=lambda *a,**k: Socket()), patch('sys.argv',['run_400_devices.py','--pause','0']), contextlib.redirect_stdout(io.StringIO()):
            assert app.main() == 0
        out = next((Path(directory)/'reports').iterdir())
        with (out/'requests.csv').open(encoding='utf-8-sig',newline='') as handle:
            rows=list(csv.DictReader(handle))
        ack=[r for r in rows if r['outcome']=='ACK_ONLY']
        assert len(ack)==1500
        assert len({r['udid'] for r in ack})==400
        assert all(len({r['udid'] for r in ack if r['user']==u})==20 for u in {r['user'] for r in ack})
        assert len({r['ref'] for r in rows if r['ref']})==1520
        raw=(out/'messages.log').read_text(encoding='utf-8')
        assert raw.count('Message sent:')==1520
        assert raw.count('Received message:')==1540
        assert 'must-not-appear' not in raw and 'offline-secret' not in raw
    print('PASS: 20 sessions, 400 unique devices, 1500 acknowledgments, reversed reply correlation, background logging and token redaction')


if __name__=='__main__': test()
