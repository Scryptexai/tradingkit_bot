"""Backend MCP client/host bridge for the bundled TradingKit Pro Streamable HTTP server.

OAuth discovery, PKCE, dynamic client registration, refresh and MCP session framing are
provided by the official MCP Python SDK. This module never implements guessed REST routes.
"""
from __future__ import annotations
import asyncio, json, os, re, sqlite3, uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from cryptography.fernet import Fernet
from mcp.client.auth import OAuthClientProvider
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken

MCP_ENDPOINT='https://app.tradingkit.com/mcp/pro'
MCP_AUDIENCE='https://app.tradingkit.com/mcp'

class EncryptedOAuthStore:
    """Encrypted durable token/client-registration storage; key supplied out-of-band."""
    def __init__(self, db_path: str | Path, encryption_key: str):
        if not encryption_key: raise RuntimeError('TRADINGKIT_TOKEN_ENCRYPTION_KEY is required; refusing plaintext token storage')
        self.fernet=Fernet(encryption_key.encode())
        self.db_path=str(db_path);Path(self.db_path).parent.mkdir(parents=True,exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('CREATE TABLE IF NOT EXISTS mcp_oauth_credentials(account_key TEXT PRIMARY KEY, tokens BLOB, client_info BLOB, updated_at TEXT NOT NULL)')
    def _get(self,key,column,model):
        with sqlite3.connect(self.db_path) as conn: row=conn.execute(f'SELECT {column} FROM mcp_oauth_credentials WHERE account_key=?',(key,)).fetchone()
        if not row or row[0] is None:return None
        return model.model_validate_json(self.fernet.decrypt(row[0]).decode())
    def _set(self,key,column,value):
        encrypted=self.fernet.encrypt(value.model_dump_json().encode()) if value else None
        values=(key,encrypted,None) if column=='tokens' else (key,None,encrypted)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('INSERT INTO mcp_oauth_credentials(account_key,tokens,client_info,updated_at) VALUES(?,?,?,datetime(\'now\')) ON CONFLICT(account_key) DO UPDATE SET '+column+'=excluded.'+column+',updated_at=excluded.updated_at',values)
    async def get_tokens(self,key): return self._get(key,'tokens',OAuthToken)
    async def set_tokens(self,key,value): self._set(key,'tokens',value)
    async def get_client_info(self,key): return self._get(key,'client_info',OAuthClientInformationFull)
    async def set_client_info(self,key,value): self._set(key,'client_info',value)
    def delete(self,key):
        with sqlite3.connect(self.db_path) as conn: conn.execute('DELETE FROM mcp_oauth_credentials WHERE account_key=?',(key,))

class _AccountStorage:
    def __init__(self,store:EncryptedOAuthStore,key:str):self.store=store;self.key=key
    async def get_tokens(self):return await self.store.get_tokens(self.key)
    async def set_tokens(self,tokens):await self.store.set_tokens(self.key,tokens)
    async def get_client_info(self):return await self.store.get_client_info(self.key)
    async def set_client_info(self,info):await self.store.set_client_info(self.key,info)

@dataclass
class PendingOAuth:
    flow_id:str
    redirect_uri:str
    authorize_url:asyncio.Future
    callback:asyncio.Future
    task:asyncio.Task|None=None
    error:str|None=None

class TradingKitMCPHost:
    """Small backend MCP host: OAuth, tool discovery, account verification and tool calls."""
    def __init__(self, *, db_path:Path, account_key:str='local-account', token_key:str|None=None, endpoint:str=MCP_ENDPOINT):
        self.endpoint=endpoint;self.account_key=account_key
        key=token_key if token_key is not None else os.getenv('TRADINGKIT_TOKEN_ENCRYPTION_KEY','')
        self.store=EncryptedOAuthStore(db_path,key) if key else None
        self.pending:dict[str,PendingOAuth]={};self._oauth_lock=asyncio.Lock()
        self.connected=False;self.last_error=None;self.tools=[];self.account=None
    def configured(self):return self.store is not None
    async def begin_authorization(self,redirect_uri:str)->dict[str,str]:
        if not self.store: raise RuntimeError('Secure connection setup required: set TRADINGKIT_TOKEN_ENCRYPTION_KEY before OAuth can begin')
        if not redirect_uri.startswith('https://') and not redirect_uri.startswith('http://localhost'):
            raise ValueError('OAuth callback must use HTTPS (localhost is allowed for local development)')
        async with self._oauth_lock:
            if self.pending: raise RuntimeError('An account authorization flow is already pending')
            flow_id=str(uuid.uuid4());loop=asyncio.get_running_loop()
            pending=PendingOAuth(flow_id,redirect_uri,loop.create_future(),loop.create_future())
            self.pending[flow_id]=pending
            pending.task=asyncio.create_task(self._authorize_and_discover(pending))
        try: url=await asyncio.wait_for(asyncio.shield(pending.authorize_url),timeout=30)
        except Exception:
            self.pending.pop(flow_id,None);raise
        return {'flow_id':flow_id,'authorization_url':url}
    async def _authorize_and_discover(self,pending:PendingOAuth):
        try:
            callback_uri=pending.redirect_uri.replace('{flow_id}',pending.flow_id)
            metadata=OAuthClientMetadata(redirect_uris=[callback_uri],token_endpoint_auth_method='none',client_name='AI Quant Lab TradingKit MCP')
            async def redirect(url:str):
                if not pending.authorize_url.done():pending.authorize_url.set_result(url)
            async def callback():return await pending.callback
            oauth=OAuthClientProvider(server_url=self.endpoint,client_metadata=metadata,storage=_AccountStorage(self.store,self.account_key),redirect_handler=redirect,callback_handler=callback,timeout=300)
            async with streamablehttp_client(self.endpoint,auth=oauth) as (read,write,_session_id):
                async with ClientSession(read,write) as session:
                    await session.initialize()
                    tools=await session.list_tools()
                    tool_names=[item.name for item in tools.tools]
                    # The package's documented first account check; never claim connected before it succeeds.
                    if 'get_account' not in tool_names: raise RuntimeError('MCP connected but required get_account tool was not registered')
                    result=await session.call_tool('get_account',{})
                    if getattr(result,'isError',False): raise RuntimeError('TradingKit get_account tool returned an error; account authentication was not verified')
                    self.tools=tool_names;self.account={'verified':True};self.connected=True;self.last_error=None
        except asyncio.CancelledError: raise
        except Exception as exc:
            self.connected=False;self.last_error=f'{type(exc).__name__}: {str(exc)[:300]}'
            if not pending.authorize_url.done():pending.authorize_url.set_exception(exc)
            raise
        finally:self.pending.pop(pending.flow_id,None)
    async def complete_callback(self,flow_id:str,code:str|None,state:str|None,error:str|None=None):
        pending=self.pending.get(flow_id)
        if not pending or pending.callback.done():raise ValueError('OAuth flow not found or already completed')
        if error:
            pending.callback.set_exception(RuntimeError('OAuth authorization was denied'))
        elif not code or not state:raise ValueError('OAuth callback must include code and state')
        else:pending.callback.set_result((code,state))
        if pending.task:
            try:await asyncio.wait_for(asyncio.shield(pending.task),timeout=45)
            except asyncio.TimeoutError:pass
        return {'status':'connected' if self.connected else 'authorizing','account':self.account}
    def _provider(self,redirect_uri:str):
        async def no_redirect(_url):raise RuntimeError('OAuth renewal required; restart TradingKit authorization from Connections')
        async def no_callback():raise RuntimeError('OAuth callback is not active; restart TradingKit authorization from Connections')
        metadata=OAuthClientMetadata(redirect_uris=[redirect_uri],token_endpoint_auth_method='none',client_name='AI Quant Lab TradingKit MCP')
        return OAuthClientProvider(server_url=self.endpoint,client_metadata=metadata,storage=_AccountStorage(self.store,self.account_key),redirect_handler=no_redirect,callback_handler=no_callback)
    async def verify(self,redirect_uri:str)->bool:
        if not self.store:return False
        tokens=await self.store.get_tokens(self.account_key)
        if not tokens:return False
        try:
            oauth=self._provider(redirect_uri)
            async with streamablehttp_client(self.endpoint,auth=oauth) as (read,write,_sid):
                async with ClientSession(read,write) as session:
                    await session.initialize();tools=(await session.list_tools()).tools
                    names=[x.name for x in tools]
                    if 'get_account' not in names:return False
                    result=await session.call_tool('get_account',{})
                    if getattr(result,'isError',False):return False
                    self.tools=names;self.account={'verified':True};self.connected=True;self.last_error=None
                    return True
        except Exception as exc:
            self.connected=False;self.last_error=f'{type(exc).__name__}; reauthorization may be required'
            return False
    async def discover_tools(self,redirect_uri:str)->list[dict[str,Any]]:
        if not self.store:raise RuntimeError('Secure connection setup is not configured')
        oauth=self._provider(redirect_uri)
        async with streamablehttp_client(self.endpoint,auth=oauth) as (read,write,_sid):
            async with ClientSession(read,write) as session:
                await session.initialize();return [{'name':x.name,'description':x.description,'inputSchema':x.inputSchema} for x in (await session.list_tools()).tools]
    async def call_tool(self,name:str,arguments:dict[str,Any],redirect_uri:str):
        if not self.store or not self.connected:raise RuntimeError('TradingKit account is not authenticated')
        if not name or name not in self.tools:raise ValueError('tool name is not in the latest authenticated MCP tool discovery')
        lowered=name.lower()
        forbidden=('paper','alert','notification','order','trade_live','place_order','incubat','portfolio','telegram','webhook','conversion')
        readonly=lowered.startswith(('get_','list_','search_','compare_'))
        authorized_submission=lowered in {'start_backtest','start_optimization'}
        if any(word in lowered for word in forbidden) or not (readonly or authorized_submission):
            raise ValueError('tool is outside the authorized read-only research/backtest scope')
        oauth=self._provider(redirect_uri)
        async with streamablehttp_client(self.endpoint,auth=oauth) as (read,write,_sid):
            async with ClientSession(read,write) as session:
                await session.initialize()
                actual={x.name for x in (await session.list_tools()).tools}
                if name not in actual:raise RuntimeError('tool is no longer registered by TradingKit; refresh capabilities')
                result=await session.call_tool(name,arguments)
                if getattr(result,'isError',False):raise RuntimeError('TradingKit MCP tool call returned an error')
                return _redact(_safe_content(result))
    def status(self):return {'provider':'TradingKit','endpoint':self.endpoint,'audience':MCP_AUDIENCE,'configured':self.configured(),'authenticated':self.connected,'account':{'verified':True} if self.connected else None,'tools':self.tools if self.connected else [],'last_error':self.last_error}

def _redact(value:Any):
    sensitive=('token','secret','password','credential','authorization','email','accountid','accountnumber','accountref','userid','useremail')
    if isinstance(value,dict):return {k:('[REDACTED]' if any(term in str(k).lower().replace('_','').replace('-','') for term in sensitive) else _redact(v)) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [_redact(x) for x in value]
    if isinstance(value,str):
        value=re.sub(r'(?i)bearer\s+[A-Za-z0-9._~+/-]+=*','Bearer [REDACTED]',value)
        value=re.sub(r'(?i)(access_token|refresh_token|client_secret|api[_-]?key)\s*[:=]\s*[^\s,;]+',r'\1=[REDACTED]',value)
        value=re.sub(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}','[EMAIL REDACTED]',value)
        return value[:20000]
    if value is None or isinstance(value,(bool,int,float)):return value
    return str(value)[:2000]

def _safe_content(result:Any):
    structured=getattr(result,'structuredContent',None)
    if structured is not None:return structured
    return [{'type':getattr(x,'type','unknown'),'text':getattr(x,'text','')} for x in getattr(result,'content',[])]
