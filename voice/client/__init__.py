"""Client-side helpers for talking to the realtime server.

This package is intentionally separate from ``src/`` so that client code
(audio loading, WebSocket plumbing, replay bookkeeping) does not pull in
the server runtime.  Modules here are imported by the scripts in
``scripts/`` and by the replay entrypoints under ``client/replay/``.
"""
