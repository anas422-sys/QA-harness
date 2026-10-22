"""Offline verification of exact request replay, correlation and reporting."""
import contextlib
import csv
import io
import json
from pathlib import Path
import tempfile
from unittest.mock import patch
import replay_supplied_messages as app


class Login:
    status_code=200
    def __enter__(self): return self
    def __exit__(self,*args): pass
    def json(self): return {'token':'offline-token'}


def main():
    source=app.load_source(app.SOURCE)
    expected={s['payload']['messagetype']:s for s in source}
    sent=[]
    class Socket:
        def __init__(self): self.reply=None; self.background=True
        def settimeout(self,value): pass
        def send(self,raw):
            payload=json.loads(raw); sent.append(payload)
            template=expected[payload['messagetype']]
            original=json.loads(json.dumps(payload)); original['client_data']=template['payload']['client_data']
            assert original==template['payload']
            self.reply=json.loads(json.dumps(template['expected'])) if template['expected'] else {'messagetype':payload['messagetype'],'status':'success','reply':None}
            self.reply['client_data']=payload['client_data']
        def recv(self):
            if self.background:
                self.background=False
                return json.dumps({'messagetype':15,'token':'should-be-redacted'})
            if self.reply is None: raise app.websocket.WebSocketTimeoutException()
            reply=self.reply; self.reply=None
            return json.dumps(reply)
        def close(self,**kwargs): pass
    cfg=dict(LOGIN_URL='https://staging.phone-diagnostics.com/v1/login',WS_URL='wss://staging.phone-diagnostics.com/v1/ws',USERNAME=source[2]['expected']['username'],PASSWORD='offline-password')
    with tempfile.TemporaryDirectory(dir=app.ROOT,ignore_cleanup_errors=True) as tmp:
        with patch.object(app,'ROOT',Path(tmp)),patch.object(app,'settings',return_value=cfg),patch.object(app.requests,'post',return_value=Login()),patch.object(app.websocket,'create_connection',return_value=Socket()),patch('sys.argv',['replay_supplied_messages.py']),contextlib.redirect_stdout(io.StringIO()):
            assert app.main()==0
        out=next(p for p in (Path(tmp)/'reports').iterdir() if p.is_dir())
        summary=json.loads((out/'manifest.json').read_text())
        assert summary['sent']==11 and summary['received']==12
        assert summary['outcomes']=={'ACK_NO_REFERENCE':2,'MATCH':9}
        assert len({m['client_data']['ref'] for m in sent})==11
        text=(out/'messages.log').read_text()
        assert 'should-be-redacted' not in text and 'offline-token' not in text
        assert (out/'recorded_command_outputs.csv').exists()
    assert app.differences({'a':1},{'a':None})
    assert app.differences({'command':[{'cmd_id':3}]},{'command':[{'cmd_id':3},{'cmd_id':4}]})
    print('PASS: exact 11-request sequence, unchanged source data, fresh refs, 9 matched source replies, full logs, redaction and difference detection')


if __name__=='__main__': main()
