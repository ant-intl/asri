"""ServerPool — manage a pool of realtime server subprocesses.

Each worker in the replay runner gets its own dedicated server listening
on its own port.  Workers never share a port, so there is no
``ws_lock`` contention.  The pool starts all servers, waits for them to
become healthy, and shuts them down cleanly on exit.

Usage::

    with ServerPool(config_path=..., pool_size=4) as pool:
        # pool.ports == [8765, 8766, 8767, 8768]
        ...
"""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]


class ServerPool:
    """Start and supervise a pool of realtime servers.

    Parameters
    ----------
    config_path:
        Path to the server YAML config.
    pool_size:
        Number of servers to start (one per worker).
    port_start:
        First server port.  Subsequent servers use ``port_start + 1``,
        ``port_start + 2``, etc.
    host:
        Host to bind servers to and to health-check against.
    python_bin:
        Python interpreter to use for starting the server subprocesses.
    startup_timeout_s:
        Maximum seconds to wait for each server to become healthy.
    log_dir:
        Directory to write per-server log files.
    env_overrides:
        Optional dict of environment variables to inject into the server
        subprocesses.
    """

    def __init__(
        self,
        *,
        config_path: str,
        pool_size: int,
        port_start: int = 8765,
        host: str = "127.0.0.1",
        python_bin: str = sys.executable,
        startup_timeout_s: float = 120.0,
        log_dir: Path | None = None,
        env_overrides: dict[str, str] | None = None,
    ) -> None:
        self.config_path = config_path
        self.pool_size = max(1, pool_size)
        self.port_start = port_start
        self.host = host
        self.python_bin = python_bin
        self.startup_timeout_s = startup_timeout_s
        self.log_dir = log_dir or Path("/tmp/heartbeat_replay_logs")
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.env_overrides = env_overrides or {}
        self._servers: list[dict[str, Any]] = []
        self._started = False

    @property
    def ports(self) -> list[int]:
        """Return the list of ports the pool manages."""
        return [self.port_start + i for i in range(self.pool_size)]

    def start(self) -> None:
        """Start all servers and wait for them to become healthy.

        Raises
        ------
        RuntimeError
            If a server exits early or fails to become healthy within
            ``startup_timeout_s`` seconds.
        """
        occupied_ports = [port for port in self.ports if self._health_check(port)]
        if occupied_ports:
            raise RuntimeError(
                "replay server port(s) already in use before ServerPool startup: "
                f"{occupied_ports}. Stop stale replay server processes or choose a "
                "different --port-start; refusing to reuse an existing listener."
            )

        for offset in range(self.pool_size):
            port = self.port_start + offset
            log_path = self.log_dir / f"server_{port}.log"
            env = dict(os.environ)
            env.update(self.env_overrides)
            env["PYTHONPATH"] = str(REPO_ROOT / "src")
            no_proxy_values = [
                v.strip()
                for v in (env.get("no_proxy") or env.get("NO_PROXY") or "").split(",")
                if v.strip()
            ]
            for v in ("127.0.0.1", "localhost", self.host):
                if v and v not in no_proxy_values:
                    no_proxy_values.append(v)
            env["no_proxy"] = ",".join(no_proxy_values)
            env["NO_PROXY"] = env["no_proxy"]

            cmd = [
                self.python_bin,
                str(REPO_ROOT / "src/main.py"),
                "--config",
                self.config_path,
                "--ws_port",
                str(port),
            ]
            with log_path.open("w", encoding="utf-8") as log_file:
                proc = subprocess.Popen(
                    cmd,
                    cwd=str(REPO_ROOT),
                    env=env,
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    # Put the server in its own process group so we can
                    # clean it up without taking down the parent.
                    start_new_session=True,
                )
            self._servers.append(
                {
                    "port": port,
                    "proc": proc,
                    "log_path": log_path,
                    "ready": False,
                }
            )

        deadline = time.monotonic() + self.startup_timeout_s
        for entry in self._servers:
            port = entry["port"]
            proc = entry["proc"]
            log_path = entry["log_path"]
            while True:
                if proc.poll() is not None:
                    tail = log_path.read_text(encoding="utf-8", errors="replace")[-2000:]
                    raise RuntimeError(
                        f"server on port {port} exited early (code {proc.returncode}).\n"
                        f"Log tail:\n{tail}"
                    )
                if self._health_check(port):
                    entry["ready"] = True
                    break
                if time.monotonic() > deadline:
                    tail = log_path.read_text(encoding="utf-8", errors="replace")[-2000:]
                    raise RuntimeError(
                        f"server on port {port} did not become healthy within "
                        f"{self.startup_timeout_s:.0f}s.\nLog tail:\n{tail}"
                    )
                time.sleep(1.0)

    def _health_check(self, port: int) -> bool:
        """Check if a server is accepting TCP connections on ``port``."""
        try:
            with socket.create_connection((self.host, port), timeout=2.0):
                pass
            return True
        except OSError:
            return False

    def shutdown(self) -> None:
        """Shut down all servers in the pool."""
        for entry in self._servers:
            proc = entry["proc"]
            if proc.poll() is not None:
                continue
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except ProcessLookupError:
                pass
            except OSError:
                # Fallback: just terminate the process directly.
                proc.terminate()
        deadline = time.monotonic() + 10.0
        for entry in self._servers:
            proc = entry["proc"]
            if proc.poll() is not None:
                continue
            try:
                proc.wait(timeout=max(0.1, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except OSError:
                    proc.kill()
                proc.wait(timeout=5.0)
        self._servers.clear()

    def __enter__(self) -> "ServerPool":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.shutdown()
