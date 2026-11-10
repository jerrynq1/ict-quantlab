from datetime import datetime,timezone
from app.domain.time import to_new_york
from app.domain.market_data import CandleM1
from app.services.cache import SessionOHLCMemoryCache

def test_ny_dst_offsets():
 assert to_new_york(datetime(2026,1,10,12,tzinfo=timezone.utc)).utcoffset().total_seconds()==-18000
 assert to_new_york(datetime(2026,7,10,12,tzinfo=timezone.utc)).utcoffset().total_seconds()==-14400

def test_cache_dedupe_and_env_isolation():
 c=SessionOHLCMemoryCache(); t=datetime(2026,1,1,tzinfo=timezone.utc)
 def bar(close): return CandleM1(candle_id='x',symbol_id='s',timestamp_utc=t,open=1,high=2,low=.5,close=close,volume=1)
 c.upsert('owner','demo','s',[bar(1.2)]); c.upsert('owner','demo','s',[bar(1.3)])
 c.upsert('owner','live','s',[bar(1.4)])
 assert len(c.get('owner','demo','s',t,datetime(2026,1,2,tzinfo=timezone.utc)))==1
 assert c.get('owner','demo','s',t,datetime(2026,1,2,tzinfo=timezone.utc))[0].close==1.3
 assert c.get('owner','live','s',t,datetime(2026,1,2,tzinfo=timezone.utc))[0].close==1.4


def test_bearer_session_round_trip(monkeypatch):
    from fastapi import Request
    from app import security
    monkeypatch.setattr(security.settings, "session_secret", "test-session-signing-secret")
    token = security.create_session("quantlab-admin")
    assert security.valid_session(token)
    assert not security.valid_session(token + "tampered")

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/v1/auth/status",
        "headers": [(b"authorization", f"Bearer {token}".encode())],
        "query_string": b"",
        "server": ("testserver", 80),
        "client": ("127.0.0.1", 12345),
        "scheme": "http",
    }
    request = Request(scope)
    assert security.require_workspace(request) == "quantlab-admin"
