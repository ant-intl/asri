"""
Pluggable tracing middleware.

Delegates span creation / closure to the configured tracer backend.
With ``NoopTracer`` this is a transparent pass-through.
"""
from django.utils.deprecation import MiddlewareMixin


class TracerMiddleware(MiddlewareMixin):
    """Django middleware that delegates to the configured tracer."""

    def process_request(self, request):
        """Start a request span."""
        from .base import get_tracer

        tracer = get_tracer()
        span = tracer.start_request_span(request)
        request._tracer_span = span

    def process_response(self, request, response):
        """End the request span."""
        from .base import get_tracer

        span = getattr(request, '_tracer_span', None)
        if span is not None:
            tracer = get_tracer()
            tracer.end_request_span(span, response)
        return response
