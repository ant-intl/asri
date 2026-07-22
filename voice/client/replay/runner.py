"""Replay runner entrypoint.

This module ties everything together:

1. Parse CLI args.
2. Load seed rows from ``--input``.
3. Start a ``ServerPool`` with ``--jobs`` servers.
4. Dispatch rows to workers via ``ThreadPoolExecutor`` — each worker
   runs a ``ReplaySession`` against its dedicated server port.
5. Collect results, write summary/traces/thinking/response JSONL files.
6. Shut down the ``ServerPool``.

Usage::

    python -m client.replay.runner \\
        --input /tmp/replay_input.jsonl \\
        --out-dir /upfs/zhenyu/distillation_replay/test \\
        --config /tmp/replay_server_config.yaml \\
        --jobs 4 --limit 10
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from client.replay.replay_session import ReplaySession  # noqa: E402
from client.replay.server_pool import ServerPool  # noqa: E402
from distillation_replay.response_with_reference import (  # noqa: E402
    ResponseWithReferenceClient,
    ResponseWithReferenceConfig,
)
from distillation_replay.tool_trigger_judge import (  # noqa: E402
    ToolTriggerJudgeClient,
    ToolTriggerJudgeConfig,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Self-contained distillation replay runner with ServerPool")
    parser.add_argument("--input", required=True, help="JSONL produced by distillation_seed_preview.py")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--config", required=True, help="Server YAML config path")
    parser.add_argument("--limit", type=int, default=0, help="Optional total row limit")
    parser.add_argument("--jobs", type=int, default=1, help="Parallel workers (each gets its own server port)")
    parser.add_argument("--port-start", type=int, default=8765, help="First server port; subsequent workers use port_start+1, +2, ...")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument(
        "--speed",
        type=float,
        default=1.0,
        help=(
            "Audio send speed multiplier. Distillation replay must keep this at "
            "1.0; heartbeat and tool visibility are simulated on the virtual "
            "timeline instead of by fast-forwarding audio."
        ),
    )
    parser.add_argument("--client-timeout", type=float, default=90.0)
    parser.add_argument("--drain-after-transcription-s", type=float, default=3.0)
    parser.add_argument("--heartbeat-block-duration-ms", type=int, default=500)
    parser.add_argument("--tool-mock-simulated-latency-min-ms", type=int, default=20)
    parser.add_argument("--tool-mock-simulated-latency-max-ms", type=int, default=100)
    parser.add_argument("--response-with-reference-base-url", default=None)
    parser.add_argument("--response-with-reference-model", default=None)
    parser.add_argument("--response-with-reference-api-key", default="EMPTY")
    parser.add_argument("--response-with-reference-timeout-s", type=float, default=120.0)
    parser.add_argument("--tool-trigger-judge-base-url", default=None)
    parser.add_argument("--tool-trigger-judge-model", default=None)
    parser.add_argument("--tool-trigger-judge-api-key", default="EMPTY")
    parser.add_argument("--tool-trigger-judge-timeout-s", type=float, default=120.0)
    parser.add_argument(
        "--history-toolcall-drop-rate",
        type=float,
        default=0.6,
        help="Probability of dropping tool_calls from history turns to simulate heartbeat cover (0.0-1.0).",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from existing summary.jsonl — skip indices already processed successfully.",
    )
    return parser


def _response_with_reference_client_from_args(args: argparse.Namespace) -> ResponseWithReferenceClient | None:
    if not args.response_with_reference_base_url:
        return None
    config = ResponseWithReferenceConfig(
        base_url=args.response_with_reference_base_url,
        model=args.response_with_reference_model or "default",
        api_key=args.response_with_reference_api_key,
        timeout_s=args.response_with_reference_timeout_s,
    )
    return ResponseWithReferenceClient(config)


def _tool_trigger_judge_from_args(args: argparse.Namespace) -> ToolTriggerJudgeClient | None:
    if not args.tool_trigger_judge_base_url:
        return None
    config = ToolTriggerJudgeConfig(
        base_url=args.tool_trigger_judge_base_url,
        model=args.tool_trigger_judge_model or "default",
        api_key=args.tool_trigger_judge_api_key,
        timeout_s=args.tool_trigger_judge_timeout_s,
    )
    return ToolTriggerJudgeClient(config)


def _iter_rows(path: Path):
    with path.open(encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if line:
                row = json.loads(line)
                row["_input_line"] = line_no
                yield row


def _load_completed_indices(summary_path: Path) -> set[int]:
    """Load indices that have already been processed successfully.

    A sample is considered "successfully processed" if its summary entry
    has ``status == "ok"``. Failed or missing entries are not counted,
    so they will be retried on resume.
    """
    if not summary_path.exists():
        return set()
    completed: set[int] = set()
    with summary_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("status") == "ok":
                idx = entry.get("index")
                if isinstance(idx, int):
                    completed.add(idx)
    return completed


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.speed != 1.0:
        raise SystemExit("distillation replay must use --speed 1.0; use virtual time for heartbeat/tool latency")

    # Ensure local connections bypass any configured HTTP proxy.  The
    # replay client connects to the in-process server via
    # ``ws://127.0.0.1:<port>`` — if ``http_proxy``/``https_proxy`` are
    # set (as they must be on UCloud to reach the LLM/ASR endpoints),
    # the proxy would otherwise intercept the WebSocket upgrade request
    # and reject it with HTTP 403.
    no_proxy_values = {
        v.strip()
        for v in (os.environ.get("no_proxy") or os.environ.get("NO_PROXY") or "").split(",")
        if v.strip()
    }
    for v in ("127.0.0.1", "localhost", args.host):
        if v:
            no_proxy_values.add(v)
    os.environ["no_proxy"] = ",".join(sorted(no_proxy_values))
    os.environ["NO_PROXY"] = os.environ["no_proxy"]

    out_dir = Path(args.out_dir)
    work_dir = out_dir / "work"
    log_dir = out_dir / "logs"
    server_log_dir = out_dir / "server_logs"
    work_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)
    server_log_dir.mkdir(parents=True, exist_ok=True)

    summary_path = out_dir / "summary.jsonl"
    traces_jsonl_path = out_dir / "traces.jsonl"
    thinking_jsonl_path = out_dir / "heartbeat_thinking.jsonl"
    response_jsonl_path = out_dir / "heartbeat_response.jsonl"

    # Resume support: load already-completed indices and open files in append mode
    completed_indices: set[int] = set()
    file_mode = "a"
    if args.resume:
        completed_indices = _load_completed_indices(summary_path)
        print(f"[distill] Resume: {len(completed_indices)} samples already completed, skipping them", flush=True)

    rows = list(_iter_rows(Path(args.input)))
    if args.limit > 0:
        rows = rows[: args.limit]

    response_with_reference_client = _response_with_reference_client_from_args(args)
    tool_trigger_judge = _tool_trigger_judge_from_args(args)

    # Lock for thread-safe appends to shared JSONL files
    write_lock = threading.Lock()

    def _append_jsonl(path: Path, data: dict[str, Any]) -> None:
        """Append a single JSON line to *path* in a thread-safe manner."""
        with write_lock:
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(data, ensure_ascii=False) + "\n")

    def _append_thinking_samples(thinking_path: Path) -> None:
        """Append thinking samples from *thinking_path* to the shared JSONL."""
        if not thinking_path.exists():
            return
        with write_lock:
            with thinking_path.open("r", encoding="utf-8") as src:
                with thinking_jsonl_path.open("a", encoding="utf-8") as dst:
                    for line in src:
                        if line.strip():
                            dst.write(line)

    pool = ServerPool(
        config_path=args.config,
        pool_size=args.jobs,
        port_start=args.port_start,
        host=args.host,
        startup_timeout_s=120.0,
        log_dir=server_log_dir,
        env_overrides={
            "HEARTBEAT_REPLAY_TOOL_MOCK_SIMULATED_LATENCY_MIN_MS": str(args.tool_mock_simulated_latency_min_ms),
            "HEARTBEAT_REPLAY_TOOL_MOCK_SIMULATED_LATENCY_MAX_MS": str(args.tool_mock_simulated_latency_max_ms),
        },
    )
    try:
        pool.start()
        print(f"[distill] ServerPool ready: {len(pool.ports)} servers on ports {pool.ports[0]}-{pool.ports[-1]}", flush=True)

        # Each worker thread owns exactly one server port and processes
        # its assigned rows serially. This avoids "Only one concurrent
        # session is supported" errors from the realtime server.
        round_robin_idx = [0] * args.jobs
        port_to_rows: dict[int, list[tuple[int, dict[str, Any]]]] = {
            port: [] for port in pool.ports
        }
        for idx, row in enumerate(rows, start=1):
            # Skip already-completed samples when resuming
            if idx in completed_indices:
                continue
            worker_idx = (idx - 1) % args.jobs
            port = pool.ports[worker_idx]
            port_to_rows[port].append((idx, row))
            round_robin_idx[worker_idx] += 1

        def _is_transient_session_error(exc: Exception) -> bool:
            text = f"{type(exc).__name__}: {exc}"
            return any(
                marker in text
                for marker in (
                    "Only one concurrent session",
                    "timed out during opening handshake",
                    "opening handshake",
                )
            )

        def _server_session_state(worker_port: int) -> dict[str, Any] | None:
            url = f"http://{args.host}:{worker_port}/v1/debug/session"
            try:
                with urllib.request.urlopen(url, timeout=2.0) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except (OSError, urllib.error.URLError, json.JSONDecodeError):
                return None

        def _wait_for_server_idle(worker_port: int) -> None:
            """Wait until a one-session replay server has released its prior client."""
            timeout_s = max(0.0, float(os.getenv("HEARTBEAT_REPLAY_PORT_IDLE_TIMEOUT_S", "180")))
            poll_s = max(0.05, float(os.getenv("HEARTBEAT_REPLAY_PORT_IDLE_POLL_S", "0.25")))
            deadline = time.monotonic() + timeout_s
            last_state: dict[str, Any] | None = None
            while True:
                state = _server_session_state(worker_port)
                if state is not None:
                    last_state = state
                    if not state.get("active_session") and int(state.get("websocket_count") or 0) == 0:
                        return
                if time.monotonic() >= deadline:
                    raise TimeoutError(
                        f"server on port {worker_port} did not become idle within {timeout_s:.1f}s; "
                        f"last_state={last_state}"
                    )
                time.sleep(poll_s)

        def _run_one(idx_row: tuple[int, dict[str, Any]], worker_port: int) -> dict[str, Any]:
            idx, row = idx_row
            try:
                retry_attempts = max(1, int(os.getenv("HEARTBEAT_REPLAY_SESSION_RETRY_ATTEMPTS", "3")))
                retry_cooldown_s = max(0.0, float(os.getenv("HEARTBEAT_REPLAY_SESSION_RETRY_COOLDOWN_S", "1.0")))
                last_exc: Exception | None = None
                for attempt in range(1, retry_attempts + 1):
                    _wait_for_server_idle(worker_port)
                    session = ReplaySession(
                        row=row,
                        host=args.host,
                        port=worker_port,
                        config_path=args.config,
                        speed=args.speed,
                        client_timeout_s=args.client_timeout,
                        drain_after_transcription_s=args.drain_after_transcription_s,
                        heartbeat_block_duration_ms=args.heartbeat_block_duration_ms,
                        tool_mock_simulated_latency_min_ms=args.tool_mock_simulated_latency_min_ms,
                        tool_mock_simulated_latency_max_ms=args.tool_mock_simulated_latency_max_ms,
                        work_dir=work_dir,
                        log_dir=log_dir,
                        idx=idx,
                        history_toolcall_drop_rate=args.history_toolcall_drop_rate,
                        response_with_reference_client=response_with_reference_client,
                        tool_trigger_judge=tool_trigger_judge,
                    )
                    try:
                        result = asyncio.run(session.run())
                        break
                    except Exception as exc:
                        last_exc = exc
                        if attempt >= retry_attempts or not _is_transient_session_error(exc):
                            raise
                        print(
                            json.dumps(
                                {
                                    "index": idx,
                                    "status": "retrying",
                                    "attempt": attempt,
                                    "max_attempts": retry_attempts,
                                    "error": f"{type(exc).__name__}: {exc}",
                                    "worker_port": worker_port,
                                },
                                ensure_ascii=False,
                            ),
                            flush=True,
                        )
                        time.sleep(retry_cooldown_s * attempt)
                        _wait_for_server_idle(worker_port)
                else:
                    assert last_exc is not None
                    raise last_exc
                result["worker_port"] = worker_port

                # Immediately append to shared JSONL files so progress is saved
                # even if the process is killed mid-run.
                if result.get("trace_path"):
                    try:
                        trace_data = json.loads(Path(result["trace_path"]).read_text(encoding="utf-8"))
                        with write_lock:
                            with traces_jsonl_path.open("a", encoding="utf-8") as f:
                                f.write(json.dumps(trace_data, ensure_ascii=False) + "\n")
                    except Exception:
                        pass

                if result.get("thinking_sample_path") and Path(result["thinking_sample_path"]).exists():
                    _append_thinking_samples(Path(result["thinking_sample_path"]))

                if result.get("response_sample_path") and Path(result["response_sample_path"]).exists():
                    try:
                        sample_data = json.loads(Path(result["response_sample_path"]).read_text(encoding="utf-8"))
                        with write_lock:
                            with response_jsonl_path.open("a", encoding="utf-8") as f:
                                f.write(json.dumps(sample_data, ensure_ascii=False) + "\n")
                    except Exception:
                        pass

                # Append summary entry
                _append_jsonl(summary_path, result)
                print(json.dumps(result, ensure_ascii=False), flush=True)

                return result
            except Exception as exc:
                # On failure, record the error but don't save partial samples
                error_result = {
                    "index": idx,
                    "status": "failed",
                    "error": f"{type(exc).__name__}: {exc}",
                    "worker_port": worker_port,
                }
                _append_jsonl(summary_path, error_result)
                print(json.dumps(error_result, ensure_ascii=False), flush=True)
                return error_result

        def _worker_loop(worker_port: int) -> list[dict[str, Any]]:
            results: list[dict[str, Any]] = []
            for idx_row in port_to_rows[worker_port]:
                result = _run_one(idx_row, worker_port)
                results.append(result)
                cooldown_s = max(0.0, float(os.getenv("HEARTBEAT_REPLAY_WORKER_COOLDOWN_S", "0.5")))
                if cooldown_s:
                    time.sleep(cooldown_s)
            return results

        with ThreadPoolExecutor(max_workers=args.jobs) as executor:
            futures = [executor.submit(_worker_loop, port) for port in pool.ports]
            for future in as_completed(futures):
                for result in future.result():
                    pass  # Results are already appended in _run_one

    finally:
        pool.shutdown()

    print(f"[distill] Done. Output: {out_dir}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
