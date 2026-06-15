"""
Execute Shell Command Tool — run a shell command in the tenant's skills directory.

Path is validated to stay under the current tenant's skills directory to prevent
arbitrary execution.
"""
import asyncio
import logging
import os

from apps.integrations.tool.base import BaseTool

logger = logging.getLogger(__name__)

# Commands that are never allowed
FORBIDDEN_COMMANDS = [
    "rm -rf", "rm -r /", "mkfs", "dd if=", ">:",
    "sudo", "su ", "chmod 777", "chown",
    "wget ", "curl -o", "curl --output",
    ":(){ :|:& };:",  # fork bomb
]


class ExecuteShellCommandTool(BaseTool):
    """Execute shell commands in the current tenant's skills directory (for running skill scripts)."""

    name = "execute_shell_command"
    description = (
        "在当前租户的 skills 目录下执行 shell 命令。"
        "用于运行 skill 中的脚本（如 python script/convert.py --value 26.2 --from miles --to kilometers）。"
        "命令的工作目录会被限定在当前租户的 skills/<skill-name>/ 下。"
        "执行 shell 命令会触发用户确认。"
    )
    requires_config = False

    parameters_schema = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "要执行的 shell 命令，例如 'python script/convert.py --value 26.2 --from miles --to kilometers'。",
            },
            "work_dir": {
                "type": "string",
                "description": "工作目录（相对于当前租户的 skills 目录），例如 'unit-converter'。不指定则使用 skills 根目录。",
            },
        },
        "required": ["command"],
    }

    def __init__(self, tenant_id: str = None, config: dict = None):
        super().__init__(tenant_id, config)

    async def execute(self, input_text: str, context) -> str:
        import json

        args = json.loads(input_text)
        command = args.get("command", "").strip()
        work_dir = args.get("work_dir", "").strip()

        if not command:
            return "Error: 'command' is required."

        # Security checks
        error = self._validate_command(command)
        if error:
            return error

        # Resolve working directory (tenant-scoped)
        from apps.utils.skill_paths import get_tenant_skills_dir
        tenant_id = getattr(context, 'tenant_id', None) or 'example'
        skills_base = get_tenant_skills_dir(tenant_id)
        cwd = skills_base
        if work_dir:
            clean = work_dir.lstrip("/")
            candidate = os.path.normpath(os.path.join(skills_base, clean))
            if not candidate.startswith(skills_base):
                return "Error: work_dir must be under tenant skills directory."
            if not os.path.isdir(candidate):
                return f"Error: work_dir '{work_dir}' does not exist."
            cwd = candidate

        # Execute the command with timeout
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=30
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return f"Error: command timed out after 30 seconds.\nCommand: {command}"

            stdout_text = ""
            output_parts = []
            if stdout:
                stdout_text = stdout.decode("utf-8", errors="replace").strip()
                output_parts.append(stdout_text)
            if stderr:
                output_parts.append(
                    f"[stderr]\n{stderr.decode('utf-8', errors='replace').strip()}"
                )

            result = "\n".join(output_parts) if output_parts else "(no output)"
            logger.info(
                "Shell command exited with code %d (work_dir=%s): %s",
                proc.returncode,
                cwd,
                command,
            )

            # --- Card auto-detection ---
            # If stdout contains JSON with __asri_card__ marker, route to CardDataFrame
            if stdout_text:
                try:
                    data = json.loads(stdout_text)
                    if isinstance(data, dict) and data.get("__asri_card__") is True:
                        card_data = {k: v for k, v in data.items() if k != "__asri_card__"}
                        self.requires_llm = False
                        return json.dumps({
                            "_type": "card_result",
                            "card_data": card_data,
                            "status": "generated",
                        })
                except (json.JSONDecodeError, ValueError):
                    pass

            self.requires_llm = True
            return (
                f"Exit code: {proc.returncode}\n"
                f"Command: {command}\n"
                f"Work dir: {cwd}\n---\n{result}"
            )
        except FileNotFoundError:
            return f"Error: command not found: {command}"
        except Exception as e:
            logger.error("Shell command failed: %s", e, exc_info=True)
            return f"Error: command execution failed: {e}"

    def _validate_command(self, command: str) -> str | None:
        """Validate command safety. Returns error message or None."""
        cmd_lower = command.lower()

        for forbidden in FORBIDDEN_COMMANDS:
            if forbidden in cmd_lower:
                return f"Error: command contains forbidden pattern '{forbidden}'."

        return None
