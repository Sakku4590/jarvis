# Jarvis — Phase 1 Foundation

The infrastructure backbone for the AI Personal Operating System: containerized
services, a FastAPI app, async PostgreSQL with migrations, a ChromaDB client,
Redis, and structured logging. No agents, tools, or chat logic yet. This phase
exists to give every later phase a healthy, observable place to stand.

## What is here

```
jarvis/
├── docker-compose.yml          # postgres, redis, chroma, backend
├── .env.example                # copy to .env
├── Makefile                    # make up / migrate / logs / ...
└── backend/
    ├── Dockerfile
    ├── requirements.txt
    ├── alembic.ini
    ├── alembic/                # async migration environment
    └── app/
        ├── main.py             # FastAPI app + lifespan
        ├── core/
        │   ├── config.py       # env-driven settings
        │   ├── logging.py      # structlog setup
        │   └── llm.py          # Phase 2: async JSON LLM client (OpenAI/Ollama)
        ├── api/
        │   ├── health.py       # liveness + readiness probes
        │   ├── memory.py       # Phase 2: consolidate / search / facts endpoints
        │   ├── planner.py      # Phase 3: plan / replan / capabilities endpoints
        │   └── supervisor.py   # Phase 4: POST /supervisor/run
        ├── db/
        │   ├── base.py         # declarative base
        │   ├── session.py      # async engine + session
        │   └── models.py       # users, threads, messages, tool_calls, memory_facts
        ├── memory/             # Phase 2: the memory subsystem
        │   ├── chroma_client.py # vector store client + heartbeat
        │   ├── embeddings.py    # OpenAI / Ollama / fake embedders
        │   ├── schemas.py       # ExtractedFact, RetrievedMemory, decisions
        │   ├── store.py         # Postgres + Chroma dual-store coordination
        │   ├── retrieval.py     # hybrid read path (semantic + recent)
        │   ├── consolidation.py # extract + resolve (insert/skip/supersede)
        │   ├── state.py         # LangGraph state
        │   └── agent.py         # the LangGraph Memory Agent
        └── planner/            # Phase 3: the planner subsystem
            ├── schemas.py      # Plan, PlanStep, statuses
            ├── capabilities.py # declarative capability catalog (no executors)
            ├── validation.py   # pure DAG validation + topological order
            ├── decomposer.py   # LLM-backed plan + replan
            ├── state.py        # LangGraph state
            └── agent.py        # the LangGraph Planner Agent
        # Phase 4 adds two sibling packages:
        # tools/   schemas.py, registry.py, pipeline.py, selector.py, builtin.py
        # agents/  state.py, classifier.py, executor.py, supervisor.py
        # Phase 5 adds the File Agent (first real specialist):
        # services/file_service.py   sandboxed filesystem layer
        # tools/file_tools.py        create/read/delete/rename/search tools
        # agents/file_agent.py       LangGraph tool-calling loop
        # api/files.py               POST /files/task
        # Phase 6 adds the Coding Agent:
        # services/code_sandbox.py   process-level execution sandbox
        # tools/code_tools.py        generate/review/debug/execute tools
        # agents/coding_agent.py     LangGraph tool-calling loop
        # api/code.py                POST /code/task
        # Phase 7 adds the Browser Agent:
        # services/browser_service.py  Playwright service + URL guard (lazy import)
        # tools/browser_tools.py       open/search/extract/fill tools
        # agents/browser_agent.py      LangGraph tool-calling loop
        # api/browser.py               POST /browser/task
        # Phase 8 adds the Gmail Agent (first credentialed integration):
        # core/crypto.py                  Fernet token encryption
        # integrations/credential_store.py  encrypted Postgres + in-memory stores
        # integrations/google_oauth.py    OAuth flow helpers (lazy google import)
        # services/gmail_service.py       Gmail API wrapper + MIME builder
        # tools/gmail_tools.py            read_inbox/search/draft_reply/send tools
        # agents/gmail_agent.py           LangGraph tool-calling loop
        # api/gmail.py                    OAuth endpoints + POST /email/task
        # db/models.py                    + Integration model (encrypted tokens)
        # Phase 9 adds the Spotify Agent:
        # integrations/spotify_oauth.py   OAuth (Authorization Code) via httpx
        # services/spotify_service.py     Spotify Web API wrapper (httpx)
        # tools/spotify_tools.py          search/play/pause/skip/create_playlist
        # agents/spotify_agent.py         LangGraph tool-calling loop
        # api/spotify.py                  OAuth endpoints + POST /music/task
        # Phase 10 adds the WhatsApp Agent (Twilio):
        # services/whatsapp_service.py    Twilio WhatsApp API wrapper (httpx)
        # tools/whatsapp_tools.py         send/schedule/broadcast (all gated)
        # agents/whatsapp_agent.py        LangGraph tool-calling loop
        # api/whatsapp.py                 status + POST /messaging/task
        # Phase 11 connects everything into one workflow:
        # agents/agent_registry.py        capability -> specialist agent
        # agents/orchestrator.py          the unified LangGraph (graph of graphs)
        # api/jarvis.py                   POST /jarvis/run (single entrypoint)
        # Phase 12 adds the dashboard + its backend support:
        # observability/activity.py       in-memory tool/task activity store
        # api/dashboard.py                agent status / activity / tasks
        # frontend/                       Next.js + TypeScript + Tailwind app
        # Phase 13 adds production deployment:
        # backend/Dockerfile              multi-stage prod image (gunicorn)
        # frontend/Dockerfile             Next.js standalone prod image
        # docker-compose.prod.yml         build + migrate + serve, prod-flavoured
        # deploy/k8s/                     namespace, config, db/redis/chroma,
        #                                 backend, frontend, ingress, hpa, kustomize
        # .github/workflows/ci.yml        tests + type-check + image build
        # .github/workflows/release.yml   push to GHCR + deploy to k8s
```

## Run it

1. Copy the environment template and set a real secret key:
   ```
   cp .env.example .env
   # edit SECRET_KEY (openssl rand -hex 32) and the passwords
   ```
2. Start the stack:
   ```
   make up
   ```
   This builds the backend, starts Postgres, Redis, and Chroma, applies
   migrations, and serves the API on http://localhost:8000.
3. Verify everything is wired up:
   ```
   curl http://localhost:8000/health
   curl http://localhost:8000/health/ready
   ```
   A `ready` status with all three checks `true` means the foundation is solid.

## Creating the first migration

The models exist but no migration has been generated yet. Once the stack is up:

```
make revision m="initial schema"
make migrate
```

API docs are at http://localhost:8000/docs.

## Notes

- Services talk to each other by container name inside the compose network
  (`postgres`, `redis`, `chroma`), which is why `.env` defaults to `localhost`
  but compose overrides the hosts.
- Chroma is exposed on host port 8001 to avoid clashing with the backend on
  8000; inside the network it listens on 8000.
- Ollama is commented out in compose. Uncomment it when model routing begins.

## Phase 2: the Memory Agent

The memory subsystem is a LangGraph `StateGraph` with a conditional entry that
runs one of two flows:

```
START ─(retrieve)──▶ retrieve ───────────────────────▶ END
      └(consolidate)▶ extract ─▶ resolve ─▶ store ────▶ END
```

- Retrieve (read): hybrid lookup combining Chroma semantic neighbors with the
  most recent current facts from Postgres, deduped, ranked, and capped to a
  character budget.
- Consolidate (write/update): an LLM extracts durable facts from a conversation,
  then each fact is resolved against existing memory into insert, skip, or
  supersede. Superseding closes the old Postgres row (valid_to) and removes its
  Chroma vector, so retrieval only ever surfaces current facts.

### Try it without an API key

The default `EMBEDDING_PROVIDER=fake` and the injectable LLM let the pipeline run
and be tested with no external services. Run the suite:

```
cd backend
EMBEDDING_PROVIDER=fake pytest -q
```

The tests drive the real graph with an in-memory store and a canned LLM,
covering insert, skip, supersede, and retrieve.

### Try it over HTTP (full stack up)

```
# remember something
curl -X POST localhost:8000/memory/consolidate -H 'Content-Type: application/json' \
  -d '{"user_id":"<uuid>","messages":[{"role":"user","content":"I prefer dark roast and moved to Bangalore"}]}'

# recall it
curl "localhost:8000/memory/search?user_id=<uuid>&q=where%20do%20I%20live"

# list current facts
curl "localhost:8000/memory/facts?user_id=<uuid>"
```

For real semantic retrieval set `EMBEDDING_PROVIDER=openai` and `OPENAI_API_KEY`,
or `EMBEDDING_PROVIDER=ollama` with a local embedding model. The `memory_facts`
table already exists from the Phase 1 migration, so no new migration is needed.

## Phase 3: the Planner Agent

The planner turns a goal into a validated, dependency-ordered plan. It is a
LangGraph `StateGraph` with a conditional entry into a shared validation node:

```
START ─(plan)───▶ decompose ─┐
      └(replan)─▶ replan ────┴─▶ validate ─▶ END
```

- decompose / replan ask the LLM for draft steps against a declarative
  capability catalog. The catalog (file, email, calendar, browser, coding,
  music, messaging, memory) lists capability keys and descriptions only. No
  executor or specialist agent is implemented in this phase; those arrive later.
- validate is pure, LLM-free logic and is where correctness lives. It checks id
  uniqueness, that every dependency and capability resolves, and that the graph
  is acyclic, then computes a topological execution order with Kahn's algorithm.
  A plan the LLM got wrong comes back `invalid` with reasons rather than being
  passed downstream.

The plan-and-execute loop is closed by `replan`: feed back a failure or new
information and the planner revises the remaining work.

### Try it without an API key

The validation layer and graph wiring are tested with a canned LLM, so no key
is needed:

```
cd backend
pytest -q tests/test_planner_validation.py tests/test_planner_agent.py
```

### Try it over HTTP (full stack up)

```
curl localhost:8000/planner/capabilities

curl -X POST localhost:8000/planner/plan -H 'Content-Type: application/json' \
  -d '{"goal":"find the signed contract, summarize the payment terms, and email John"}'
```

### Wiring in Phase 2 memory (optional)

`PlannerAgent` accepts a `retriever` (an async callable taking the goal and
returning a context string). Pass one that calls the Memory Agent to fold what
is known about the user into planning. Left unset, the planner runs standalone.

## Phase 4: the Supervisor (orchestration)

The Supervisor sits on top and turns a message into an answer:

```
START -> recall -> classify ─(chat)──▶ chat ───────────────▶ END
                            ─(single)▶ single ─▶ synthesize ─▶ END
                            ─(plan)──▶ plan ─(ready)─▶ execute ┐
                                            └(invalid)─────────┴▶ synthesize ▶ END
```

- Routing (`agents/classifier.py`): chat (answer directly, no tools), single
  (one capability, fast path), or plan (hand to the Phase 3 planner). The
  fast-path / agent-path split keeps trivial requests cheap.
- Tool layer (`tools/`): every tool is registered with a common contract
  (args schema, risk class, approval flag, handler). The pipeline runs
  validate -> permit -> risk gate -> execute (timeout + retry) -> audit and
  returns a normalized `ToolResult`. The selector picks a tool by action key,
  then single-tool shortcut, then LLM only for genuine ambiguity.
- Execution (`agents/executor.py`): walks the plan in topological order,
  resolves `$step.output` references between steps, and skips dependents of any
  step that failed or was held for approval.

Only `memory.retrieve` is a real tool (wired to Phase 2). The other
capabilities are registered as labeled stubs so the whole flow runs and every
pipeline branch is exercised; the real integrations replace them in later
phases without changing the orchestration.

The risk gate is live: a destructive tool (e.g. `email.send`) returns
`pending_approval` instead of running unless the request carries `approved`.
The full human-in-the-loop resume (LangGraph interrupt + the `approvals` table)
layers on top of this gate later.

### Try it without an API key

```
cd backend
pytest -q tests/test_tools.py tests/test_supervisor_agent.py
```

### Try it over HTTP (full stack up)

```
curl -X POST localhost:8000/supervisor/run -H 'Content-Type: application/json' \
  -d '{"user_id":"<uuid>","message":"find the contract and email it to John"}'

# re-run with approval to clear the risk gate on the send step
curl -X POST localhost:8000/supervisor/run -H 'Content-Type: application/json' \
  -d '{"user_id":"<uuid>","message":"email John","approved":true}'
```

## Phase 5: the File Agent (first real specialist)

The File Agent replaces the Phase 4 file stubs with real, sandboxed file
operations: create, read, delete, rename, search. It is a LangGraph tool-calling
loop:

```
START -> think -(call)-> act -> think
               -(finish)-----------> finish -> END
```

The model picks one file tool per turn, sees the result, and continues until the
task is done or the iteration cap is hit. Every call runs through the same
pipeline as the supervisor, so the workspace sandbox, risk gate, and audit apply.

Safety is the point of this phase, since it is the first agent with real side
effects:

- Sandbox: all operations are confined to `FILE_WORKSPACE_ROOT`. The
  `FileService._resolve` primitive joins any caller path to the root,
  canonicalizes it (collapsing `..` and symlinks), and rejects anything that
  lands outside. Absolute paths, `../../etc/passwd`, and symlink escapes all
  fail before any IO.
- Risk: `file.delete` is destructive and approval-gated; the agent reports a
  held delete rather than performing it, unless the request is approved.

### Try it without an API key

```
cd backend
pytest -q tests/test_file_service.py tests/test_file_agent.py
```

The service tests are pure; the agent tests drive the real loop with a scripted
LLM against an isolated temp workspace, covering create, read, search, the
delete gate, and the iteration cap.

### Try it over HTTP (full stack up)

```
curl -X POST localhost:8000/files/task -H 'Content-Type: application/json' \
  -d '{"user_id":"u1","instruction":"create notes/todo.txt containing buy milk, then read it back"}'
```

Set `FILE_WORKSPACE_ROOT` to a mounted volume in production so the workspace
persists and is isolated from the rest of the container.

## Phase 6: the Coding Agent

The Coding Agent generates, reviews, debugs, and executes code through a
LangGraph tool-calling loop (same shape as the File Agent):

```
START -> think -(call)-> act -> think
               -(finish)-----------> finish -> END
```

A typical flow is generate -> execute -> (on failure) debug -> execute again.
generate, review, and debug are pure LLM operations (no side effects, READ).
code.execute is DESTRUCTIVE and approval-gated, so the pipeline holds it unless
the request is approved.

### Safe execution (read this before trusting it)

`SubprocessSandbox` gives PROCESS-LEVEL isolation: a fresh temp working dir
removed after the run, Python launched in isolated mode (-I), POSIX resource
limits applied in the child (CPU time, address space, file size, process count),
its own session so a wall-clock timeout can kill the whole tree, a minimal
environment, and closed stdin.

This is appropriate for development and low-trust-but-not-adversarial code. It
is NOT a full security boundary: a process sandbox cannot, by itself, block
network access or contain a kernel exploit. In production, implement
`CodeSandbox` with a disposable container or microVM (Docker, gVisor,
Firecracker) and inject it; nothing else changes. Tuning lives in
`CODE_EXEC_*` settings (cpu seconds, memory MB, timeout, output cap).

### Try it without an API key

```
cd backend
pytest -q tests/test_code_sandbox.py tests/test_coding_agent.py
```

The sandbox tests run real subprocesses and assert stdout capture, exception
handling, the timeout, and the memory limit. The agent tests drive the loop with
a scripted LLM and the real sandbox, covering generate -> execute, the execution
gate, review, and debug.

### Try it over HTTP (full stack up)

```
curl -X POST localhost:8000/code/task -H 'Content-Type: application/json' \
  -d '{"user_id":"u1","instruction":"write a function for fibonacci and run it for n=10","approved":true}'
```

## Phase 7: the Browser Agent (Playwright)

The Browser Agent opens sites, searches the web, extracts content, and fills
forms, through a LangGraph tool-calling loop (same shape as the File and Coding
agents):

```
START -> think -(call)-> act -> think
               -(finish)-----------> finish -> END
```

open, search, and extract are READ. browser.fill is WRITE and approval-gated,
because submitting a form acts on the site (login, purchase, post); a held fill
is reported rather than performed unless the request is approved.

### Safety

- URL guard: `validate_url` allows only http/https and, when
  `BROWSER_ALLOWED_DOMAINS` is set, restricts navigation to an allowlist
  (subdomains included). It blocks `file://`, `javascript:`, `data:`, and other
  schemes before any navigation, which closes the door on using the browser to
  read local files.
- Untrusted content: extracted page text is returned as DATA. The agent prompt
  explicitly instructs the model to never follow instructions found inside page
  content. Treating scraped text as trusted is the classic browser-agent
  prompt-injection hole, so it is called out directly.
- Isolation: each operation uses a fresh, disposed browser context, so calls do
  not leak state and can run concurrently against one shared browser. Downloads
  are disabled and every navigation has a timeout.

### Install the browser binary

The `playwright` library installs via pip, but the Chromium binary is fetched
separately and once:

```
pip install playwright
playwright install chromium
```

Playwright is imported lazily, so the rest of the system runs and the test suite
passes without the browser installed. In Docker, add `RUN playwright install
--with-deps chromium` to the backend image (it needs network at build time).

### Try it without an API key

```
cd backend
pytest -q tests/test_browser_agent.py
```

These cover the URL guard directly and drive the agent loop against a fake
browser service (no Playwright, no network), including the fill approval gate.

### Try it over HTTP (full stack up, browser installed)

```
curl -X POST localhost:8000/browser/task -H 'Content-Type: application/json' \
  -d '{"user_id":"u1","instruction":"search for the latest Python release and tell me the version"}'
```

## Phase 8: the Gmail Agent (first credentialed integration)

The Gmail Agent reads the inbox, searches, drafts replies, and sends mail
through a LangGraph tool-calling loop, replacing the Phase 4 email stubs.
read_inbox and search are READ; draft_reply is WRITE (a draft is not sent, so it
is not gated); send is DESTRUCTIVE and approval-gated.

### Credential security

OAuth tokens are the most sensitive data the system holds, so they are
encrypted at rest. `core/crypto.py` uses Fernet; the key comes from
`CREDENTIAL_ENCRYPTION_KEY` (set this in production, managed by a secrets
manager) or is derived from `SECRET_KEY` in development. The `integrations`
table stores only ciphertext in `credentials_encrypted`. The token is decrypted
in memory only when a request needs it, and a refreshed token is re-encrypted
before being written back.

### OAuth setup

1. In Google Cloud Console, create an OAuth client (type: Web application),
   enable the Gmail API, and add `http://localhost:8000/integrations/gmail/callback`
   as an authorized redirect URI.
2. Put the values in `.env`:
   ```
   GOOGLE_CLIENT_ID=...
   GOOGLE_CLIENT_SECRET=...
   GOOGLE_OAUTH_REDIRECT_URI=http://localhost:8000/integrations/gmail/callback
   CREDENTIAL_ENCRYPTION_KEY=<python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())">
   ```
3. Connect an account:
   ```
   # 1) get the consent URL, open it, grant access
   curl "localhost:8000/integrations/gmail/authorize?user_id=<uuid>"
   # 2) Google redirects to the callback, which stores encrypted tokens
   # 3) confirm
   curl "localhost:8000/integrations/gmail/status?user_id=<uuid>"
   ```

Run the migration first so the `integrations` table exists:
`make revision m="add integrations"` then `make migrate`.

Scopes default to gmail.readonly + gmail.send + gmail.compose (`GMAIL_SCOPES`).

### Error handling

The service maps Gmail failures to clean errors that become tool-result
envelopes: 401 -> reconnect, 429/403 -> rate limit, others -> a generic API
error, and a missing connection -> `not_connected`. Expired access tokens are
refreshed automatically (and the new token re-encrypted and saved) when a
refresh token is present.

### Try it without an API key

```
cd backend
pytest -q tests/test_gmail_agent.py
```

These cover credential encryption, the MIME builder, the credential store, and
the agent loop (search, read, the send gate, draft reply, and not-connected
handling) against a fake Gmail service. No Google API or network needed.

### Try it over HTTP (account connected)

```
curl -X POST localhost:8000/email/task -H 'Content-Type: application/json' \
  -d '{"user_id":"<uuid>","instruction":"summarize my unread email from this week"}'
```

## Phase 9: the Spotify Agent

The Spotify Agent plays music, pauses, skips, searches, and creates playlists
through a LangGraph tool-calling loop, using the Spotify Web API over httpx (no
SDK). search is READ; play, pause, skip, and create_playlist are WRITE and not
approval-gated (music is the low-risk capability).

### OAuth setup

1. In the Spotify Developer Dashboard, create an app, note the Client ID and
   Secret, and add `http://localhost:8000/integrations/spotify/callback` as a
   redirect URI.
2. Put the values in `.env`:
   ```
   SPOTIFY_CLIENT_ID=...
   SPOTIFY_CLIENT_SECRET=...
   SPOTIFY_REDIRECT_URI=http://localhost:8000/integrations/spotify/callback
   ```
3. Connect an account:
   ```
   curl "localhost:8000/integrations/spotify/authorize?user_id=<uuid>"
   # open the URL, grant access; the callback stores encrypted tokens
   curl "localhost:8000/integrations/spotify/status?user_id=<uuid>"
   ```

Tokens are encrypted at rest using the same credential store and Fernet key as
Phase 8 (`integrations` table). The access token is refreshed automatically when
near expiry or on a 401, then re-encrypted and saved.

### Error handling

Spotify HTTP errors map to clean envelopes: 401 -> reconnect, 403 -> forbidden
(Spotify Premium may be required for playback control), 404 -> no active device,
429 -> rate limited, plus `not_connected` when no account is linked. Playback
control requires an active Spotify device.

### Try it without an API key

```
cd backend
pytest -q tests/test_spotify_agent.py
```

Covers the OAuth URL builder and the agent loop (play, pause, skip, create
playlist, not-connected) against a fake Spotify service. No network needed.

### Try it over HTTP (account connected, active device)

```
curl -X POST localhost:8000/music/task -H 'Content-Type: application/json' \
  -d '{"user_id":"<uuid>","instruction":"play some lo-fi and make a focus playlist"}'
```

## Phase 10: the WhatsApp Agent (Twilio)

The WhatsApp Agent sends, schedules, and broadcasts WhatsApp messages through
the Twilio WhatsApp API (the compliant, official path, not the bannable
unofficial web libraries), over httpx. A LangGraph tool-calling loop drives it.
All three messaging tools are DESTRUCTIVE and approval-gated, since every one
sends externally visible messages.

### Setup

Twilio uses account-level credentials (no per-user OAuth). Put them in `.env`:

```
TWILIO_ACCOUNT_SID=AC...
TWILIO_AUTH_TOKEN=...
TWILIO_WHATSAPP_FROM=whatsapp:+14155238886        # your Twilio WhatsApp sender
TWILIO_MESSAGING_SERVICE_SID=MG...                # required only for scheduling
```

For the WhatsApp sandbox or a registered sender, follow Twilio's WhatsApp
onboarding. Check configuration:

```
curl "localhost:8000/integrations/whatsapp/status"
```

### Capabilities

- send: immediate message to one number.
- schedule: future delivery via Twilio scheduled messages (ScheduleType=fixed +
  SendAt). Requires a Messaging Service SID; `send_at` must be a future ISO 8601
  time (Twilio's window is roughly 15 minutes to 7 days out).
- broadcast: send the same message to a list of recipients, returning per-
  recipient results.

### Error handling

Twilio failures map to clean envelopes: 401 -> invalid credentials, 400 -> bad
request (e.g. invalid number), 429 -> rate limited, plus `not_configured` when
credentials are missing and `no_messaging_service` when scheduling without a
Messaging Service SID. Broadcast continues past individual failures and reports
sent/failed counts.

### Try it without credentials

```
cd backend
pytest -q tests/test_whatsapp_agent.py
```

Covers number normalization, request-param building (immediate vs scheduled),
future-time validation, and the agent loop (send gate, schedule, broadcast,
not-configured) against a fake Twilio service. No network needed.

### Try it over HTTP (configured)

```
curl -X POST localhost:8000/messaging/task -H 'Content-Type: application/json' \
  -d '{"user_id":"<uuid>","instruction":"message +14155550123 that I am running late","approved":true}'
```

## Phase 11: the Orchestrator (all agents, one workflow)

The Orchestrator is the capstone: a single LangGraph workflow that connects
every agent. It recalls memory, classifies the request, and routes into chat, a
single specialist, or a planned multi-step run.

```
START -> recall -> classify -(chat)--> chat ---------------> END
                            -(single)> single -> synthesize -> END
                            -(plan)--> plan -(ready)-> execute +
                                            -(invalid)---------+-> synthesize -> END
```

The key idea is delegation: instead of calling one tool per plan step, the
executor hands each step to the SPECIALIST AGENT for its capability (File,
Coding, Browser, Email, Spotify, WhatsApp), and each of those is itself a
LangGraph tool-calling loop. So the Orchestrator is a graph of graphs. The
Planner produces the step DAG; the Memory agent supplies recall context;
classification picks the path.

- Routing: chat (no tools), single (one specialist), or plan (Planner + multi-
  agent execution).
- Delegation + cross-step flow: a step's instruction is the step description
  plus its resolved inputs, where `$s1.output` is replaced by the prior step's
  result. Specialist agents run their own tool-calling loops to complete a step.
- Failure containment: a step that errors or is held for approval blocks its
  dependents, which are skipped; the run still returns a full per-step report.
- Fallback: capabilities with no specialist agent (calendar, memory) fall back
  to direct tool dispatch through the same pipeline, so the approval gate and
  audit apply everywhere. `approved` propagates into every agent and tool call.

### Try it without an API key

```
cd backend
pytest -q tests/test_orchestrator.py
```

Covers chat, single delegation, multi-agent plan ordering with cross-step data,
a held-for-approval step blocking its dependents, an invalid plan skipping
execution, and the no-agent fallback path, using fake agents and a fake LLM.

### Try it over HTTP (full stack up, integrations connected)

```
curl -X POST localhost:8000/jarvis/run -H 'Content-Type: application/json' \
  -d '{"user_id":"<uuid>","message":"find the budget file, then draft an email to my accountant about it"}'
# re-run with "approved": true to clear any gated step (a send, a delete, ...)
```

`/jarvis/run` is the single entrypoint that ties memory, planner, supervisor
routing, and all six specialist agents together.

## Phase 12: the Dashboard (Next.js + TypeScript + Tailwind)

A control-room dashboard for Jarvis, in `frontend/`. Five panels:

- Chat: talk to the orchestrator (`/jarvis/run`); each reply shows the route and
  the per-step delegation (which agent handled what). An "auto-approve actions"
  toggle clears the risk gate for that run.
- Agents: live status of every capability and whether its integration is
  connected (Gmail/Spotify per user, WhatsApp by config).
- Memory: the facts Jarvis remembers about you (`/memory/facts`).
- Tasks: history of recent runs.
- Tool activity: a live log of tool calls with risk class, status, and timing.

### Backend support added this phase

The dashboard needs live data, so the backend gained a small, read-only surface:
an in-memory activity store (`observability/activity.py`) that records every
tool call (via a recording audit sink on the pipeline) and every run, exposed
through `/dashboard/agents`, `/dashboard/activity`, and `/dashboard/tasks`. This
is process-local and ephemeral by design; the `tool_calls` / `tasks` tables can
back it durably later.

### Run it

```
# backend (terminal 1)
make up                       # or: cd backend && uvicorn app.main:app --reload

# frontend (terminal 2)
cd frontend
cp .env.local.example .env.local      # set NEXT_PUBLIC_API_URL + NEXT_PUBLIC_USER_ID
npm install
npm run dev                           # http://localhost:3000
```

Set `NEXT_PUBLIC_USER_ID` to a real user UUID (the same one you connect Gmail /
Spotify for). The dashboard polls health and activity on a short interval.

### Design

Mission-control aesthetic: near-black layered background with a faint scanline
texture, IBM Plex Mono labels over IBM Plex Sans body, a single amber signal
accent, and status dots colored by outcome (green ok, amber held-for-approval,
red error). Typed API client in `lib/api.ts`; all panels are client components.

The full dashboard type-checks with `tsc --noEmit` (0 errors). `node_modules` is
not included in the zip; run `npm install` once.

## Phase 13: production deployment

Container images, a production compose file, Kubernetes manifests, and CI/CD.

### Images

- `backend/Dockerfile`: multi-stage. A builder compiles dependencies into a venv;
  the slim runtime copies that venv plus the app, runs as a non-root user, has a
  `HEALTHCHECK`, and serves via gunicorn supervising uvicorn workers
  (`WEB_CONCURRENCY`, default 4).
- `frontend/Dockerfile`: multi-stage Next.js standalone build. `NEXT_PUBLIC_*`
  values are inlined at build time, so the API URL the browser calls is passed
  as a build arg; the runner ships only the standalone server and static assets,
  as a non-root user.

### docker-compose.prod.yml

Builds both images, runs a one-shot `migrate` job (Alembic to head) that the
backend waits on via `service_completed_successfully`, then serves the API and
dashboard. Code is baked into images (no bind mounts), logs are JSON.

```
cp .env.example .env     # fill in secrets
docker compose -f docker-compose.prod.yml up -d --build
```

### Kubernetes (deploy/k8s)

`kubectl apply -k deploy/k8s` brings up: namespace, ConfigMap, Postgres / Redis /
Chroma StatefulSets with PVCs, a migration Job, backend and frontend Deployments
(2 replicas, rolling updates, liveness on `/health`, readiness on `/health/ready`,
resource requests/limits, dropped capabilities, non-root), an HPA for each, and a
host-based Ingress (app + api subdomains, TLS via cert-manager).

Secrets are deliberately NOT part of the kustomization, so `apply -k` can never
overwrite real credentials with placeholders. Create them out-of-band:

```
kubectl -n jarvis create secret generic jarvis-secrets \
  --from-literal=SECRET_KEY=$(openssl rand -hex 32) \
  --from-literal=POSTGRES_PASSWORD=... \
  --from-literal=CREDENTIAL_ENCRYPTION_KEY=$(python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())") \
  --from-literal=OPENAI_API_KEY=...
```

`02-secret.example.yaml` is a template showing the expected keys. Replace the
`ghcr.io/your-org/...` image references (and the `your-org` in CI) with your own.

### CI/CD (.github/workflows)

- `ci.yml` (PRs, non-main pushes): backend test suite (`EMBEDDING_PROVIDER=fake`,
  no keys needed), frontend `tsc --noEmit` + `next build`, and a no-push Docker
  build of both images to validate the Dockerfiles.
- `release.yml` (main pushes and `v*` tags): build and push both images to GHCR
  (frontend with the public API URL baked in), then on tags deploy to Kubernetes
  using a `KUBE_CONFIG` secret: apply manifests, run the migration Job to
  completion, pin both deployments to the released tag, and wait for rollout.

### Verified here

All YAML (manifests, both compose files, both workflows) parses cleanly, the
frontend type-checks, and the backend suite is 84 passing. The image builds,
registry push, and cluster apply require Docker / a registry / a cluster, which
are outside this environment, so those steps are provided ready to run rather
than executed here.

### Notes

- The browser agent needs a Chromium binary; the slim backend image does not
  install one (it would roughly double the image). Add `playwright install
  --with-deps chromium` to the backend Dockerfile if you rely on that agent in
  production.
- For fully reproducible frontend installs, run `npm install` once locally to
  generate `package-lock.json`, commit it, and the Dockerfile/CI will use
  `npm ci` automatically.
