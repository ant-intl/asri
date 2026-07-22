import inspect
import threading
from pathlib import Path

import yaml

from handlers.heartbeat_interaction.arguments import HeartbeatInteractionArguments
from handlers.heartbeat_interaction.handler import HeartbeatInteractionHandler
from handlers.heartbeat_interaction.streaming_asr_handler import (
    StreamingASRHeartbeatHandler,
)


CONFIG_DIR = Path(__file__).resolve().parents[1] / "configs"


def test_heartbeat_is_enabled_with_eight_concurrent_requests_in_yaml_defaults():
    for filename in ("asri-voice.yaml", "asri-voice.example.yaml"):
        config = yaml.safe_load((CONFIG_DIR / filename).read_text(encoding="utf-8"))

        assert config["enable_heartbeat_interaction"] is True
        assert config["heartbeat_interaction_config"]["max_concurrent"] == 8


def test_heartbeat_code_defaults_use_eight_concurrent_requests():
    arguments = HeartbeatInteractionArguments()
    assert arguments.heartbeat_interaction_max_concurrent == 8

    omni_default = inspect.signature(HeartbeatInteractionHandler.setup).parameters[
        "max_concurrent"
    ].default
    streaming_default = inspect.signature(
        StreamingASRHeartbeatHandler.setup
    ).parameters["max_concurrent"].default

    assert omni_default == 8
    assert streaming_default == 8


def _saturated_handler(handler_class):
    handler = handler_class.__new__(handler_class)
    handler._predict_semaphore = threading.Semaphore(0)
    handler._inflight_lock = threading.Lock()
    current = threading.current_thread()
    handler._inflight = {current}
    return handler, current


def test_streaming_heartbeat_drops_block_when_concurrency_is_saturated():
    handler, current = _saturated_handler(StreamingASRHeartbeatHandler)
    handler._inflight_blocks = {current: 3}

    model_called = False

    def fail_if_called(*_args, **_kwargs):
        nonlocal model_called
        model_called = True

    handler._call_predict_model = fail_if_called
    handler._process_predict_result = fail_if_called

    handler._predict_worker([], "hello", 3, 0, 0, 0)

    assert model_called is False
    assert current not in handler._inflight
    assert current not in handler._inflight_blocks


def test_omni_heartbeat_drops_block_when_concurrency_is_saturated():
    handler, current = _saturated_handler(HeartbeatInteractionHandler)

    model_called = False

    def fail_if_called(*_args, **_kwargs):
        nonlocal model_called
        model_called = True

    handler._invoke_predict_model = fail_if_called
    handler._process_predict_result = fail_if_called

    handler._predict_worker({}, [], [], 3, 0, 0, 0)

    assert model_called is False
    assert current not in handler._inflight
