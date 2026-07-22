"""Demo server-side tools for the agent loop.

Usage:
    uv run python src/main.py --tools_module tools.demo_tools ...
"""

import datetime


def get_weather(city: str) -> str:
    """Get the current weather for a city."""
    weathers = ["Sunny, 25°C", "Cloudy, 18°C", "Rainy, 15°C", "Clear, 22°C"]
    idx = hash(city) % len(weathers)
    return f"{weathers[idx]} in {city}"


def get_current_time() -> str:
    """Get the current date and time."""
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def register_tools(registry):
    """Register demo tools with the given ToolRegistry."""
    registry.register(
        "get_weather",
        get_weather,
        description="Get the current weather for a city.",
        parameters={
            "type": "object",
            "properties": {
                "city": {
                    "type": "string",
                    "description": "City name, e.g. 'Beijing', 'Shanghai'",
                },
            },
            "required": ["city"],
        },
    )
    registry.register(
        "get_current_time",
        get_current_time,
        description="Get the current date and time.",
        parameters={"type": "object", "properties": {}},
    )