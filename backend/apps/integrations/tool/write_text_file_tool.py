"""
Write Text File Tool — create or overwrite a text file.

Path is validated against a base directory to prevent traversal attacks.
"""
import os
import logging

from apps.integrations.tool.base import BaseTool

logger = logging.getLogger(__name__)

SKILLS_BASE_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "data", "skills")
)


class WriteTextFileTool(BaseTool):
    """Write/overwrite a text file. The file path must be under the data/skills/ directory."""

    name = "write_text_file"
    description = "写入或覆盖一个文本文件。用于创建或更新 SKILL.md、references 等文件。"
    requires_config = False

    parameters_schema = {
        "type": "object",
        "properties": {
            "filepath": {
                "type": "string",
                "description": (
                    "文件路径，相对于 data/skills/ 目录。"
                    "例如：'unit-converter/references/notes.md'"
                ),
            },
            "content": {
                "type": "string",
                "description": "要写入的文件内容（UTF-8 编码）。",
            },
        },
        "required": ["filepath", "content"],
    }

    def __init__(self, tenant_id: str = None, config: dict = None):
        super().__init__(tenant_id, config)

    async def execute(self, input_text: str, context) -> str:
        import json

        args = json.loads(input_text)
        filepath = args.get("filepath", "")
        content = args.get("content", "")

        if not filepath:
            return "Error: 'filepath' is required."

        resolved, error = self._resolve_path(filepath)
        if error:
            return error

        # Ensure parent directory exists
        parent = os.path.dirname(resolved)
        try:
            os.makedirs(parent, exist_ok=True)
        except OSError as e:
            return f"Error: failed to create directory: {e}"

        try:
            with open(resolved, "w", encoding="utf-8") as fh:
                fh.write(content)
        except OSError as e:
            return f"Error: failed to write file: {e}"

        logger.info("Wrote %d bytes to '%s'", len(content), resolved)
        return f"Successfully wrote {len(content)} bytes to '{filepath}'."

    def _resolve_path(self, filepath: str) -> tuple[str, str | None]:
        """Resolve *filepath* and validate it stays under SKILLS_BASE_DIR."""
        clean = filepath.lstrip("/")
        candidate = os.path.normpath(os.path.join(SKILLS_BASE_DIR, clean))

        if not candidate.startswith(SKILLS_BASE_DIR):
            return None, "Error: path must be under data/skills/ directory."

        return candidate, None
