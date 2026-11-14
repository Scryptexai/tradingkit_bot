# Technical phase status — TradingKit research/backtests

**Scope:** research/backtests only. No live trading, deployment, or financial transaction was performed. Secrets and account identifiers are intentionally omitted.

## Phase status

| Phase | Status | Evidence / limitation |
|---|---|---|
| TradingKit connection UI / MCP P0 | IMPLEMENTED (backend client/host flow), UNVERIFIED (real provider OAuth) | Connections UI calls FastAPI OAuth start, redirects to backend-generated authorization URL, returns to callback, then displays verified status and live-discovered tools. Python MCP SDK supplies Streamable HTTP/OAuth metadata discovery, PKCE and dynamic registration; backend encrypts tokens and scopes them to verified Supabase user ID. No TradingKit consent flow was exercised in this sandbox; DCR/callback policy may need official provider registration. |
| TradingKit authentication/tool discovery | IMPLEMENTED (backend implementation), UNVERIFIED (provider/account) | Backend uses the official Python MCP SDK against the ZIP endpoint; OAuth metadata discovery, PKCE, callback, encrypted token/client storage, Supabase user verification, `get_account` check and live tool discovery are wired. Runtime has no TradingKit account tools; real authorization/account test remains unperformed. |
| MCP strategy/research tool execution from UI | IMPLEMENTED (dynamic UI/backend call path), UNVERIFIED (provider) | Authenticated UI can display actual discovered schemas and invoke read-only research tools plus documented start_backtest/start_optimization tools. Tool calls and redacted results/status are saved in per-user backend activity. No tool has been invoked against TradingKit here; end-to-end provider job/report synchronization is unverified. |
| Genuine provider backtest | NOT STARTED | No authenticated provider call or explicit provider execution was available. There are no genuine provider job/report IDs or metrics. |
| Durable backtest provenance | IMPLEMENTED (local schema/API), UNVERIFIED (provider integration) | SQLite provenance migration and report persistence capture strategy/version/job/source hash, market/timeframe/interval, parameter snapshot, execution times, cost assumptions, provider metrics, unavailable-field list, trade count and trade records. Supabase migration draft adds server-side provenance fields. No provider payload contract exists to verify mappings. |
| Atomic queue leases | IMPLEMENTED (local worker path), UNVERIFIED (cross-process stress/provider integration) | SQLite worker dispatch and recovery now atomically claim the exact job before adapter calls, periodically renew the lease during execution, and release on exit. Supabase migration includes a `SKIP LOCKED` claim function. Local tests cover competing claims; migration is unapplied and multi-process stress tests remain. |
| Shared exponential retry with jitter | IMPLEMENTED (local worker path), UNVERIFIED (cross-process/provider behavior) | Worker errors schedule a durable next-attempt timestamp with exponential jitter under an active lease, release the lease, and allow a later worker poll to claim when due. Supabase migration provides a corresponding scheduler function. Production DB behavior is untested. |
| Parallel execution and provider rate defaults | IMPLEMENTED (bounded configurable mechanism), BLOCKED (production enablement) | Worker requires an explicit verified-provider-limits object, checks configured concurrency against the verified ceiling, and derives request pacing from that object; there is no default production concurrency/rate. Mock tests exercise the guard, not TradingKit. Do not enable production parallelism until one real backtest succeeds and provider/account limits are verified. |
| Strategy algorithm/alias classification | IMPLEMENTED | Factory metadata identifies aliases vs independent algorithm families, supplies a canonical algorithm ID shared by parameter variants, and generation rejects names outside the explicit supported family list. Pine source remains a draft requiring official compiler validation. |
| Automated test/build checks | VERIFIED (local/mocked) | 56 Python tests pass; Python compile, JS syntax, Vite build, and `git diff --check` pass. Tests cover encrypted token storage, Supabase-session guard and mocked/local behavior only; none is authenticated TradingKit integration. |

## Changed files and purpose

- `app/tradingkit_mcp.py`, `app/main.py`, `requirements.txt` — Python MCP SDK OAuth/Streamable HTTP client, encrypted per-user credential store, Supabase session verification, callback, dynamic tool discovery/invocation and activity API.
- `cloud/src/main.js`, `cloud/.env.example`, `.env.example` — UI OAuth start/return, discovered tool/schema invocation and per-user activity views; backend configuration template.
- `tests/test_tradingkit_mcp.py`, `tests/test_mcp_api.py` — encrypted credential-store, redaction, missing-config and auth-gate local tests.
- `app/migrations/002_execution_provenance.sql`, `app/migrations/__init__.py` — register local SQLite provenance/queue lease schema migrations.
- `app/jobs.py` — source hash, interval validation, execution timestamps, atomic local lease/retry primitives.
- `app/report_store.py` — idempotent report/trade persistence, explicit missing-field ledger, provider metrics and cost assumptions.
- `app/worker.py` — persist validated adapter report evidence before marking a job complete; no fabricated trade fields.
- `app/metrics.py` — avoid assuming a starting capital when it was not supplied.
- `app/main.py` — return expanded persisted report provenance.
- `supabase/migrations/202611130007_backtest_provenance.sql`, `202611130008_shared_retry_backoff.sql` — draft server-side provenance, lease and retry scheduling schema/functions; not applied.
- `tests/test_api.py`, `tests/test_jobs.py`, `tests/test_metrics.py`, `tests/test_worker_integration.py` — mock/local regression coverage for provenance and lease/retry primitives.
- `cloud/src/main.js` — truthful TradingKit connection entry point, no simulated OAuth.
- `app/adapters.py`, `app/templates.py`, `tests/test_templates.py`, `tests/test_adapters.py` — other pre-existing branch changes; see git diff for details.

## Evidence and test classification

- **Genuine backtest evidence:** none. No claim of provider compilation, execution, report validation, or profitability is made.
- **Mock/local tests:** `python -m pytest -q` — 50 passed. Includes local SQLite state tests and mock adapter tests; it does not authenticate to TradingKit.
- **Frontend/build checks:** `node --check cloud/src/main.js`; `npm run build --prefix cloud`; `git diff --check` — passed.
- **Authenticated integration tests:** none.

## Gaps and risks

1. Backend OAuth/MCP client is implemented but unverified against TradingKit. The callback URL must be publicly reachable over HTTPS; provider client registration/redirect allowlisting policy is not specified by the ZIP. The user must configure the deployed backend/frontend URLs and token-encryption key, then approve real provider consent. Do not send passwords or tokens in chat.
2. MCP tools/schemas are discovered dynamically after auth, but no provider test has established the actual registration set, argument semantics, backtest lifecycle/report mapping or cost/slippage/funding conventions. Provider concurrency/rate limits remain unknown.
3. Local worker renews leases periodically during execution. Process-kill/crash recovery and multi-process stress behavior still need explicit tests before production multi-worker use.
4. Durable retry scheduling is integrated in the local worker; Supabase scheduling/claim functions have not been deployed or exercised against the project's schema.
5. Supabase migrations are drafts and were not applied. Their assumptions about deployed schema, permissions, type relationships and required `next_attempt_at` fields need review against the actual project before use.
6. Bot activity records each MCP invocation plus a redacted result/status. Provider-side events not caused by this bot are not synchronized yet; complete job/report lifecycle-to-ledger ingestion needs real schemas and a verified provider call.
7. Report schema migration and provider provenance completeness have only local tests; no migration was deployed or tested against production data.

## Blocking prerequisite

Configure and deploy the FastAPI backend with a public HTTPS callback, Supabase session verification, exact frontend CORS origins and stable encryption key; then approve the UI-started TradingKit OAuth and verify a single genuine backtest. Provider redirect/client-registration acceptance and provider limits still need direct verification. No deployment is authorized or performed.
