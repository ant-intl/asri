"""
Pluggable tracing abstraction for ASRI.

Provides a BaseTracer interface with a NoopTracer default.
External packages can register custom tracers via entry_points('asri.tracers').
"""
from .base import BaseTracer, NoopTracer, get_tracer
from .formatter import TracerLogFormatter
from .middleware import TracerMiddleware

__all__ = [
    'BaseTracer',
    'NoopTracer',
    'get_tracer',
    'TracerLogFormatter',
    'TracerMiddleware',
]
