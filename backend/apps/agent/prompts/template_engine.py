"""
Jinja2 Template Engine for Prompt rendering.

Provides a safe sandboxed environment for rendering Jinja2 templates
with predefined helper functions.
"""
import json
from datetime import datetime
from typing import Any

from jinja2.sandbox import SandboxedEnvironment


# ============================================================================
# Predefined Helper Functions (available in templates)
# ============================================================================

def now(format_str: str = "%Y-%m-%d %H:%M:%S") -> str:
    """Return current datetime string.

    Available in all prompt templates via ``{{ now() }}``.
    Supports strftime format, e.g. ``{{ now('%Y-%m-%d %H:%M') }}``
    or ``{{ now('%Y年%m月%d日 %H:%M') }}``.

    Args:
        format_str: strftime format string. Defaults to ``%%Y-%%m-%%d %%H:%%M:%%S``.

    Returns:
        Formatted current datetime string.
    """
    return datetime.now().strftime(format_str)


def to_json(obj: Any, indent: int | None = None) -> str:
    """Serialize an object to JSON string with sorted keys."""
    return json.dumps(obj, ensure_ascii=False, indent=indent, sort_keys=True)


def format_history(history: list[dict], role_map: dict | None = None) -> str:
    """Format conversation history as text.

    Args:
        history: List of message dicts.
        role_map: Role mapping, e.g. {"user": "User", "assistant": "Assistant"}.
    """
    if not history:
        return ""
    default_map = {"user": "User", "assistant": "Assistant", "tool": "Tool"}
    role_map = role_map or default_map
    lines = []
    for msg in history:
        role = role_map.get(msg.get('role', ''), msg.get('role', ''))
        content = msg.get('content', '')
        lines.append(f"{role}: {content}")
    return "\n".join(lines)


def format_tools(tools: list[dict]) -> str:
    """Format tool list as text with parameter schemas.

    Supports two formats:
    1. OpenAI format: ``{"type": "function", "function": {"name": ..., "description": ..., "parameters": ...}}``
    2. Flat format: ``{"name": ..., "description": ..., "parameters": ...}``

    Output includes parameter names, types, required/optional markers,
    and descriptions so the LLM can construct valid tool calls.
    """
    if not tools:
        return "No tools available."
    lines = []
    for t in tools:
        # Try OpenAI format first (type/function nesting)
        func = t.get('function') if t.get('type') == 'function' else None
        if func:
            name = func.get('name', '')
            desc = func.get('description', '')
            params = func.get('parameters', {})
        else:
            # Fallback to flat format
            name = t.get('name', '')
            desc = t.get('description', '')
            params = t.get('parameters', {})

        lines.append(f"- {name}: {desc}")

        # Append parameter details
        properties = params.get('properties') if isinstance(params, dict) else None
        if properties:
            required_params = set(params.get('required', []) or [])
            lines.append("  Parameters:")
            for param_name, param_info in properties.items():
                param_type = param_info.get('type', 'any')
                param_desc = param_info.get('description', '')
                is_required = param_name in required_params
                required_tag = "required" if is_required else "optional"
                if param_desc:
                    lines.append(f"    - {param_name} ({param_type}, {required_tag}): {param_desc}")
                else:
                    lines.append(f"    - {param_name} ({param_type}, {required_tag})")

    return "\n".join(lines)


def format_skills(skills: list[dict], start: int = 1) -> str:
    """Format filesystem skill list as text with path info.

    Skills are rendered with their name, description, and SKILL.md path.
    The LLM MUST use ``view_text_file`` to read SKILL.md before executing
    any skill script — NEVER guess commands or parameters.

    Args:
        skills: List of skill dicts with 'name', 'description',
            and 'skill_dir' (filesystem path to skill directory).
        start: Starting number for enumeration.
    """
    if not skills:
        return ""
    lines = []
    fs_skills = [s for s in skills if s.get('skill_dir')]

    if fs_skills:
        lines.append("Available filesystem skills:")
        for s in fs_skills:
            name = s.get('name', '')
            desc = s.get('description', '')
            skill_dir = s.get('skill_dir', '')
            lines.append(f"- {name}: {desc}")
            lines.append(f"  SKILL.md at: {skill_dir}/SKILL.md")
        lines.append("")
        lines.append(
            "CRITICAL: Before executing ANY filesystem skill script, you MUST first use "
            "`view_text_file` to read its SKILL.md file to understand the correct parameters "
            "and command format. NEVER guess the command or script path — always read SKILL.md first."
        )
        lines.append(
            "After reading SKILL.md, use `execute_shell_command` to run skill scripts "
            "according to the instructions."
        )

    return "\n".join(lines)



def first_item(items: list) -> Any:
    """Return the first element of a list."""
    return items[0] if items else None


def join_lines(items: list) -> str:
    """Join list elements with newlines."""
    return "\n".join(str(i) for i in items) if items else ""


def history_to_interleaved(history: list[dict]) ->list[dict]:
    """Convert history messages to interleaved format.

    Args:
        history: Original history message list.

    Returns:
        tuple: (prompt_history, last_query)
            - prompt_history: History excluding the last message (converted format)
            - last_query: Content of the last message (empty string if role is 'tool')
    """
    if not history:
        return []

    prompt_history = []

    # Convert history except the last message
    for msg in history[:-1]:
        role = msg.get('role', '')
        content = msg.get('content', '')
        if role == 'tool':
            prompt_history.append({
                'role': 'tool',
                'content': f'{content}'
            })
        elif role == 'assistant':
            prompt_history.append({'role': 'assistant', 'content': content})
        else:
            prompt_history.append({'role': role or 'user', 'content': content})

    return prompt_history


def build_user_content(tools: list | None, history: list | None, query: str, tool_ans: str | list | None) -> str:
    """Build user message content for interleaved mode.

    Internally calls history_to_interleaved() to handle history conversion,
    providing a clean interface for Jinja2 templates.

    Args:
        tools: Tool schema list.
        history: Original history message list.
        query: User query.
        tool_ans: Tool execution result (str or list).

    Returns:
        JSON string.
    """
    # Handle history conversion internally
    prompt_history = history_to_interleaved(history or [])

    # Use passed query if no query extracted from history

    last_message = {}
    if history and len(history) >= 1:
        last_message = history[-1]
    if last_message and last_message.get('role') == "tool":
        query = ""

    # Normalize tool_ans to list
    if tool_ans is None:
        tool_ans_list = []
    elif isinstance(tool_ans, str):
        tool_ans_list = [tool_ans] if tool_ans else []
    elif isinstance(tool_ans, (list, tuple)):
        tool_ans_list = list(tool_ans)
    else:
        tool_ans_list = []

    content = {
        'tools': tools or [],
        'history': prompt_history,
        'user': query,
        'tool_ans': tool_ans_list,
    }
    return json.dumps(content, ensure_ascii=False, sort_keys=True)
    # return json.dumps(content, ensure_ascii=False, indent=2)


# ============================================================================
# Template Rendering Engine
# ============================================================================

class PromptTemplateEngine:
    """Jinja2 template rendering engine for prompts."""

    _env = SandboxedEnvironment(
        autoescape=False,
    )

    # Register global functions
    _env.globals.update({
        'to_json': to_json,
        'format_history': format_history,
        'format_tools': format_tools,
        'format_skills': format_skills,
        'first_item': first_item,
        'join_lines': join_lines,
        'history_to_interleaved': history_to_interleaved,
        'build_user_content': build_user_content,
        'now': now,
    })

    # Register filters (accessible via {{ var | filter }} syntax)
    _env.filters.update({
        'tojson': to_json,  # {{ obj | tojson }}
        'format_tools': format_tools,  # {{ tool_schemas | format_tools }}
        'format_skills': format_skills,  # {{ skills | format_skills }}
    })

    # Template cache
    _template_cache: dict[str, Any] = {}

    @classmethod
    def render(cls, template_str: str, **kwargs) -> str:
        """Render a Jinja2 template with the given variables.

        Args:
            template_str: The Jinja2 template string.
            **kwargs: Variables to pass to the template.

        Returns:
            Rendered template string.
        """
        if not template_str:
            return ""

        # Check cache first
        template = cls._template_cache.get(template_str)
        if template is None:
            template = cls._env.from_string(template_str)
            cls._template_cache[template_str] = template

        return template.render(**kwargs)

    @classmethod
    def clear_cache(cls) -> None:
        """Clear the template cache."""
        cls._template_cache.clear()
