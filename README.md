# RazorSync — Razorpay Coordination Engine

> One coordination layer for every customer touchpoint: live Razorpay payments, policy guardrails, human review, and multi-seed simulation with confidence intervals. Every decision is audited with its reasoning.

RazorSync sits between your agents and Razorpay. Every payment event, order, and agent action flows through one policy engine (windowed rules + hard guardrails + dispatcher scoring), gets audited, and can be replayed in simulation before you ship a rule change.

- **Backend:** FastAPI · Python 3.12 · SQLite (WAL) · SQLAlchemy · Redis Streams (optional) · Razorpay SDK · provider-agnostic LLM (optional)
- **Frontend:** Next.js 14 · TypeScript · Tailwind · Recharts · Lucide
- **Infra:** Docker Compose (API + worker + Redis) · `mise` for Node/Python pinning

---

## 1. What it does

| Capability | How |
|---|---|
| **Live payment pipeline** | `POST /orders` creates a real Razorpay test-mode order → Checkout popup → `payment.captured/failed` webhook → verified (HMAC) → coordinated decision with fast ack |
| **Coordination engine** | Windowed, IST-aware rules (`frequency_cap`, `cooldown`, `time_window`, `budget_limit`, `escalation_ceiling`) + hard guardrails (financial ceiling, state conflict → HITL suspend) + dispatcher (policy scoring picks the best agent) |
| **Audit & polling** | Every decision writes `AuditEntry` with reasoning + webhook event. Dashboard polls `GET /decisions/recent?since=` every 2s — no WebSocket, fewer failure modes |
| **Simulation with uncertainty** | Multi-seed scorecard (default 200 customers × 3 seeds) with 95% CI, Welch's t-test p-value, false-positive rate, and `net_value` (P&L instead of gross revenue). Engine parity: simulation calls the same `RulesEngine.evaluate` as live |
| **Async ingestion (Option B)** | Webhook → Redis Stream + DB inbox → background reasoning worker. Redis down? DB fallback keeps local work and tests fully offline |
| **LLM, optional** | OpenAI-compatible endpoint (`LLM_ENDPOINT`/`LLM_MODEL`/`LLM_API_KEY`). Empty = deterministic fallback. Used for reasoning text, never for policy verdicts |
| **Failure drills** | `POST /ops/failure-toggle` forces the real `TimeoutError` path: fallback order + amber banner + audit, so the console stays useful when the provider is down |

---

## 2. Quick start

### Prerequisites

- Python 3.12 (`mise` or `uv` recommended)
- Node 20+
- Optional: Redis 7 (Docker), Razorpay test keys, tunnel (ngrok/cloudflared) for webhooks

### Backend

```bash
cd backend
cp .env.example .env   # fill only what you need — never commit .env
uv sync                # or: pip install -e .
uv run pytest tests    # credential-free, offline
uv run uvicorn app.main:app --reload --port 8000
# health → http://127.0.0.1:8000/health
# docs  → http://127.0.0.1:8000/docs
```

### Frontend

```bash
cd frontend
npm install
npm run dev
# → http://localhost:3000  (rewrites /api/* → :8000)
```

### Docker (API + worker + Redis)

```bash
cp backend/.env.example backend/.env
docker compose up --build
```

---

## 3. Configuration

All settings live in `backend/app/config.py` (pydantic-settings, reads `backend/.env`).

```bash
# backend/.env.example — placeholders only, safe to commit
RAZORPAY_KEY_ID=rzp_test_XXXXXXXXXXXX
RAZORPAY_KEY_SECRET=XXXXXXXXXXXXXXXXXXXXXXXX
RAZORPAY_WEBHOOK_SECRET=your_webhook_secret_from_dashboard
WEBHOOK_BASE_URL=https://<your-tunnel>
REDIS_URL=                      # empty → DB fallback (local work + tests)
LLM_ENDPOINT=                   # empty → deterministic fallback
LLM_MODEL=
LLM_API_KEY=
```

| Var | Required? | Notes |
|---|---|---|
| `RAZORPAY_KEY_ID/SECRET` | Only for live orders | Test-mode keys. Without them, orders use the fallback path (still coordinated + audited) |
| `RAZORPAY_WEBHOOK_SECRET` | Only for real webhooks | Must match Dashboard webhook secret. Empty locally → verification skipped with a warning |
| `WEBHOOK_BASE_URL` | Only for real webhooks | Your public tunnel URL |
| `REDIS_URL` | No | `redis://localhost:6379/0`. Empty = inbox via DB, worker runs inline |
| `LLM_ENDPOINT/MODEL/API_KEY` | No | Any OpenAI-compatible tier or local Ollama. Empty = fallback reasoning |
| `SIMULATION_*` | No | Defaults: 500 customers, seeds `42,137,256`, 7 days |

> **Security:** `.env` is gitignored. No key, secret, token, or tunnel URL is committed. Frontend never embeds secrets — the console webhook helper uses a `local_ops_only_not_a_secret` placeholder and real verification happens server-side.

---

## 4. Evaluation workflow

1. **Overview** — `http://localhost:3000` shows live metrics + architecture.
2. **Live order** — `/ops` → pick customer → `Create Order` → real `order_…` + decision via polling.
3. **Decision chain** — `GET /decisions/recent?since=` shows `webhook → rule eval → verdict → reasoning`.
4. **Simulation** — `/simulation/scorecard` → `Run Simulation` → bars with 95% CI, p-value, false-positive.
5. **Rules** — `/rules` → toggle a rule → re-run simulation → result changes (same engine as live).
6. **Failure drill** — `/ops` → `Razorpay Failure` ON → `Create Order` → amber banner + fallback decision + audit.
7. **Checkout** — `/checkout` → real Razorpay popup (UPI/cards/netbanking per Dashboard payment-methods config).

**Tunnels for webhooks:** Razorpay needs a public HTTPS URL. Run `ngrok http 8000` (or `cloudflared tunnel --url http://localhost:8000`), set Dashboard webhook to `https://<tunnel>/api/v1/webhook/razorpay` with events `payment.captured`, `payment.failed`, `order.paid`, and copy the secret to `.env`.

---

## 5. API

| Method | Path | Notes |
|---|---|---|
| `POST` | `/api/v1/orders` | Razorpay `order.create` (5s timeout, retry ×2, fallback) → coordination → decision |
| `POST` | `/api/v1/checkout/order` | Checkout-scoped order; returns only public `key_id`/`order_id` (secret never exposed) |
| `POST` | `/api/v1/webhook/razorpay` | HMAC verify (401 on fail) → Redis Stream + DB inbox → ack fast, reason async |
| `GET` | `/api/v1/decisions/recent?since=&limit=` | Dashboard polling endpoint |
| `POST` | `/api/v1/simulation/scorecard` | Multi-seed scorecard: CI, p-value, false-positive, `net_value` |
| `POST` | `/api/v1/simulation/seed?num_customers=` | Seed customers for evaluation/tests |
| `GET/POST` | `/api/v1/rules` | Single-source `BusinessRule.rule_config`; IST-aware |
| `GET` | `/api/v1/ops/state` | Inspectable runtime state |
| `POST` | `/api/v1/ops/failure-toggle` | Force real degradation path |
| `POST` | `/api/v1/ops/reset`, `/replay` | Reset / replay runtime state |
| `GET` | `/api/v1/audit`, `/metrics`, `/execution`, `/hitl` | Trail, aggregates, DAG, review queue |
| `GET` | `/health`, `/` | Liveness |

---

## 6. Architecture

```text
Dashboard --POST /orders--> Razorpay API (test) --webhook--> /webhook/razorpay (verify)
                                                                              |
                                                     Redis Stream + DB inbox (fast ack)
                                                                              |
                                              Reasoning worker: guardrails → rules → dispatcher → LLM note
                                                                              |
                                                     Audit + Decision --poll--> Dashboard
                                                                              `--> Scorecard (multi-seed, CI, p-value)
```

- **Windowed rules:** `frequency_cap`, `cooldown`, `escalation_ceiling` count `proposed_at >= now - window`; `budget_limit` is cumulative; `time_window` is IST (`Asia/Kolkata`).
- **Hard vs soft:** financial/state risks → `SUSPEND` + HITL ticket (async, 24h expiry, re-validated on resume). Frequency/throttle → `BLOCK` (no ticket).
- **Dispatcher:** `score = est_revenue − churn_risk − discount_cost − channel_cost + channel_fit`. Policy proposes, guardrails veto — competition is visible in `/ops` and `/execution`.
- **Engine parity:** simulation imports `RulesEngine` — toggling a rule changes both live and simulated outcomes.
- **Stats notes:** `net_value = Σ(V−d)·converted − Σd·¬converted − Σ LTV·0.3·churned`; `revenue_per_contact` is the headline; non-significant results are labeled, not hidden.

---

## 7. Project structure

```text
backend/app/{config.py,main.py,
  db/, models/{customer,action,decision,rule,audit,simulation,order,hitl,inbox},
  engine/{rules,coordinator,collisions,priority,context,dispatcher,llm_client},
  simulation/{engine,customers,agents,metrics},
  services/razorpay_client.py, queue/redis_queue.py,
  llm/{client,registry,models.yaml,providers/}, agents/{config.yaml},
  worker/reasoning.py,
  api/{orders,checkout,webhooks,decisions,simulation,ops,rules,customers,audit,metrics,actions,execution,hitl,agents_config}}
backend/tests/{test_health.py,test_rules.py}   # credential-free, offline
frontend/src/{app/{page,layout,ops,checkout,rules,customers,audit,simulation/scorecard,execution},
  components/Sidebar.tsx, lib/{api,types,format}.ts}
docker-compose.yml  mise.toml  .python-version
```

---

## 8. Testing (no credentials needed)

```bash
cd backend
uv run pytest tests -v
# test_health.py — root/health, OpenAPI contracts, list endpoints, validation 422
# test_rules.py  — approve/block, cooldown window, inactive-rule ignore
```

Live Razorpay, real webhooks, Redis, and LLM are **not** required. They are exercised via `/ops` toggles and the documented manual flow in §4.

---

## 9. Limitations

- If Razorpay is down: 5s timeout → fallback order + cached decision + banner + audit. Pre-seeded data + replay keep the console useful.
- Polling (not WebSocket) is deliberate: fewer failure modes at the cost of a 2s polling interval.
- `λ=0.3 LTV at risk` in `net_value` is an assumption — disclosed in UI.
- SQLite WAL + semaphore(2) + `429→fallback` keep stress runs stable; for production use Postgres + managed Redis.

---

## 10. License

MIT — see `LICENSE` (or treat as all-rights-reserved if no `LICENSE` file is present). Do not commit `.env` or any keys.
