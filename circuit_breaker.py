from schemas import CircuitBreakerState, LoopDetectedError
import time

states = {}  # In-memory session registry


class TokenBucket:
    def __init__(self, capacity: int, refill_rate: float):
        self.capacity = capacity
        self.tokens = capacity
        self.refill_rate = refill_rate
        self.last_update = time.time()

    def consume(self) -> bool:
        now = time.time()

        # Refill tokens based on elapsed time
        self.tokens += (now - self.last_update) * self.refill_rate
        self.tokens = min(self.capacity, self.tokens)

        self.last_update = now

        if self.tokens >= 1:
            self.tokens -= 1
            return True

        return False


def evaluate_circuit(session_id: str, similarity: float):

    if session_id not in states:
        states[session_id] = {
            "state": CircuitBreakerState.CLOSED,
            "count": 0,
            "bucket": TokenBucket(
                capacity=10,
                refill_rate=1.0
            )
        }

    session = states[session_id]

    # Layer 1: volumetric protection
    if not session["bucket"].consume():
        raise Exception("Rate limit exceeded for session")

    # Layer 2: semantic circuit breaker
    if session["state"] == CircuitBreakerState.OPEN:
        raise LoopDetectedError(session_id, similarity)

    if session["state"] == CircuitBreakerState.HALF_OPEN:

        if similarity > 0.92:
            session["state"] = CircuitBreakerState.OPEN
            raise LoopDetectedError(session_id, similarity)

        else:
            session["state"] = CircuitBreakerState.CLOSED
            session["count"] = 0
            return True

    # CLOSED state behavior
    if similarity > 0.92:

        session["count"] += 1

        # 4 consecutive semantic hits -> OPEN
        if session["count"] >= 4:
            session["state"] = CircuitBreakerState.OPEN
            raise LoopDetectedError(session_id, similarity)

    else:
        # Healthy request -> decay counter
        session["count"] = max(0, session["count"] - 1)

    return True