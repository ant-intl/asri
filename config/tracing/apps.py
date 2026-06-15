"""
Django AppConfig for the pluggable tracing module.
"""
from django.apps import AppConfig


class TracingAppConfig(AppConfig):
    """Initialize the tracer backend at Django startup."""

    name = 'config.tracing'
    verbose_name = 'Tracing'

    def ready(self) -> None:
        """Initialize the configured tracer."""
        from django.conf import settings
        from .base import get_tracer

        config = getattr(settings, 'TRACING_CONFIG', {})
        tracer = get_tracer()
        tracer.initialize(config)
