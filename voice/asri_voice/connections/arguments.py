from dataclasses import dataclass, field


@dataclass
class SocketReceiverArguments:
    recv_host: str = field(
        default="localhost",
        metadata={"help": "The host IP address for the socket connection. Default is 'localhost'."},
    )
    recv_port: int = field(
        default=12345,
        metadata={"help": "The port number on which the socket server listens. Default is 12345."},
    )
    chunk_size: int = field(
        default=1024,
        metadata={"help": "The size of each data chunk in bytes. Default is 1024."},
    )


@dataclass
class SocketSenderArguments:
    send_host: str = field(
        default="localhost",
        metadata={"help": "The host IP address for the socket connection. Default is 'localhost'."},
    )
    send_port: int = field(
        default=12346,
        metadata={"help": "The port number on which the socket server listens. Default is 12346."},
    )


@dataclass
class WebSocketStreamerArguments:
    ws_host: str = field(
        default="127.0.0.1",
        metadata={"help": "The host IP address for the WebSocket server. Default is '127.0.0.1'."},
    )
    ws_port: int = field(
        default=8765,
        metadata={"help": "The port number for the WebSocket server. Default is 8765."},
    )
