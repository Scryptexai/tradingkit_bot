import asyncio
import pytest
from cryptography.fernet import Fernet
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from app.tradingkit_mcp import EncryptedOAuthStore, _AccountStorage, _redact


def test_encrypted_oauth_storage_roundtrip_and_no_plaintext(tmp_path):
    path=tmp_path/'oauth.sqlite'; key=Fernet.generate_key().decode(); store=EncryptedOAuthStore(path,key)
    async def go():
        client=_AccountStorage(store,'local-account')
        tokens=OAuthToken(access_token='access-secret',refresh_token='refresh-secret',expires_in=3600)
        info=OAuthClientInformationFull(client_id='registered-client',redirect_uris=['https://example.test/callback'])
        await client.set_tokens(tokens);await client.set_client_info(info)
        assert (await client.get_tokens()).access_token=='access-secret'
        assert (await client.get_client_info()).client_id=='registered-client'
    asyncio.run(go())
    raw=path.read_bytes();assert b'access-secret' not in raw and b'refresh-secret' not in raw

def test_secure_storage_refuses_missing_key(tmp_path):
    with pytest.raises(RuntimeError,match='refusing plaintext'):
        EncryptedOAuthStore(tmp_path/'oauth.sqlite','')

def test_account_redaction_removes_sensitive_named_fields():
    assert _redact({'account_id':'private','safe':{'access_token':'secret','count':2}})=={'account_id':'[REDACTED]','safe':{'access_token':'[REDACTED]','count':2}}
