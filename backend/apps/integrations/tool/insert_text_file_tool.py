"""
Insert Text File Tool — insert content at a specific line number, or
replace a string match in an existing text file.

Path is validated against the current tenant's skills directory to prevent
path traversal attacks.
"""
import os
import logging

from apps.integrations.tool.base import BaseTool

logger = logging.getLogger(__name__)


class InsertTextFileTool(BaseTool):
    """Edit a text file: insert content after a specified line number, or replace a string."""

    name = "insert_text_file"
    description = (
        "编辑文本文件。支持两种模式：\n"
        "1. 行号插入：在指定 line_number 后插入 content\n"
        "2. 字符串替换：将 old_string 替换为 new_string\n"
        "文件路径必须位于当前租户的 skills 目录下。"
    )
    requires_config = False

    parameters_schema = {
        "type": "object",
        "properties": {
            "filepath": {
                "type": "string",
                "description": (
                    "文件路径，相对于当前租户的 skills 目录。"
                    "例如：'unit-converter/SKILL.md'"
                ),
            },
            "line_number": {
                "type": "integer",
                "description": "在此行号后插入内容（从1开始）。与 old_string 二选一。",
            },
            "content": {
                "type": "string",
                "description": "要插入或替换的新内容。",
            },
            "old_string": {
                "type": "string",
                "description": "要替换的旧字符串。与 line_number 二选一。",
            },
            "new_string": {
                "type": "string",
                "description": "替换后的新字符串（仅替换模式）。",
            },
        },
        "oneOf": [
            {"required": ["filepath", "line_number", "content"]},
            {"required": ["filepath", "old_string", "new_string"]},
        ],
    }

    def __init__(self, tenant_id: str = None, config: dict = None):
        super().__init__(tenant_id, config)

    async def execute(self, input_text: str, context) -> str:
        import json

        args = json.loads(input_text)
        filepath = args.get("filepath", "")
        line_number = args.get("line_number")
        content = args.get("content", "")
        old_string = args.get("old_string")
        new_string = args.get("new_string")

        if not filepath:
            return "Error: 'filepath' is required."

        resolved, error = self._resolve_path(filepath, context)
        if error:
            return error

        if not os.path.isfile(resolved):
            return f"Error: file '{filepath}' not found."

        try:
            with open(resolved, "r", encoding="utf-8") as fh:
                original = fh.read()
        except (OSError, UnicodeDecodeError) as e:
            return f"Error: failed to read file: {e}"

        if line_number is not None:
            # Line-number mode: insert after line
            lines = original.splitlines(keepends=True)
            if line_number < 1 or line_number > len(lines):
                return (
                    f"Error: line_number {line_number} out of range "
                    f"(file has {len(lines)} lines)."
                )
            lines.insert(line_number, content + "\n")
            new_content = "".join(lines)
            mode_desc = f"line {line_number}"
        elif old_string is not None:
            # String-replacement mode
            if old_string not in original:
                return f"Error: old_string not found in '{filepath}'."
            new_content = original.replace(old_string, new_string, 1)
            mode_desc = f"replace '{old_string}' → '{new_string}'"
        else:
            return "Error: provide either 'line_number' or 'old_string'."

        try:
            with open(resolved, "w", encoding="utf-8") as fh:
                fh.write(new_content)
        except OSError as e:
            return f"Error: failed to write file: {e}"

        logger.info("Edited '%s' (%s)", resolved, mode_desc)
        return f"Successfully edited '{filepath}' ({mode_desc})."

    def _resolve_path(self, filepath: str, context) -> tuple[str, str | None]:
        """Resolve *filepath* and validate it stays under the tenant's skills directory."""
        from apps.utils.skill_paths import get_tenant_skills_dir
        tenant_id = getattr(context, 'tenant_id', None) or 'example'
        base = get_tenant_skills_dir(tenant_id)
        clean = filepath.lstrip("/")
        candidate = os.path.normpath(os.path.join(base, clean))
        if not candidate.startswith(base):
            return None, "Error: path must be under tenant skills directory."
        return candidate, None
