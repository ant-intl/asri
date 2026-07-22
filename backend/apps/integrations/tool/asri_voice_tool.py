"""ASRI Voice business tools — Django BaseTool subclasses.

Migrated from ``voice/src/tools/asri_tools.py`` to unify tool definition
under Django's ``BaseTool`` pattern.  Each tool has ``requires_config = False``
so it is auto-registered as a zero-config instance for every tenant and
appears on the frontend Tool management page automatically.

Voice execution enhancements (cancel scope, ToolPolicy, idempotency) are
applied by Voice's ``ToolRegistry`` execution layer via the bridge in
``register_django_tools()``.  The ``tool_policy`` class attribute declared
here is read by the bridge and passed to Voice's ``register(policy=...)``.
"""
import datetime as _datetime
import hashlib
import json
import logging
import os
from typing import Any

import httpx

from apps.integrations.tool.base import BaseTool

logger = logging.getLogger(__name__)

EPOS_KNOWLEDGE_URL = os.environ.get(
    "EPOS_KNOWLEDGE_URL",
    "http://localhost:8001/api/search_knowledge",
)
EPOS_QUERY_URL = os.environ.get(
    "EPOS_QUERY_URL",
    "http://localhost:8002/api/query_status",
)


class GetCurrentTimeTool(BaseTool):
    """Get the current server local time."""

    name = "get_current_time"
    description = (
        "Get the current server local time. Use this when the user asks "
        "for the current time, date, day, or similar time information."
    )
    requires_config = False
    tool_policy = "read"

    parameters_schema = {
        "type": "object",
        "properties": {
            "timezone": {
                "type": "string",
                "description": (
                    "Optional timezone label requested by the user, "
                    "such as Asia/Shanghai or UTC."
                ),
            },
        },
    }

    async def execute(self, input_text: str, context: Any) -> str:
        args = json.loads(input_text) if input_text else {}
        timezone = args.get("timezone")
        now = _datetime.datetime.now().astimezone()
        return json.dumps(
            {
                "current_time": now.strftime("%Y-%m-%d %H:%M:%S"),
                "timezone": timezone or str(now.tzinfo),
            },
            ensure_ascii=False,
        )


class GetWeatherTool(BaseTool):
    """Get mock weather for a location."""

    name = "get_weather"
    description = (
        "Get mock weather for a location. Use this when the user asks about "
        "weather. The result is simulated and should be described as an "
        "estimate if needed."
    )
    requires_config = False
    tool_policy = "read"

    parameters_schema = {
        "type": "object",
        "properties": {
            "location": {
                "type": "string",
                "description": "City, region, or place name mentioned by the user.",
            },
        },
        "required": ["location"],
    }

    async def execute(self, input_text: str, context: Any) -> str:
        args = json.loads(input_text) if input_text else {}
        location = args.get("location", "")
        presets = [
            {"condition": "sunny", "temperature_c": 29, "humidity": "62%"},
            {"condition": "cloudy", "temperature_c": 26, "humidity": "71%"},
            {"condition": "light rain", "temperature_c": 24, "humidity": "86%"},
            {"condition": "clear", "temperature_c": 27, "humidity": "58%"},
        ]
        digest = hashlib.sha256(
            location.strip().lower().encode("utf-8")
        ).hexdigest()
        weather = presets[int(digest[:8], 16) % len(presets)]
        return json.dumps(
            {"location": location, **weather, "source": "mock"},
            ensure_ascii=False,
        )


class SearchEposKnowledgeTool(BaseTool):
    """Search EPOS/BlueTap business knowledge."""

    name = "search_epos_knowledge"
    description = (
        "Search the EPOS/BlueTap business knowledge base for product "
        "information, pricing, setup, activation, payments, settlement, "
        "troubleshooting, delivery, warranty, and returns. Always translate "
        "the user's question to English before passing it as the query "
        "parameter."
    )
    requires_config = False
    tool_policy = "read"

    parameters_schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "Search query in English. Translate non-English user "
                    "questions to English before searching."
                ),
            },
        },
        "required": ["query"],
    }

    async def execute(self, input_text: str, context: Any) -> str:
        args = json.loads(input_text) if input_text else {}
        query = args.get("query", "")
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    EPOS_KNOWLEDGE_URL,
                    json={"query": query},
                    timeout=10.0,
                )
                return json.dumps(resp.json(), ensure_ascii=False)
        except Exception as exc:
            return json.dumps(
                {"results": [], "error": str(exc)},
                ensure_ascii=False,
            )


class QueryEposOrderTool(BaseTool):
    """Query EPOS/BlueTap order, delivery, or activation status."""

    name = "query_epos_order"
    description = (
        "Query EPOS/BlueTap order, delivery, device inventory, or activation "
        "status. Use this when the user asks about an order, delivery, "
        "logistics, tracking, shipment, device activation, or provides a PI "
        "number. The current service supports lookup_by='pi_number'."
    )
    requires_config = False
    tool_policy = "read"

    parameters_schema = {
        "type": "object",
        "properties": {
            "lookup_by": {
                "type": "string",
                "enum": ["pi_number"],
                "description": (
                    "Lookup dimension. Use pi_number for EPOS/BlueTap PI numbers."
                ),
            },
            "value": {
                "type": "string",
                "description": "PI number value, such as 4431 or PI-2743.",
            },
            "return_fields": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Optional list of fields to return. Omit to return all "
                    "available fields."
                ),
            },
        },
        "required": ["lookup_by", "value"],
    }

    async def execute(self, input_text: str, context: Any) -> str:
        args = json.loads(input_text) if input_text else {}
        lookup_by = args.get("lookup_by", "")
        value = args.get("value", "")
        return_fields = args.get("return_fields")
        body: dict[str, Any] = {"lookup_by": lookup_by, "value": value}
        if return_fields:
            body["return_fields"] = return_fields
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    EPOS_QUERY_URL,
                    json=body,
                    timeout=10.0,
                )
                return json.dumps(resp.json(), ensure_ascii=False)
        except Exception as exc:
            return json.dumps(
                {"found": False, "records": [], "error": str(exc)},
                ensure_ascii=False,
            )
