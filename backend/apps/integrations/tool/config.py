"""
Tool configuration model - Minimal version.

Only requires tool name, auto-derives module and class.
"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ToolConfig:
    """
    Minimal tool configuration.

    Example (tenant JSON):
    ```json
    {
      "TOOLS": [
        {"name": "example_mcp", "type": "mcp", "config": {"endpoint": "..."}},
        {"name": "faq_rag", "type": "rag", "config": {"client_type": "rag_search", "rag_url": "..."}}
      ]
    }
    ```

    Auto-derivation (based on client_type):
    - client_type="view_text_file" → module="apps.integrations.tool.view_text_file_tool", class="ViewTextFileTool"

    Type field:
    - "class" (default): Create tool from registered BaseTool subclass
    - "mcp": Register MCP server and discover tools dynamically
    - "rag" / "skill": Equivalent to "class", used for categorization

    client_type (from config):
    - Specifies which BaseTool subclass to use for instantiation.
    - Falls back to ``name`` when not provided, preserving backward compatibility.
    """
    name: str                              # Tool instance name (unique identifier)
    config: dict = field(default_factory=dict)  # Tool-specific configuration
    enabled: bool = True                   # Whether the tool is enabled
    type: str = "class"                   # Tool type: "class", "mcp", "rag", "skill"

    # Extracted from config or falls back to name
    client_type: str = field(init=False)   # Class lookup key (used to locate BaseTool subclass)

    # Auto-derived fields (based on client_type)
    module: str = field(init=False)        # Module path (auto-derived)
    class_name: str = field(init=False)    # Class name (auto-derived)

    def __post_init__(self):
        """Auto-derive client_type, module and class."""
        # client_type: extracted from config, falls back to name if not specified
        self.client_type = self.config.get('client_type', self.name)

        # MCP type does not need module and class name derivation
        if self.type == "mcp":
            self.module = ""
            self.class_name = ""
            return

        # snake_case to CamelCase conversion based on client_type
        # e.g., "skill_load" -> "SkillLoad"
        parts = self.client_type.split('_')
        camel_case = ''.join(part.capitalize() for part in parts)

        # Derive module path
        # e.g., "skill_load" -> "apps.integrations.tool.skill_load_tool"
        self.module = f"apps.integrations.tool.{self.client_type}_tool"

        # Derive class name
        # e.g., "skill_load" -> "SkillLoadTool"
        self.class_name = f"{camel_case}Tool"

    @classmethod
    def from_dict(cls, data: dict) -> 'ToolConfig':
        """Create a ToolConfig from a dictionary."""
        return cls(
            name=data['name'],
            config=data.get('config', {}),
            enabled=data.get('enabled', True),
            type=data.get('type', 'class')
        )
