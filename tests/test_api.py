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
    strategies=client.get('/api/strategies').json()
    assert strategies[0]['status'] == 'generated'
    assert 'strategy.entry' in strategies[0]['source'] and 'strategy.exit' in strategies[0]['source']
    assert 'NOT compiler validated' not in strategies[0]['source']
    assert client.get('/api/leaderboard').json()['results'] == []
    configured=client.get('/api/leaderboard?minimum_trades=5&profit_weight=0.5&drawdown_weight=0.5')
    assert configured.status_code == 200 and configured.json()['minimum_trades'] == 5
    assert client.get('/api/execution/readiness').json()['allowed'] is False
    db=main.db(); assert db.execute('select count(*) from strategy_versions').fetchone()[0] == 3; db.close()
    campaign=client.post('/api/campaigns',json={'name':'test','total':3}).json()
    blocked=client.post(f"/api/campaigns/{campaign['id']}/start")
    assert blocked.status_code == 409
    assert client.get('/api/campaigns').json()[0]['status'] == 'draft'

def test_api_leaderboard_uses_persisted_validation_evidence_and_filters(tmp_path):
    from app import main
    main.DB=tmp_path/'leaderboard.sqlite'
    client=TestClient(main.app)
    generated=client.post('/api/strategies/generate',json={'count':1,'families':['EMA crossover'],'market':'BTCUSDT','timeframe':'1h'}).json()['items'][0]
    c=main.db()
    metrics={'trade_count':50,'net_profit':100,'gross_loss':20,'profit_factor':2.0,'max_drawdown_close_to_close':.1,'expectancy':2.0,'average_loss':-1.0,'win_rate':.6}
    c.execute('INSERT INTO reports(id,strategy_id,adapter,external_job_id,external_report_id,source_hash,market,timeframe,returned_at,metrics) VALUES(?,?,?,?,?,?,?,?,?,?)',('r1',generated['id'],'adapter','job1','report1',generated['source_hash'],'BTCUSDT','1h','2025-01-01T00:00:00+00:00',__import__('json').dumps(metrics)))
    c.execute('INSERT INTO validations VALUES(?,?,?,?,?,?,?,?)',('v1',generated['id'],'r1','walk_forward','validated','{}',__import__('json').dumps({'parameter_stability':.8,'walk_forward_consistency':.7,'out_of_sample_result':.6}),'2025-01-02T00:00:00+00:00'))
    c.commit();c.close()
    result=client.get('/api/leaderboard?minimum_trades=30&min_stability=0.75').json()['results']
    assert len(result)==1 and result[0]['stability_score']==.8
    assert result[0]['walk_forward_score']==.7 and result[0]['out_of_sample_result']==.6
    assert result[0]['validation_status']=='validated' and result[0]['score'] is not None
    assert client.get('/api/leaderboard?min_stability=0.9').json()['results']==[]

def test_deduplication(tmp_path):
    from app import main
    main.DB=tmp_path/'dedup.sqlite'
    client=TestClient(main.app)
    payload={'count':2,'families':['EMA crossover'],'market':'BTCUSDT','timeframe':'1h'}
    one=client.post('/api/strategies/generate',json=payload).json()
    two=client.post('/api/strategies/generate',json=payload).json()
    assert one['created']==2 and two['created']==0 and two['duplicates_skipped']==2
