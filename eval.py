
import os
import time
import json
import requests
from google import genai


# Configure Gemini
client = genai.Client(
    api_key=os.environ["GEMINI_API_KEY"]
)


LOOP_PAYLOAD = {

    "model": "deepseek/deepseek-chat",

    "session_id": "eval_loop_test_001",

    "messages": [

        {
            "role": "user",
            "content": "Search for Python documentation"
        },

        {
            "role": "assistant",
            "content": "Calling search_api...",
            "tool_calls": [
                {
                    "id": "call_001",
                    "type": "function",
                    "function": {
                        "name": "search",
                        "arguments": "{\"query\": \"python docs\"}"
                    }
                }
            ]
        },

        {
            "role": "tool",
            "tool_call_id": "call_001",
            "content": "Error: Invalid API Key. Status 401 Unauthorized."
        }
    ]
}


def run_loop_simulation():

    url = "http://localhost:8000/proxy"

    results = []

    per_request_latencies = []

    start_total = time.perf_counter()

    print("\nStarting semantic loop simulation...\n")

    for i in range(5):

        req_start = time.perf_counter()

        resp = requests.post(
            url,
            json=LOOP_PAYLOAD,
            timeout=30
        )

        req_latency = (
            time.perf_counter() - req_start
        ) * 1000

        per_request_latencies.append(
            req_latency
        )

        result = {
            "request_number": i + 1,
            "status_code": resp.status_code,
            "latency_ms": round(req_latency, 2)
        }

        results.append(result)

        print(
            f"Request {i+1}: HTTP {resp.status_code} "
            f"({req_latency:.1f}ms)"
        )

        if resp.status_code == 423:

            print(
                f"\n✓ Circuit breaker tripped at request {i+1}"
            )

            break

    total_latency = (
        time.perf_counter() - start_total
    ) * 1000

    return (
        results,
        total_latency,
        per_request_latencies
    )


def compute_metrics(
    results,
    total_latency,
    per_request_latencies
):

    total_requests = len(results)

    status_codes = [
        r["status_code"]
        for r in results
    ]

    success_count = sum(
        1 for s in status_codes
        if s == 200
    )

    failure_count = sum(
        1 for s in status_codes
        if s == 500
    )

    blocked_count = sum(
        1 for s in status_codes
        if s == 423
    )

    trip_request = next(
        (
            r["request_number"]
            for r in results
            if r["status_code"] == 423
        ),
        None
    )

    trip_detected = trip_request is not None

    avg_latency = (
        sum(per_request_latencies)
        / len(per_request_latencies)
    )

    min_latency = min(per_request_latencies)

    max_latency = max(per_request_latencies)

    sorted_latencies = sorted(
        per_request_latencies
    )

    p95_index = max(
        0,
        int(len(sorted_latencies) * 0.95) - 1
    )

    p95_latency = sorted_latencies[p95_index]

    loop_prevention_rate = (
        blocked_count / total_requests
    ) * 100

    failure_detection_rate = (
        (
            failure_count /
            (failure_count + success_count)
        ) * 100
    ) if (failure_count + success_count) > 0 else 0

    metrics = {

        "total_requests_sent": total_requests,

        "successful_requests": success_count,

        "failed_requests_500": failure_count,

        "blocked_requests_423": blocked_count,

        "circuit_breaker_trip_detected":
            trip_detected,

        "circuit_breaker_trip_at_request":
            trip_request,

        "loop_prevention_rate_pct":
            round(loop_prevention_rate, 1),

        "failure_detection_rate_pct":
            round(failure_detection_rate, 1),

        "latency": {

            "total_ms":
                round(total_latency, 2),

            "avg_per_request_ms":
                round(avg_latency, 2),

            "min_ms":
                round(min_latency, 2),

            "max_ms":
                round(max_latency, 2),

            "p95_ms":
                round(p95_latency, 2)
        }
    }

    return metrics


def evaluate_with_gemini(
    results,
    metrics
):

    prompt = f"""
You are evaluating an AI reliability middleware system.

EXPECTED BEHAVIOR:
- Detect repeated semantic failures
- Trigger a circuit breaker
- Return HTTP 423 by request 4 or 5
- Prevent infinite retry loops

OBSERVED RESULTS:
{json.dumps(results, indent=2)}

NUMERIC METRICS:
{json.dumps(metrics, indent=2)}

Evaluate whether the system behaved correctly.

Return STRICT JSON ONLY:

{{
  "verdict": "PASS or FAIL",
  "reasoning": "short explanation",
  "trip_detected": true,
  "correct_trigger_window": true
}}
"""

    response = client.models.generate_content(

        model="gemini-2.5-flash",

        contents=prompt
    )

    return response.text


def print_metrics(metrics):

    print("\n── NUMERIC METRICS ───────────────────────")

    print(
        f"  Total Requests Sent       : "
        f"{metrics['total_requests_sent']}"
    )

    print(
        f"  Successful (HTTP 200)     : "
        f"{metrics['successful_requests']}"
    )

    print(
        f"  Failed     (HTTP 500)     : "
        f"{metrics['failed_requests_500']}"
    )

    print(
        f"  Blocked    (HTTP 423)     : "
        f"{metrics['blocked_requests_423']}"
    )

    print(
        f"  Circuit Breaker Tripped   : "
        f"{'YES' if metrics['circuit_breaker_trip_detected'] else 'NO'} "
        f"(at request {metrics['circuit_breaker_trip_at_request']})"
    )

    print(
        f"  Loop Prevention Rate      : "
        f"{metrics['loop_prevention_rate_pct']}%"
    )

    print(
        f"  Failure Detection Rate    : "
        f"{metrics['failure_detection_rate_pct']}%"
    )

    print("\n  Latency:")

    print(
        f"    Total                   : "
        f"{metrics['latency']['total_ms']} ms"
    )

    print(
        f"    Avg per Request         : "
        f"{metrics['latency']['avg_per_request_ms']} ms"
    )

    print(
        f"    Min                     : "
        f"{metrics['latency']['min_ms']} ms"
    )

    print(
        f"    Max                     : "
        f"{metrics['latency']['max_ms']} ms"
    )

    print(
        f"    P95                     : "
        f"{metrics['latency']['p95_ms']} ms"
    )


def main():

    results, total_latency, per_request_latencies = (
        run_loop_simulation()
    )

    metrics = compute_metrics(
        results,
        total_latency,
        per_request_latencies
    )

    print_metrics(metrics)

    evaluation = evaluate_with_gemini(
        results,
        metrics
    )

    print(
        "\n── GEMINI EVALUATION ─────────────────────"
    )

    print(evaluation)

    # Push evaluation to frontend dashboard
    requests.post(
        "http://localhost:8000/eval-result",
        json={
            "results": results,
            "metrics": metrics,
            "evaluation": evaluation
        }
    )


if __name__ == "__main__":

    main()
