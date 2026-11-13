# AI QUANT LAB — TradingKit research workspace

This repository is currently a TradingKit Pro plugin package (`tradingkit-pro.zip`), not an existing web application. The archive is an instruction/plugin bundle (manifest, MCP server URL, skills); it contains no frontend, backend, database schema, worker, or TradingKit API implementation. This incremental build adds a local research API and honest execution-gated dashboard foundation without claiming that an MCP connection or actual backtest has occurred.

## Repository analysis and architecture

- Existing stack: none; only README and `tradingkit-pro.zip` (plugin version 2.1.10).
- Package manager/runtime: none previously defined.
- TradingKit endpoint documented by the archive: `https://app.tradingkit.com/mcp/pro`, Streamable HTTP. OAuth resource/audience is documented as `https://app.tradingkit.com/mcp`; authentication is host-managed.
- MCP tools are discovered by the connected host, not specified as a REST API in the ZIP. Relevant documented operations include `get_account`, `get_pine_codegen_rules`, `search_markets`, `search_assets`, `start_backtest`/`get_backtest` and report readers; operations are conditional on actual tool registration and account capabilities. Consult the bundled skills before any such operation.
- No authenticated TradingKit MCP connector is exposed to this coding sandbox. Therefore account, market availability, quotas, rate/concurrency limits, and actual backtesting cannot be verified or executed here. No fabricated results or credentials are used.

Proposed modular direction: current deliverable uses Python FastAPI + SQLite persistence for a portable local control plane. A later production deployment can replace SQLite with PostgreSQL and add a durable queue/worker and WebSocket after actual workload/auth requirements are confirmed. TradingKit MCP adapter must run in a supported authenticated host/local agent; it must not invent HTTP endpoints or bypass host OAuth.

## Roadmap

1. Repository and plugin capability inspection — complete.
2. Responsive dashboard, persisted draft state, migrations, metrics/ranking contracts, idempotent job ledger and fail-closed bounded worker — implemented and tested with mocks.
3. Live Activity uses persisted-event polling; campaigns remain drafts and actual job submission is intentionally blocked.
4. Official TradingKit OAuth/MCP bridge, verified capability/data discovery and secure user-authorized worker — externally blocked pending supported host/client authorization metadata and account interaction; no guessed endpoints are used.
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

OAuth is performed by TradingKit's supported host flow. Never paste tokens/passwords/cookies into this app or repository. The current adapter intentionally reports unavailable rather than simulating successful authentication. Keep this app bound to a trusted local environment until authentication, authorization, CSRF, and production deployment controls are implemented. SQLite is a local development store, not a multi-user production database. Tests use temporary SQLite and do not call TradingKit.

## Cloud preview and Supabase Auth

- Vercel project: `ai-quant-lab` (Vite root directory `cloud`, preview deployment built from the active branch).
- Preview URL: https://ai-quant-lab-git-arena-b308d401-tradi-4896c3-scryptexs-projects.vercel.app (Vercel may require the account's SSO login). Stable project alias that was smoke-tested: https://ai-quant-lab-blush.vercel.app.
- Supabase project: `ai-quant-lab`, region `ap-southeast-1`. The two SQL migrations in `supabase/migrations/` have been applied; tables are owner-scoped by RLS, with composite owner-reference constraints. Auth/DB/REST health reported healthy.
- Supabase Auth is enabled for email magic-link/OTP. The stable Vercel alias and the branch preview URL are in the redirect allow-list. The client only receives the Supabase publishable key; no service-role key or DB password is bundled or exposed.
- Cloud navigation includes all requested research sections. Campaign progress and overview counts are exact head-counts from RLS-protected persistent rows; Live Activity listens to Supabase Realtime inserts on `job_events`. Browser clients have read-only rights to jobs/reports/trades/worker heartbeats/events and cannot forge execution evidence. Pause/resume/stop/retry create durable, expiring user control requests. They remain pending until an authorized worker acknowledges them; they do not claim to change running work while no worker is online.
- Strategy drafts contain Pine v6 example logic for every listed family (EMA/SMA, RSI, MACD, Bollinger, VWAP, Supertrend, ADX, ATR/Donchian, Ichimoku, Stochastic, mean reversion, momentum, volume, trend, support/resistance, confluence, multi-timeframe and hybrid), with direction and risk/exit parameters snapshotted. Structural template tests check signals and exits; they do not replace TradingView/TradingKit compiler validation or real backtests. No template executes until the official adapter, user authorization, preflight and Start gate exist.
- The Connections page deliberately does not collect TradingKit credentials. TradingKit Pro documents a host-managed OAuth flow for its MCP endpoint (`https://app.tradingkit.com/mcp/pro`, audience `https://app.tradingkit.com/mcp`). This Vercel app has no registered TradingKit OAuth client/callback or host OAuth bridge; therefore a real authorization button cannot be honestly delivered from this deployment. Its endpoint link is not itself authentication. Supabase website login is separate and configured through the deployed Supabase Auth redirect allow-list.
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

**Authentication walkthrough / current blocker:** install or enable TradingKit Pro in a supported host and connect `https://app.tradingkit.com/mcp/pro` using that host's official OAuth sign-in. The ZIP says the protected OAuth audience is `https://app.tradingkit.com/mcp`; do not paste tokens. Then verify `get_account`, code-generation rules and required research tools in a fresh connected session. This sandbox has no connected TradingKit MCP tool and no public auth discovery/client registration in the ZIP. So the local app cannot receive the host's login session, verify account capabilities, or safely act on that connection. A local MCP OAuth bridge requires the official client flow/redirect support and verified server capability metadata; no guessed auth URLs, browser bypass or token-copy workaround is supplied. `app/credentials.py` stores only opaque official-flow credentials in OS keychain if a real secure backend is available; it has no login/token input endpoint. Until a supported local-agent authorization bridge is delivered, Connections stays not-connected and execution stays blocked.

**Backtest walkthrough (available local draft flow vs blocked execution):** generate strategy drafts in Strategy Factory, review source/parameters and create a draft campaign. The Start control returns a fail-closed preflight report. An eventual actual run must first prove local worker heartbeat, valid OAuth, account capability check, selected instrument, supported timeframe and historical coverage, then receive an explicit Start click. Only after those steps should an official adapter compile, submit with a stable idempotency key, poll the returned job, retrieve the exact report and validate its source pins/trades. Current sandbox can exercise that lifecycle only with the explicit `MockBacktestAdapter` in integration tests; those records are tests and never appear as TradingKit results.

## Plugin archive

`tradingkit-pro.zip` is retained unchanged. Installation instructions, account constraints, tool workflows, and extensive limitations are documented inside its `tradingkit-pro/INSTALL.md` and `skills/` after extraction. Package installation alone does not authenticate or grant account features.
