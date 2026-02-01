"""Structured logging configuration for MetaGate.

This module provides JSON-formatted structured logging with trace IDs
for production observability and easier log parsing.
"""
import logging
import sys
import uuid
from contextvars import ContextVar
from typing import Any

import structlog
from structlog.types import Processor

from .config import get_settings

# Context variable for request trace ID
trace_id_var: ContextVar[str | None] = ContextVar("trace_id", default=None)


def get_trace_id() -> str | None:
    """Get the current trace ID from context."""
    return trace_id_var.get()


def set_trace_id(trace_id: str | None = None) -> str:
    """Set a trace ID in context, generating one if not provided."""
    if trace_id is None:
        trace_id = str(uuid.uuid4())[:8]
    trace_id_var.set(trace_id)
    return trace_id


def add_trace_id(
    logger: logging.Logger, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Add trace ID to log events."""
    trace_id = get_trace_id()
    if trace_id:
        event_dict["trace_id"] = trace_id
    return event_dict


def add_service_info(
    logger: logging.Logger, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Add service metadata to log events."""
    settings = get_settings()
    event_dict["service"] = "metagate"
    event_dict["version"] = settings.metagate_version
    event_dict["instance_id"] = settings.instance_id
    return event_dict


def configure_logging() -> structlog.stdlib.BoundLogger:
    """Configure structured logging based on environment.

    In debug mode: Human-readable console output with colors
    In production: JSON-formatted logs for observability systems

    Returns:
        Configured structlog logger instance
    """
    settings = get_settings()

    # Common processors for all environments
    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        add_trace_id,
        add_service_info,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    if settings.debug:
        # Development: human-readable console output
        processors: list[Processor] = shared_processors + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ]
        formatter = structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared_processors,
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.dev.ConsoleRenderer(colors=True),
            ],
        )
    else:
        # Production: JSON output for log aggregation systems
        processors = shared_processors + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ]
        formatter = structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared_processors,
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.processors.JSONRenderer(),
            ],
        )

    # Configure structlog
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Configure standard logging to use structlog formatter
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.DEBUG if settings.debug else logging.INFO)

    # Reduce noise from third-party libraries
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.error").setLevel(logging.INFO)
    logging.getLogger("asyncpg").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

    return structlog.get_logger("metagate")


def get_logger(name: str = "metagate") -> structlog.stdlib.BoundLogger:
    """Get a structured logger instance.

    Args:
        name: Logger name for categorization

    Returns:
        Configured structlog logger
    """
    return structlog.get_logger(name)
