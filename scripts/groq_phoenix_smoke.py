"""Send one Groq LLM call and one trace to local Phoenix."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from groq import Groq
from opentelemetry import trace
from phoenix.otel import register

from src.config import Settings, load_settings


SMOKE_PROMPT = (
    "In one sentence, say what an incident triage agent should return after "
    "investigating payment-api errors caused by postgres-main connection pressure."
)
SPAN_NAME = "groq.chat.completions.create"
LLM_SYSTEM = "groq"
MAX_COMPLETION_TOKENS = 300
TEMPERATURE = 0.0


@dataclass(frozen=True, slots=True)
class GroqSmokeResult:
    """Groq smoke test result."""

    model: str
    content: str
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None


def run_smoke(settings: Settings) -> GroqSmokeResult:
    """Run one traced Groq completion."""
    require_groq_api_key(settings)
    tracer_provider = register(
        project_name=settings.phoenix_project_name,
        endpoint=settings.otel_exporter_otlp_endpoint,
        protocol="grpc",
        batch=False,
    )
    try:
        return create_traced_completion(settings)
    finally:
        tracer_provider.shutdown()


def require_groq_api_key(settings: Settings) -> None:
    """Require a Groq API key."""
    if not settings.groq_api_key or settings.groq_api_key == "change-me":
        msg = "Add GROQ_API_KEY to the ignored .env file before running this smoke test"
        raise ValueError(msg)


def create_traced_completion(settings: Settings) -> GroqSmokeResult:
    """Create one traced Groq completion."""
    client = Groq(
        api_key=settings.groq_api_key,
        base_url=groq_sdk_base_url(settings.groq_base_url),
        timeout=settings.http_timeout_seconds,
    )
    tracer = trace.get_tracer(__name__)
    with tracer.start_as_current_span(SPAN_NAME) as span:
        span.set_attribute("llm.system", LLM_SYSTEM)
        span.set_attribute("llm.model_name", settings.groq_model)
        span.set_attribute("input.value", SMOKE_PROMPT)
        completion = client.chat.completions.create(
            messages=message_payload(),
            model=settings.groq_model,
            temperature=TEMPERATURE,
            max_completion_tokens=MAX_COMPLETION_TOKENS,
        )
        result = result_from_completion(settings.groq_model, completion)
        span.set_attribute("output.value", result.content)
        set_usage_attributes(span, result)
        return result


def message_payload() -> list[dict[str, str]]:
    """Return the smoke prompt payload."""
    return [{"role": "user", "content": SMOKE_PROMPT}]


def groq_sdk_base_url(base_url: str) -> str:
    """Return a base URL compatible with the Groq SDK."""
    return base_url.removesuffix("/openai/v1").rstrip("/")


def result_from_completion(model: str, completion: Any) -> GroqSmokeResult:
    """Return a typed smoke result."""
    message = completion.choices[0].message
    usage = getattr(completion, "usage", None)
    return GroqSmokeResult(
        model=model,
        content=message.content or "",
        prompt_tokens=get_optional_int(usage, "prompt_tokens"),
        completion_tokens=get_optional_int(usage, "completion_tokens"),
        total_tokens=get_optional_int(usage, "total_tokens"),
    )


def get_optional_int(value: Any, name: str) -> int | None:
    """Return one optional integer attribute."""
    raw = getattr(value, name, None)
    return None if raw is None else int(raw)


def set_usage_attributes(span: Any, result: GroqSmokeResult) -> None:
    """Set token usage attributes on one span."""
    if result.prompt_tokens is not None:
        span.set_attribute("llm.token_count.prompt", result.prompt_tokens)
    if result.completion_tokens is not None:
        span.set_attribute("llm.token_count.completion", result.completion_tokens)
    if result.total_tokens is not None:
        span.set_attribute("llm.token_count.total", result.total_tokens)


def main() -> None:
    """Run the smoke test from the command line."""
    try:
        result = run_smoke(load_settings())
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    print(f"model={result.model}")
    print(f"total_tokens={result.total_tokens}")
    print(result.content)


if __name__ == "__main__":
    main()
