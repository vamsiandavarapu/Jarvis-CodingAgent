import subprocess
from langchain_core.tools import tool
from app.config import WORKSPACE, COMMAND_TIMEOUT
from app.tools.approval import request_approval


@tool
def run_cmd(command: str) -> str:
    """Run a developer-approved command from the configured workspace."""
    if not command or not command.strip():
        return "No command provided."

    if not request_approval(f"run command in '{WORKSPACE}':\n{command}"):
        return "Command execution rejected by user."

    try:
        result = subprocess.run(
            command,
            cwd=WORKSPACE,
            shell=True,
            capture_output=True,
            text=True,
            timeout=COMMAND_TIMEOUT,
            errors="replace"
        )
        stdout = result.stdout.strip()
        stderr = result.stderr.strip()
        output = "\n".join(part for part in [stdout, stderr] if part)
        if not output:
            output = "(no output)"
        return f"Exit code: {result.returncode}\n{output}"
    except subprocess.TimeoutExpired:
        return f"Command timed out after {COMMAND_TIMEOUT} seconds."
    except Exception as exc:
        return f"Command failed: {type(exc).__name__}: {exc}"
