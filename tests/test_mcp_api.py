from fastapi.testclient import TestClient
from app import main


def test_mcp_backend_requires_verified_supabase_session(monkeypatch,tmp_path):
    monkeypatch.setattr(main,'DB',tmp_path/'backend.sqlite')
    client=TestClient(main.app)
    assert client.get('/api/connections').status_code==401
    assert client.get('/api/tradingkit/tools').status_code==401
    assert client.get('/api/tradingkit/activity').status_code==401

def test_oauth_start_fails_closed_without_encryption_configuration(monkeypatch,tmp_path):
    monkeypatch.setattr(main,'DB',tmp_path/'backend.sqlite')
    async def fake_user(_request):return 'test-supabase-user'
    monkeypatch.setattr(main,'authenticated_user_id',fake_user)
    monkeypatch.setattr(main,'MCP_HOSTS',{})
    monkeypatch.delenv('TRADINGKIT_TOKEN_ENCRYPTION_KEY',raising=False)
    response=TestClient(main.app).post('/api/tradingkit/connect/start')
    assert response.status_code==503
    assert 'TRADINGKIT_TOKEN_ENCRYPTION_KEY' in response.json()['detail']
