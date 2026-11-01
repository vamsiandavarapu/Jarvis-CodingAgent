from pathlib import Path
from langchain_core.tools import tool
from app.config import WORKSPACE
from app.indexer import global_indexer
from app.patcher import apply_patch as patch_file
from app.tools.approval import request_approval


def safe_path(path: str) -> Path:
    """Resolve path and prevent workspace escape."""
    root = WORKSPACE.resolve()
    target = (root / path).resolve()
    if target != root and root not in target.parents:
        raise ValueError("Path is outside the configured Jarvis workspace.")
    return target


@tool
def create_file(path: str, content: str) -> str:
    """Create a new file in workspace."""
    target = safe_path(path)
    if target.exists():
        return f"File already exists: {path}. Use apply_patch or update_file to change it."
    if not request_approval(f"create file '{path}'"):
        return "Operation rejected by user."
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    # Incrementally update repository index
    global_indexer.update_file(path)
    return f"Created file: {path}"


@tool
def read_file(path: str) -> str:
    """Read file content."""
    target = safe_path(path)
    if not target.is_file():
        return f"File not found: {path}"
    try:
        return target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return "This file is not valid UTF-8 text and cannot be read by this tool."


@tool
def apply_patch(
    path: str, original_snippet: str, replacement_snippet: str, reason: str = ""
) -> str:
    """Apply a targeted contextual patch replacing exact original_snippet with replacement_snippet in an existing file.
    Use this tool instead of update_file for modifying existing code.
    """
    res = patch_file(
        file_path=path,
        original_snippet=original_snippet,
        replacement_snippet=replacement_snippet,
        reason=reason,
        require_approval=True,
    )
    if not res.success:
        return f"Patch failed: {res.message}"
    return f"{res.message}\nDiff:\n{res.diff}"


@tool
def update_file(path: str, content: str) -> str:
    """Replace entire contents of an existing file. Prefer apply_patch for targeted changes."""
    target = safe_path(path)
    if not target.is_file():
        return f"File not found: {path}. Use create_file for a new file."
    if not request_approval(f"replace the entire contents of '{path}'"):
        return "Operation rejected by user."
    target.write_text(content, encoding="utf-8")
    global_indexer.update_file(path)
    return f"Updated file: {path}"


@tool
def delete_file(path: str) -> str:
    """Delete a file."""
    target = safe_path(path)
    if not target.is_file():
        return f"File not found: {path}"
    if not request_approval(f"DELETE file '{path}'"):
        return "Operation rejected by user."
    target.unlink()
    global_indexer.update_file(path)
    return f"Deleted file: {path}"


@tool
def list_files(path: str = ".") -> str:
    """List files in workspace directory."""
    target = safe_path(path)
    if not target.is_dir():
        return f"Directory not found: {path}"
    entries = []
    for item in sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):
        suffix = "/" if item.is_dir() else ""
        entries.append(item.name + suffix)
    return "\n".join(entries) if entries else "(empty directory)"


@tool
def locate_symbol(query: str, target: str = "") -> str:
    """Search repository index for functions, classes, methods, or files matching query or target."""
    matches = global_indexer.locate(query, target=target if target else None)
    if not matches:
        return f"No symbols or files matching '{query or target}' found in repository index."

    lines = [f"Found {len(matches)} match(es):"]
    for m in matches[:10]:
        sym = f"'{m['symbol']}'" if m["symbol"] else "(file only)"
        tag = " [semantic]" if m.get("semantic") else ""
        reason = f" ({m['reason']})" if m.get("reason") else ""
        lines.append(
            f"- {m['file']} -> {m['type']} {sym} (lines {m['start']}-{m['end']}){tag}{reason}"
        )
    return "\n".join(lines)


@tool
def get_code_context(path: str, symbol: str = "") -> str:
    """Retrieve targeted source code context (snippet with line numbers and imports) for a file or specific symbol."""
    ctx = global_indexer.get_context(path, symbol_name=symbol if symbol else None)
    if not ctx:
        return f"Could not retrieve context for '{path}'."

    parts = [
        f"File: {ctx['file']} (Lines {ctx['start_line']} to {ctx['end_line']} of {ctx['total_lines']})",
        f"File Hash: {ctx['file_hash'][:12]}...",
    ]
    if ctx["imports"]:
        parts.append(f"Imports:\n{ctx['imports']}")
    parts.append(f"Code:\n{ctx['formatted_snippet']}")
    return "\n\n".join(parts)
