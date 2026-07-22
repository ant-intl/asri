"""Code-defined prompt template registry for HeartBeat Interaction."""

from copy import deepcopy

from handlers.heartbeat_interaction.prompt_templates import response_heartbeat_context_v0
from handlers.heartbeat_interaction.prompt_templates import thinking_asri_v0
from handlers.heartbeat_interaction.prompt_templates import thinking_asri_generic_v0
from handlers.heartbeat_interaction.prompt_templates import thinking_asri_generic_chain_v1
from handlers.heartbeat_interaction.prompt_templates import thinking_asri_generic_interrupt_gate_v0
from handlers.heartbeat_interaction.prompt_templates.response_heartbeat_context_v0 import (
    RESPONSE_HEARTBEAT_CONTEXT_V0_PROMPT,
)
from handlers.heartbeat_interaction.prompt_templates.thinking_asri_generic_v0 import (
    THINKING_ASRI_GENERIC_V0_PROMPT,
)
from handlers.heartbeat_interaction.prompt_templates.thinking_asri_generic_chain_v1 import (
    THINKING_ASRI_GENERIC_CHAIN_V1_PROMPT,
)
from handlers.heartbeat_interaction.prompt_templates.thinking_asri_generic_interrupt_gate_v0 import (
    THINKING_ASRI_GENERIC_INTERRUPT_GATE_V0_PROMPT,
)
from handlers.heartbeat_interaction.prompt_templates.thinking_asri_v0 import (
    THINKING_ASRI_V0_PROMPT,
)


THINKING_PROMPT_MAPPINGS = {
    "asri-v0": THINKING_ASRI_V0_PROMPT,
    "asri-generic-v0": THINKING_ASRI_GENERIC_V0_PROMPT,
    "asri-generic-chain-v1": THINKING_ASRI_GENERIC_CHAIN_V1_PROMPT,
    "asri-generic-interrupt-gate-v0": THINKING_ASRI_GENERIC_INTERRUPT_GATE_V0_PROMPT,
}

RESPONSE_PROMPT_MAPPINGS = {
    "heartbeat-response-v0": RESPONSE_HEARTBEAT_CONTEXT_V0_PROMPT,
}

THINKING_PROMPT_DEFINITIONS = {
    "asri-v0": thinking_asri_v0,
    "asri-generic-v0": thinking_asri_generic_v0,
    "asri-generic-chain-v1": thinking_asri_generic_chain_v1,
    "asri-generic-interrupt-gate-v0": thinking_asri_generic_interrupt_gate_v0,
}

RESPONSE_PROMPT_DEFINITIONS = {
    "heartbeat-response-v0": response_heartbeat_context_v0,
}


def get_thinking_prompt_mapping(version: str) -> dict | None:
    template = THINKING_PROMPT_MAPPINGS.get(version)
    if template is None:
        return None
    return deepcopy(template)


def get_response_prompt_mapping(version: str) -> dict | None:
    template = RESPONSE_PROMPT_MAPPINGS.get(version)
    if template is None:
        return None
    return deepcopy(template)


def get_thinking_prompt_definition(version: str):
    return THINKING_PROMPT_DEFINITIONS.get(version)


def get_response_prompt_definition(version: str):
    return RESPONSE_PROMPT_DEFINITIONS.get(version)
