# loopguard-ai
# loopguard-ai

Most agent failures aren't crashes. They're loops — the model gets stuck, reformulates the same request slightly differently, and keeps firing. You burn tokens, hit rate limits, and the task never completes.

LoopGuard is a proxy that sits in front of your LLM calls and detects this semantically. Not by matching strings. By embedding every request and comparing it against what the same session has already asked. When a session starts going in circles, the circuit breaker trips and the call is blocked — HTTP 423, before the downstream model ever sees it.

Live: [loopguard-ai.vercel.app](https://loopguard-ai.vercel.app)  
Backend: [loopguard-ai.onrender.com](https://loopguard-ai.onrender.com)  
API docs: [loopguard-ai.onrender.com/docs](https://loopguard-ai.onrender.com/docs)

---

## Why this exists

Token limits and rate limits are the obvious failure modes people plan for. Loops are subtler. An agent working through a multi-step task can end up issuing semantically identical requests across several turns without ever repeating the exact same string. Standard deduplication misses this completely.

The fix is embeddings + a circuit breaker. Embed the request, store it, compare it to the last few requests in the session. If the similarity is high enough, consistently enough, something is wrong — and you stop it before it gets worse.

---

## How a request moves through the system

```
your agent
    │
    ▼
POST /proxy  ──►  embed messages (all-MiniLM-L6-v2, 384d)
                       │
                       ▼
              pgvector similarity check
              against last 5 embeddings
              in this session
                       │
                  sim > 0.92?
                  /          \
                yes            no
                 │              │
           increment        forward to
           trip counter      OpenRouter
                │            via LiteLLM
          counter >= 4?
          /          \
        yes            no
         │              │
      HTTP 423       HTTP 200
    (loop blocked)  (pass through)
```

The window is capped at 5 embeddings per session. Old ones get pruned. This keeps the comparison local to what the agent has been doing recently, not its entire history.

---

## Circuit breaker states

Each session has its own independent state machine. Sessions don't share state.

**CLOSED** — normal. Requests go through. Every time similarity exceeds 0.92, a counter increments. Every time a request comes in below the threshold, the counter decays by 1. Four consecutive hits and the session moves to OPEN.

**OPEN** — blocked. Every request raises `LoopDetectedError` immediately. No DB query, no embedding comparison, no LLM call. The session stays here until manually reset.

**HALF_OPEN** — recovery. One probe is allowed through. If similarity is still high, back to OPEN. If it's clean, reset to CLOSED with the counter at zero.

On top of the semantic layer, each session also has a token bucket — capacity 10, refill rate 1/sec. This is volumetric rate limiting that runs independently of loop detection. A session can be rate-limited without a loop being detected, and vice versa.

---

## The dashboard

The frontend connects to `GET /stream` and updates in real time via SSE.

![dashboard](screenshots/dashboard.png)

Top bar shows aggregate session stats: total calls, successful (200), upstream errors (500), trips fired, estimated tokens saved (rough estimate at ~2500 per trip), and detection rate.

Left panel is a live request log. Each entry shows timestamp, HTTP status, session ID, and the similarity score that was computed for that request. Trips show `BREAKER OPEN` in red. The similarity score is always shown — you can watch it climb across consecutive requests in a looping session.

Right panel has three tabs: call rate over time, status mix, and similarity trend. Below that is the latest Gemini evaluation result — verdict, reasoning, and the full metrics breakdown from the most recent eval run.

When the breaker trips, a banner appears across the top:

```
● CIRCUIT BREAKER OPEN — LOOP DETECTED — DOWNSTREAM REQUESTS REJECTED
```

---

## Eval harness

`eval.py` runs a controlled test: sends semantically identical messages across four requests to a known session, then has Gemini score the outcome.

```
Request 1: HTTP 200 (34319.0ms)
Request 2: HTTP 200 (15037.3ms)
Request 3: HTTP 200 (11743.4ms)
Request 4: HTTP 423 (5195.2ms)

✓ Circuit breaker tripped at request 4

— NUMERIC METRICS —
  Total Requests Sent        : 4
  Successful  (HTTP 200)     : 3
  Blocked     (HTTP 423)     : 1
  Circuit Breaker Tripped    : YES (at request 4)
  Loop Prevention Rate       : 25.0%
  Failure Detection Rate     : 0.0%

  Latency:
    Avg per Request          : 16573.73ms
    Min                      : 5195.15ms
    Max                      : 34318.98ms
    P95                      : 15037.35ms
```

Gemini's verdict on this run was **FAIL** — not because the trip didn't happen (it did, at exactly the right request), but because `failure_detection_rate_pct` was 0.0. The breaker tripped on the count heuristic (4 high-similarity requests in a row) rather than on detection of semantic failure signals in the response outputs. The trip itself was correct. The eval scoring is stricter than the mechanism.

This is a known open issue — the eval and the circuit breaker are currently measuring slightly different things.

---

## API

Full OpenAPI spec at `/openapi.json`, interactive docs at `/docs`.

![swagger](screenshots/swagger.png)

### POST /proxy

The main endpoint. Drop-in replacement for a direct LiteLLM/OpenRouter call.

```json
{
  "session_id": "agent-session-abc123",
  "model": "openai/gpt-4o",
  "messages": [
    { "role": "user", "content": "check if the build finished" }
  ]
}
```

`session_id` is how the proxy tracks per-agent state. Use the same ID across a conversation or task run. Use a different one for a new independent task.

Returns the raw LiteLLM completion on success (`200`), or this on a trip:

```
HTTP 423 Locked
"Loop Detected! Session agent-session-abc123 blocked. Similarity: 0.9823"
```

### GET /stream

Server-sent events. Connect and receive a new JSON event for every request that passes through the proxy.

```json
{ "type": "success", "session": "abc123", "sim": 0.41, "latency_ms": 312.5 }
{ "type": "trip",    "session": "abc123", "sim": 0.98, "latency_ms": 28.1  }
{ "type": "fail",    "session": "abc123", "latency_ms": 14.2               }
{ "type": "evaluation", "payload": { ... } }
```

### POST /reset/{session_id}

Resets a session from OPEN back to HALF_OPEN. The next request from that session will be used as a probe — if it's clean, the session recovers. If not, it goes back to OPEN.

```json
{ "message": "Session agent-session-abc123 reset to HALF_OPEN" }
```

### POST /eval-result

Pushes an evaluation result payload into the SSE stream. Used by `eval.py` to get Gemini's scoring visible in the dashboard in real time.

### GET /health

```json
{ "status": "alive" }
```

---

## Deployment

Backend runs on Render. Free tier, so the instance spins down after inactivity.

![render](screenshots/render.png)

First request after a cold start can take 50+ seconds while the instance wakes up, the DB pool initialises, and the embedding model loads into memory. Subsequent requests are fast.

To keep the instance warm, a cron job on cron-job.org hits `/health` every 15 minutes.

![cronjob](screenshots/cronjob.png)

Last execution: 5:00 PM, 226ms. Next at 5:15 PM. It works.

Frontend is on Vercel. CORS on the backend is locked to `https://loopguard-ai.vercel.app`.

---

## Running locally

Requirements: Python 3.12, Postgres with pgvector, an OpenRouter API key.

```bash
git clone https://github.com/0xnotdev/loopguard-ai
cd loopguard-ai
pip install -r requirements.txt
```

```bash
export DATABASE_URL="postgresql://user:pass@localhost:5432/loopguard"
export OPENROUTER_API_KEY="sk-or-..."
```

```bash
uvicorn main:app --reload
```

The `session_windows` table and the `vector` extension are created automatically on first startup if they don't already exist. No migration tooling needed.

Run the eval:

```bash
python eval.py
```

Run load tests:

```bash
locust -f locustfile.py
```

---

## Project layout

```
main.py              FastAPI app, all route handlers, startup logic
circuit_breaker.py   Per-session state machine, token bucket, LoopDetectedError
database.py          asyncpg connection pool, pgvector upsert, similarity query
embedder.py          sentence-transformers wrapper with lazy model loading
schemas.py           Pydantic request/response models, enums, exceptions
tracing.py           OpenTelemetry span injection on loop detection events
eval.py              Controlled eval harness, Gemini scoring, metrics output
locustfile.py        Locust load test scenarios
frontend/            Dashboard — SSE consumer, charts, request log
.github/workflows/   CI
.devcontainer/       Dev container config
```

---

## Known issues and gaps

**In-memory session state.** The `states` dict in `circuit_breaker.py` is process-local. Restart the server and all session states are gone. Run two instances and they don't share state. For anything beyond a single-process deployment, this needs to move to Redis.

**Hardcoded thresholds.** The 0.92 similarity threshold and the 4-hit trip count are constants in the code. Different use cases have different tolerances — a coding agent re-reading a file looks very different from a support bot asking the same question. These should be configurable per-session or at least per-deployment.

**Naive embedding of the full message array.** `embedder.py` concatenates all messages and encodes the whole thing as one vector. A very long context will produce an embedding that averages out fine-grained signal from just the recent tail of the conversation, which is where repetition actually shows up. Embedding only the last N messages, or the last user turn, would be more targeted.

**Single global SSE queue.** Multiple clients connecting to `/stream` will split events between them. There's no fan-out — the first client to read an event consumes it. This is fine for a single dashboard but breaks if you want multiple consumers.

**Eval vs. mechanism mismatch.** The eval scores on `failure_detection_rate_pct` which currently comes out at 0 even on correct trips. The circuit breaker is operating as intended but the eval is measuring something the current implementation doesn't explicitly track. The scoring and the mechanism need to be aligned.