import os
from fastapi.testclient import TestClient

def test_api(tmp_path, monkeypatch):
    monkeypatch.setenv("QUANTLAB_DB", str(tmp_path / "test.sqlite"))
    from app import main
    main.DB = tmp_path / "test.sqlite"
    client = TestClient(main.app)
    assert client.get('/api/health').json()['execution'] == 'unavailable'
    a=client.post('/api/strategies/generate', json={'count':3,'families':['EMA crossover'],'market':'BTCUSDT','timeframe':'1h'})
    assert a.status_code == 200 and a.json()['created'] == 3
    assert client.get('/api/strategies').json()[0]['status'] == 'generated'
    assert client.get('/api/leaderboard').json()['results'] == []
    assert client.get('/api/execution/readiness').json()['allowed'] is False
    db=main.db(); assert db.execute('select count(*) from strategy_versions').fetchone()[0] == 3; db.close()
    campaign=client.post('/api/campaigns',json={'name':'test','total':3}).json()
    blocked=client.post(f"/api/campaigns/{campaign['id']}/start")
    assert blocked.status_code == 409
    assert client.get('/api/campaigns').json()[0]['status'] == 'draft'

def test_deduplication(tmp_path):
    from app import main
    main.DB=tmp_path/'dedup.sqlite'
    client=TestClient(main.app)
    payload={'count':2,'families':['EMA crossover'],'market':'BTCUSDT','timeframe':'1h'}
    one=client.post('/api/strategies/generate',json=payload).json()
    two=client.post('/api/strategies/generate',json=payload).json()
    assert one['created']==2 and two['created']==0 and two['duplicates_skipped']==2
