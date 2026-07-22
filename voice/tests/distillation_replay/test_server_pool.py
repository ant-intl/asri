from __future__ import annotations

import socket

import pytest

from client.replay.server_pool import ServerPool


def test_server_pool_refuses_preoccupied_port(tmp_path) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        port = sock.getsockname()[1]

        pool = ServerPool(
            config_path=str(tmp_path / "missing.yaml"),
            pool_size=1,
            port_start=port,
            host="127.0.0.1",
            startup_timeout_s=0.1,
            log_dir=tmp_path,
        )

        with pytest.raises(RuntimeError, match="already in use"):
            pool.start()
