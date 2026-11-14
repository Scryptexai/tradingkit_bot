# AI QUANT LAB — TradingKit research workspace

This repository contains the TradingKit Pro plugin archive plus an AI Quant Lab web application. The ZIP defines the official MCP Streamable HTTP endpoint and host-managed OAuth workflow; the application now includes a FastAPI MCP client/host bridge using the official Python MCP SDK, encrypted OAuth token storage, Supabase-session verification, MCP tool discovery/calls, and a Connections UI. Provider OAuth discovery, client registration, callback acceptance, account verification and backtest execution still require end-to-end testing against a real TradingKit account; no such test has yet occurred.

## Repository analysis and architecture

- Existing stack: none; only README and `tradingkit-pro.zip` (plugin version 2.1.10).
- Package manager/runtime: none previously defined.
- TradingKit endpoint documented by the archive: `https://app.tradingkit.com/mcp/pro`, Streamable HTTP. OAuth resource/audience is documented as `https://app.tradingkit.com/mcp`; authentication is host-managed.
- MCP tools are discovered by the connected host, not specified as a REST API in the ZIP. Relevant documented operations include `get_account`, `get_pine_codegen_rules`, `search_markets`, `search_assets`, `start_backtest`/`get_backtest` and report readers; operations are conditional on actual tool registration and account capabilities. Consult the bundled skills before any such operation.
- No authenticated TradingKit MCP connector is exposed to this coding sandbox. Therefore account, market availability, quotas, rate/concurrency limits, and actual backtesting cannot be verified or executed here. No fabricated results or credentials are used.

The FastAPI backend is the MCP client/host: it uses the Python MCP SDK Streamable HTTP transport against the ZIP's endpoint; OAuth protected-resource/authorization metadata discovery, PKCE and client registration are delegated to that SDK. The backend exposes authenticated start/callback/status/tool-discovery/tool-call routes. The browser initiates OAuth but never receives TradingKit tokens; token and client-registration documents are encrypted at rest with a backend-only Fernet key. MCP tools are discovered live and scope-filtered before UI invocation. Never invent REST APIs or bypass OAuth.

## Roadmap

1. Repository and plugin capability inspection — complete.
2. Responsive dashboard, persisted draft state, migrations, metrics/ranking contracts, idempotent job ledger and fail-closed bounded worker — implemented and tested with mocks.
3. Live Activity uses persisted-event polling; campaigns remain drafts and actual job submission is intentionally blocked.
4. Backend MCP OAuth/client, callback, encrypted credentials, Supabase user scoping and dynamically discovered research-tool UI — implemented as a standards-driven client; provider interoperability remains UNVERIFIED pending actual TradingKit OAuth approval and account verification.
5. Regime evaluation, complete report/equity ingestion, operational heartbeat/recovery controls and production deployment hardening — require real adapter schemas and returned evidence before implementation can be validated honestly.

## Run locally

```sh
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0
```

Open http://localhost:8000. API docs: `/docs`. Storage defaults to `./data/quantlab.sqlite3` (override `QUANTLAB_DB`). This local starter provides a responsive dark research UI, navigation for the requested research areas, structured candidate generation and persistent draft campaigns; starting a campaign does **not** pretend to submit a TradingKit run. Live Activity reads real persisted backend events (currently candidate-generation and draft-campaign events), not synthetic terminal output. `app/metrics.py` calculates after-cost trade metrics from explicitly supplied closed trades and labels its close-to-close drawdown limitation; `app/report_store.py` provides transactional, external-report-ID-deduplicated persistence for a future adapter after it retrieves and validates a genuine report. The TradingKit adapter contract currently fails closed. Execution stays blocked until a real worker, authenticated connector and verified capabilities are implemented. Do not place secrets in source files.

## Persistence, metrics, ranking and execution contracts

SQLite migrations live under `app/migrations/`. They provision user/account references (never tokens), campaigns, immutable strategy versions, idempotent backtest jobs and job events, reports/trades, optimization/validation records, worker heartbeat and audit log tables. Job records snapshot original source and parameters; idempotency keys are unique and an existing key never overwrites the first snapshot. `app/jobs.py` enforces lifecycle transitions and prevents `completed` until report retrieval and validation. `app/worker.py` provides a bounded semaphore, rate spacing, timeout, retry/backoff, rate-limit classification and dead-letter terminal state; its `BacktestAdapter` must be supplied by an authenticated integration. Unit/integration tests use a clearly test-only mock adapter.

Metrics in `app/metrics.py` include net/gross P&L, costs, win rate, profit factor after costs, expectancy, risk/reward, drawdown, consecutive streaks, side win rates, holding duration, exposure, and per-trade Sharpe/Sortino/Calmar where inputs support them. Statistics state their definitions and unknowns. Canonical intratrade drawdown needs actual equity/excursion data; the current trade schema/report reader does not invent that evidence. `app/evaluation.py` supplies configurable multiobjective ranking and temporal split/leakage checks. Unavailable walk-forward/OOS/stability results remain null and do not become fake evidence.

## Security and operational constraints

The backend initiates OAuth through the MCP SDK and handles the registered callback with PKCE/state validation; tokens never reach browser JavaScript and are encrypted in SQLite with `TRADINGKIT_TOKEN_ENCRYPTION_KEY`. Backend endpoints verify the caller's Supabase bearer session against Supabase Auth and scope stored tokens/activity by the verified user id. Set exact `TRADINGKIT_FRONTEND_ORIGINS`; use HTTPS public callback/backend URLs outside localhost. SQLite remains a local/dev store; deploy a durable database, backup encryption key safely and add operational controls before production. Never paste tokens/passwords/cookies into the UI, chat or repository. Provider OAuth compatibility remains unverified until a real consent flow succeeds.

## Cloud preview and Supabase Auth

- Vercel project: `ai-quant-lab` (Vite root directory `cloud`, preview deployment built from the active branch).
- Preview URL: https://ai-quant-lab-git-arena-b308d401-tradi-4896c3-scryptexs-projects.vercel.app (Vercel may require the account's SSO login). Stable project alias that was smoke-tested: https://ai-quant-lab-blush.vercel.app.
- Supabase project: `ai-quant-lab`, region `ap-southeast-1`. The two SQL migrations in `supabase/migrations/` have been applied; tables are owner-scoped by RLS, with composite owner-reference constraints. Auth/DB/REST health reported healthy.
- Supabase Auth is enabled for email magic-link/OTP. The stable Vercel alias and the branch preview URL are in the redirect allow-list. The client only receives the Supabase publishable key; no service-role key or DB password is bundled or exposed.
- Cloud navigation includes all requested research sections. Campaign progress and overview counts are exact head-counts from RLS-protected persistent rows; Live Activity listens to Supabase Realtime inserts on `job_events`. Browser clients have read-only rights to jobs/reports/trades/worker heartbeats/events and cannot forge execution evidence. Pause/resume/stop/retry create durable, expiring user control requests. They remain pending until an authorized worker acknowledges them; they do not claim to change running work while no worker is online.
- Strategy drafts contain Pine v6 example logic for every listed family (EMA/SMA, RSI, MACD, Bollinger, VWAP, Supertrend, ADX, ATR/Donchian, Ichimoku, Stochastic, mean reversion, momentum, volume, trend, support/resistance, confluence, multi-timeframe and hybrid), with direction and risk/exit parameters snapshotted. Structural template tests check signals and exits; they do not replace TradingView/TradingKit compiler validation or real backtests. No template executes until the official adapter, user authorization, preflight and Start gate exist.
- The Connections page uses the backend MCP client: the connect button requests an OAuth authorization URL from FastAPI and redirects the browser to provider consent; callback, PKCE/state validation, token exchange/storage, `get_account` verification and tool discovery happen in the backend. Supabase website login remains separate and its bearer session is verified by the backend. Configure `VITE_BACKEND_URL`, backend `TRADINGKIT_PUBLIC_BASE_URL`, `TRADINGKIT_FRONTEND_URL`, exact CORS origins, Supabase URL/publishable key, and a stable secret `TRADINGKIT_TOKEN_ENCRYPTION_KEY`. Vercel currently serves the frontend only; deploy/reach the FastAPI backend and configure those variables before the button can work.
- Performance fields are sourced from persisted actual report metrics/trades only. `app/metrics.py` defines net per-trade P/L as gross P/L minus fees, funding and slippage; close-to-close drawdown is explicitly not intratrade drawdown; Sharpe/Sortino are per-trade and not annualized. Missing market costs are not inferred. Multi-objective scoring and leakage/audit helpers are in `app/evaluation.py`; unavailable walk-forward/OOS/stability evidence must remain unknown. The cloud leaderboard exposes configurable profit, drawdown, expectancy, sample-size, stability, walk-forward and OOS weights plus minimum trades, max drawdown, net profit filters; evidence not present is excluded from the score, never filled in. Actual strategy trade-close equity charts are based on stored trade P/L and are labeled as excluding intratrade drawdown.
- `CampaignWorker.serve()` is the explicit supervised recovery/poll loop; its `gate_provider` must revalidate current user authorization and Start consent on each poll. It persists worker heartbeat, bounded-concurrency recovery, retry/DLQ events and stopped state. Configure it only with an authorized adapter; default TradingKit adapter remains unavailable.
- In the deployed site, enter your email and click **Email me a sign-in link**. This uses Supabase's official Auth flow. Email delivery has not been tested against your mailbox; the project currently has Supabase default email delivery (no custom SMTP credentials configured), whose provider limits may apply. If delivery is blocked, configure your own SMTP provider in Supabase Auth settings; don't paste SMTP secrets here.
- This login authenticates access to this website and user-private strategy/campaign/knowledge rows. It is **not** TradingKit OAuth. Campaign start and actual backtest execution remain disabled until the separate official TradingKit MCP flow and worker are authorized and integrated.

Local cloud UI development: `cd cloud && cp .env.example .env && npm install && npm run dev`; configure only the Supabase URL and publishable key in the local `.env`. Those two are public browser values; never put secret/service-role keys in Vite variables.

## Clone, local startup, authentication and execution walkthrough

Clone from the configured source repository, then start the local FastAPI research API:

```sh
git clone https://github.com/Scryptexai/tradingkit_bot.git
cd tradingkit_bot
cp .env.example .env
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0
```

Alternatively, use `docker compose up --build`; SQLite data persists in the `quantlab_data` volume. Never publish the local development service openly without adding user authentication, CSRF/origin restrictions, and deployment hardening.

**Authentication walkthrough / provider verification pending:** configure all values from `.env.example` on the backend and `cloud/.env.example` in the frontend build. Generate a Fernet key out of band; do not commit it. Deploy FastAPI at the public HTTPS `TRADINGKIT_PUBLIC_BASE_URL` and register the exact generated callback URL with the provider if TradingKit requires pre-registration; this callback-registration requirement is not specified in the ZIP. Sign in to the website, visit Connections, and click **Connect TradingKit account**. The backend MCP SDK discovers OAuth metadata from the documented endpoint and initiates PKCE/DCR where supported; approve the TradingKit consent in the provider flow. The callback then initializes MCP, discovers tools and calls the documented `get_account` tool before showing authenticated status. This flow is implemented but has not been verified against TradingKit: DCR policy, callback allowlisting, token endpoint behavior and tool schemas are still provider-side unknowns. No credentials should be pasted into the app/chat. The UI can call dynamically discovered, scope-allowed research/backtest tools and logs tool/status/timestamp in backend activity; complete job/report ingestion and provider-side activity parity still require provider integration tests.

**Backtest walkthrough (available local draft flow vs blocked execution):** generate strategy drafts in Strategy Factory, review source/parameters and create a draft campaign. The Start control returns a fail-closed preflight report. An eventual actual run must first prove local worker heartbeat, valid OAuth, account capability check, selected instrument, supported timeframe and historical coverage, then receive an explicit Start click. Only after those steps should an official adapter compile, submit with a stable idempotency key, poll the returned job, retrieve the exact report and validate its source pins/trades. Current sandbox can exercise that lifecycle only with the explicit `MockBacktestAdapter` in integration tests; those records are tests and never appear as TradingKit results.

## Plugin archive

`tradingkit-pro.zip` is retained unchanged. Installation instructions, account constraints, tool workflows, and extensive limitations are documented inside its `tradingkit-pro/INSTALL.md` and `skills/` after extraction. Package installation alone does not authenticate or grant account features.
