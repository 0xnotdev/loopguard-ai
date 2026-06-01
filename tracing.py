import os
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

from openinference.instrumentation.litellm import LiteLLMInstrumentor


def setup_tracing():

    # Local Phoenix collector endpoint
    os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = "http://localhost:6006"

    tracer_provider = TracerProvider()

    tracer_provider.add_span_processor(
        BatchSpanProcessor(
            OTLPSpanExporter(
                endpoint="http://localhost:6006/v1/traces"
            )
        )
    )

    trace.set_tracer_provider(tracer_provider)

    # Auto-instrument LiteLLM
    LiteLLMInstrumentor().instrument(
        tracer_provider=tracer_provider
    )

    print("✓ Local Phoenix tracing initialized")

    return trace.get_tracer(__name__)


tracer = setup_tracing()


def inject_deadlock_span(
    session_id: str,
    similarity: float,
    tokens_saved: int
):

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