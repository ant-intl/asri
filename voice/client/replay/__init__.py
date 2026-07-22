"""Replay client — drives seed rows through the realtime Heartbeat chain.

Submodules:

* ``server_pool`` — manage N realtime server subprocesses (one port per
  worker).
* ``replay_session`` — drive one seed row through a single realtime
  server via WebSocket (no subprocess call to
  ``heartbeat_audio_client.py``).
* ``trace_builder`` — turn raw WebSocket event records into a structured
  ``heartbeat_replay_trace.v1`` trace.
* ``sft_sample_builder`` — turn a trace into ShareGPT-style thinking and
  response SFT samples.
* ``runner`` — the ``main()`` entrypoint that ties everything together.
"""
