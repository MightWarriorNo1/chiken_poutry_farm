"""Structured logging + OpenTelemetry bootstrap.

Keep this file dependency-light so the rest of the codebase can `import log` early.
"""

from __future__ import annotations

import logging
import sys

import structlog
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
)

from edge.config import Settings


def configure(settings: Settings) -> structlog.stdlib.BoundLogger:
    """Wire up structlog + OTel. Idempotent — safe to call multiple times."""
    _configure_logging(settings)
    _configure_tracing(settings)
    return structlog.get_logger("edge")


def _configure_logging(settings: Settings) -> None:
    level = getattr(logging, settings.telemetry.log_level.upper(), logging.INFO)
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=level,
        force=True,
    )

    processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    if settings.telemetry.log_format == "json":
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def _configure_tracing(settings: Settings) -> None:
    if settings.telemetry.otel_exporter == "none":
        return

    resource = Resource.create(
        {
            "service.name": "prosper-edge",
            "service.version": settings.software_version,
            "device.id": settings.device_id,
        }
    )
    provider = TracerProvider(resource=resource)

    if settings.telemetry.otel_exporter == "console":
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    elif settings.telemetry.otel_exporter == "otlp":
        # Lazy import — keep otlp deps optional.
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (  # noqa: PLC0415
            OTLPSpanExporter,
        )

        provider.add_span_processor(
            BatchSpanProcessor(
                OTLPSpanExporter(endpoint=settings.telemetry.otel_otlp_endpoint or None)
            )
        )

    trace.set_tracer_provider(provider)


def tracer(name: str = "edge") -> trace.Tracer:
    """Return a tracer; safe before configure() — falls back to NoOp."""
    return trace.get_tracer(name)
