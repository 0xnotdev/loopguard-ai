
try:

    from arize.otel import register
    from openinference.instrumentation.litellm import (
        LiteLLMInstrumentor
    )
    from opentelemetry import trace

    PHOENIX_ENABLED = True

except Exception:

    PHOENIX_ENABLED = False


def setup_tracing():

    if not PHOENIX_ENABLED:

        print("Phoenix disabled in production")

        return None

    tracer_provider = register(
        project_name="loopguard_ai"
    )

    LiteLLMInstrumentor().instrument(
        tracer_provider=tracer_provider
    )

    print("✓ Phoenix tracing initialized")

    return trace.get_tracer(__name__)


tracer = setup_tracing()


def inject_deadlock_span(
    session_id: str,
    similarity: float,
    tokens_saved: int
):

    if not tracer:
        return

    with tracer.start_as_current_span(
        "FaultType.DEADLOCK_INJECTION"
    ) as span:

        span.set_attribute(
            "session_id",
            session_id
        )

        span.set_attribute(
            "similarity_score",
            similarity
        )

        span.set_attribute(
            "tokens_saved_estimate",
            tokens_saved
        )

        span.set_attribute(
            "circuit_state",
            "OPEN"
        )