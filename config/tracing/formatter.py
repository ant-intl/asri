"""
Tracer-aware log formatter.

Injects ``trace_id`` and ``rpc_id`` into every log record via the
configured tracer backend.
"""
import logging


class TracerLogFormatter(logging.Formatter):
    """Log formatter that injects trace_id and rpc_id from the active tracer."""

    def format(self, record: logging.LogRecord) -> str:
        """Format log record with trace information."""
        from .base import get_tracer

        tracer = get_tracer()
        record.trace_id = tracer.get_trace_id()
        record.rpc_id = tracer.get_rpc_id()
        return super().format(record)
