"""
View Text File Tool — read text file content by path.

Path is validated against a base directory to prevent traversal attacks.
"""
import os
import logging

from apps.integrations.tool.base import BaseTool

logger = logging.getLogger(__name__)

SKILLS_BASE_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "data", "skills")
)


class ViewTextFileTool(BaseTool):
    """Read the content of a text file. The file path must be under the data/skills/ directory."""

    name = "view_text_file"
    description = "读取文本文件的内容。用于查看 SKILL.md、references 等文件。"
    requires_config = False

    parameters_schema = {
        "type": "object",
        "properties": {
            "filepath": {
                "type": "string",
                "description": (
                    "文件路径，相对于 data/skills/ 目录。"
                    "例如：'unit-converter/SKILL.md' 或 'unit-converter/references/conversion-formulas.md'"
                ),
            },
            "start_line": {
                "type": "integer",
                "description": "起始行号（从1开始，可选）",
            },
            "end_line": {
                "type": "integer",
                "description": "结束行号（包含，可选）",
            },
        },
        "required": ["filepath"],
    }

    def __init__(self, tenant_id: str = None, config: dict = None):
        super().__init__(tenant_id, config)

    async def execute(self, input_text: str, context) -> str:
        import json

        args = json.loads(input_text)
        filepath = args.get("filepath", "")
        start_line = args.get("start_line")
        end_line = args.get("end_line")

        if not filepath:
            return "Error: 'filepath' is required."

        resolved, error = self._resolve_path(filepath)
        if error:
            return error

        try:
            with open(resolved, "r", encoding="utf-8") as fh:
                lines = fh.readlines()
        except FileNotFoundError:
            return f"Error: file '{filepath}' not found."
        except (OSError, UnicodeDecodeError) as e:
            return f"Error: failed to read file: {e}"

        total = len(lines)
        if start_line is not None or end_line is not None:
            s = (start_line or 1) - 1
            e = end_line or total
            lines = lines[s:e]

        content = "".join(lines)
        info = f"File: {filepath} ({len(lines)} lines shown / {total} total)"

        if content:
            return f"{info}\n---\n{content}"
        return info

    def _resolve_path(self, filepath: str) -> tuple[str, str | None]:
        """Resolve *filepath* and validate it stays under SKILLS_BASE_DIR.

        Returns ``(resolved_path, None)`` on success, or
        ``(None, error_message)`` on failure.
        """
        # Strip leading slashes to prevent absolute path access
        clean = filepath.lstrip("/")
        candidate = os.path.normpath(os.path.join(SKILLS_BASE_DIR, clean))

        if not candidate.startswith(SKILLS_BASE_DIR):
            return None, "Error: path must be under data/skills/ directory."

        if not os.path.exists(candidate):
            return None, f"Error: file '{filepath}' not found."

        if not os.path.isfile(candidate):
            return None, f"Error: '{filepath}' is not a file."

        return candidate, None
