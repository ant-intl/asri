import json
import logging
from typing import Any

import numpy as np


def next_power_of_2(x):
    return 1 if x == 0 else 2 ** (x - 1).bit_length()


def int2float(sound):
    """
    Taken from https://github.com/snakers4/silero-vad
    """

    abs_max = np.abs(sound).max()
    sound = sound.astype("float32")
    if abs_max > 0:
        sound *= 1 / 32768
    sound = sound.squeeze()  # depends on the use case
    return sound


class _PayloadEncoder(json.JSONEncoder):
    """JSON encoder that converts unknown objects to strings."""

    def default(self, obj: Any) -> Any:
        try:
            return super().default(obj)
        except TypeError:
            return str(obj)


def log_llm_request(
    logger: logging.Logger,
    label: str,
    model: str,
    messages: list[dict],
    **kwargs: Any,
) -> None:
    """Log a complete LLM request payload without API keys or other secrets.

    Message content and tool definitions are logged in full so prompts can be
    inspected during debugging. The log level is INFO so it is visible without
    enabling verbose debug output.
    """
    payload = {
        "model": model,
        "messages": messages,
    }
    payload.update({k: v for k, v in kwargs.items() if k != "api_key"})
    logger.info(
        "[%s] LLM request payload: %s",
        label,
        json.dumps(payload, ensure_ascii=False, cls=_PayloadEncoder),
    )
