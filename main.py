from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware

import litellm
import asyncio
import json
import os
import time

from schemas import (
    ProxyRequest,
    LoopDetectedError,
    CircuitBreakerState
)

from database import (
    get_pool,
    upsert_and_check_similarity
)

from embedder import embed_request

from circuit_breaker import (
    evaluate_circuit,
    states
)

from tracing import inject_deadlock_span


app = FastAPI(
    title="LoopGuard AI",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

db_pool = None

event_queue: asyncio.Queue = None


@app.on_event("startup")
async def startup():

    global db_pool, event_queue

    # TEMPORARILY DISABLED
    # db_pool = await get_pool()

    event_queue = asyncio.Queue()

    print("✓ Startup complete")

@app.get("/health")
async def health():
    return {"status": "alive"}


@app.post("/proxy")
async def proxy_endpoint(req: ProxyRequest):

    request_start = time.perf_counter()

    try:
        # Step 1: Semantic embedding generation
        embedding = embed_request(req.messages)

        # Step 2: Store + compare in pgvector
        max_sim = await upsert_and_check_similarity(
            db_pool,
            req.session_id,
            embedding
        )

        # Step 3: Circuit breaker evaluation
        evaluate_circuit(
            req.session_id,
            max_sim
        )

        # Step 4: Forward request to OpenRouter via LiteLLM
        response = await litellm.acompletion(
            model=f"openrouter/{req.model}",
            messages=req.messages,
            api_key=os.environ["OPENROUTER_API_KEY"],
            base_url="https://openrouter.ai/api/v1"
        )

        latency_ms = (time.perf_counter() - request_start) * 1000

        await event_queue.put({
            "type": "success",
            "session": req.session_id,
            "sim": max_sim,
            "latency_ms": round(latency_ms, 2)
        })

        return response

    except LoopDetectedError as e:

        latency_ms = (time.perf_counter() - request_start) * 1000

        inject_deadlock_span(
            e.session_id,
            e.similarity,
            tokens_saved=2500
        )

        await event_queue.put({
            "type": "trip",
            "session": e.session_id,
            "sim": e.similarity,
            "latency_ms": round(latency_ms, 2)
        })

        raise HTTPException(
            status_code=423,
            detail=e.message
        )

    except Exception as e:

        latency_ms = (time.perf_counter() - request_start) * 1000

        print("ERROR:", str(e))

        await event_queue.put({
            "type": "fail",
            "session": req.session_id,
            "latency_ms": round(latency_ms, 2)
        })

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )


async def sse_generator():
    while True:
        event = await event_queue.get()
        yield f"data: {json.dumps(event)}\n\n"


@app.get("/stream")
async def stream_events():
    return StreamingResponse(
        sse_generator(),
        media_type="text/event-stream"
    )


@app.post("/eval-result")
async def receive_eval_result(payload: dict):
    await event_queue.put({
        "type": "evaluation",
        "payload": payload
    })
    return {"status": "received"}


@app.post("/reset/{session_id}")
async def reset_circuit(session_id: str):
    if session_id in states:
        states[session_id]["state"] = CircuitBreakerState.HALF_OPEN
        states[session_id]["count"] = 0
    return {"message": f"Session {session_id} reset to HALF_OPEN"}