"""
Base tracer interface and NoopTracer default implementation.

Supports plugin discovery via ``importlib.metadata.entry_points('asri.tracers')``.
"""
import logging
from abc import ABC, abstractmethod
from typing import Any, Optional

logger = logging.getLogger(__name__)

_tracer_instance: Optional['BaseTracer'] = None


class BaseTracer(ABC):
    """Abstract base class for tracer implementations."""

    @abstractmethod
    def initialize(self, config: dict) -> None:
        """Initialize the tracer with configuration.

        Called once at Django startup from ``TracingAppConfig.ready()``.

        Args:
            config: ``settings.TRACING_CONFIG`` dict.
        """

    @abstractmethod
    def get_trace_id(self) -> str:
        """Return the current request trace ID, or ``'N/A'``."""

    @abstractmethod
    def get_rpc_id(self) -> str:
        """Return the current RPC ID, or ``'N/A'``."""

    @abstractmethod
    def get_active_span(self) -> Optional[Any]:
        """Return the active span object, or ``None``."""

    @abstractmethod
    def start_request_span(self, request: Any) -> Optional[Any]:
        """Start a span for the incoming HTTP request."""

    @abstractmethod
    def end_request_span(self, span: Any, response: Any) -> None:
        """End the span started for the request."""


class NoopTracer(BaseTracer):
    """No-operation tracer — default when no backend is configured."""

    def initialize(self, config: dict) -> None:
        logger.debug("NoopTracer initialized (tracing disabled)")

    def get_trace_id(self) -> str:
        return "N/A"

    def get_rpc_id(self) -> str:
        return "N/A"

    def get_active_span(self) -> Optional[Any]:
        return None

    def start_request_span(self, request: Any) -> Optional[Any]:
        return None

    def end_request_span(self, span: Any, response: Any) -> None:
        pass


def get_tracer() -> BaseTracer:
    """Get the configured tracer instance (lazy-loaded singleton).

    Resolution order:
    1. If ``settings.TRACING_BACKEND`` is ``'noop'`` (default), use ``NoopTracer``.
    2. Otherwise scan ``entry_points(group='asri.tracers')`` for a matching name.
    """
    global _tracer_instance
    if _tracer_instance is not None:
        return _tracer_instance

    try:
        from django.conf import settings
        backend = getattr(settings, 'TRACING_BACKEND', 'noop')
    except Exception:
        backend = 'noop'

    if backend == 'noop':
        _tracer_instance = NoopTracer()
        return _tracer_instance

    # Discover via entry_points
    try:
        from importlib.metadata import entry_points
        eps = entry_points(group='asri.tracers')
        for ep in eps:
            if ep.name == backend:
                tracer_cls = ep.load()
                _tracer_instance = tracer_cls()
                logger.info(f"Loaded tracer backend: {backend}")
                return _tracer_instance
    except Exception as e:
        logger.warning(f"Failed to load tracer backend '{backend}': {e}")

    logger.warning(f"Tracer backend '{backend}' not found, falling back to NoopTracer")
    _tracer_instance = NoopTracer()
    return _tracer_instance
