import difflib
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple
from app.config import WORKSPACE
from app.indexer import compute_file_hash, global_indexer
from app.tools.approval import request_approval


@dataclass
class PatchResult:
    success: bool
    message: str
    diff: str = ""


def safe_workspace_path(path: str, workspace: Optional[Path] = None) -> Path:
    """Resolve path and ensure it stays inside the workspace."""
    root = (workspace or WORKSPACE).resolve()
    target = (root / path).resolve()
    if target != root and root not in target.parents:
        raise ValueError("Path is outside the configured workspace.")
    return target


def create_unified_diff(file_path: str, old_text: str, new_text: str) -> str:
    """Generate a standard unified diff string."""
    diff_lines = list(
        difflib.unified_diff(
            old_text.splitlines(),
            new_text.splitlines(),
            fromfile=f"a/{file_path}",
            tofile=f"b/{file_path}",
            lineterm="",
        )
    )
    return "\n".join(diff_lines)


def validate_patch(
    file_path: str,
    original_snippet: str,
    replacement_snippet: str,
    expected_hash: Optional[str] = None,
    workspace: Optional[Path] = None,
) -> Tuple[bool, str]:
    """Verify that the target file exists, matches expected hash, and snippet is unique."""
    if not file_path or not file_path.strip():
        return False, "No file path provided."

    if not original_snippet:
        return False, "Original snippet cannot be empty."

    try:
        target = safe_workspace_path(file_path, workspace)
    except ValueError as exc:
        return False, str(exc)

    if not target.is_file():
        return False, f"Target file '{file_path}' does not exist."

    try:
        content = target.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError) as exc:
        return False, f"Could not read '{file_path}': {exc}"

    if expected_hash:
        current_hash = compute_file_hash(content)
        if current_hash != expected_hash:
            return (
                False,
                f"File '{file_path}' has changed since context retrieval (stale patch). "
                f"Expected hash {expected_hash[:8]}..., found {current_hash[:8]}...",
            )

    occurrences = content.count(original_snippet)
    if occurrences == 0:
        return (
            False,
            f"Original snippet was not found in '{file_path}'. "
            "Please retrieve fresh context and ensure indentation/characters match exactly.",
        )
    if occurrences > 1:
        return (
            False,
            f"Original snippet occurs {occurrences} times in '{file_path}' (ambiguous match). "
            "Please include more surrounding lines in original_snippet to make it unique.",
        )

    return True, "Patch is valid."


def apply_patch(
    file_path: str,
    original_snippet: str,
    replacement_snippet: str,
    reason: str = "",
    expected_hash: Optional[str] = None,
    require_approval: bool = True,
    workspace: Optional[Path] = None,
) -> PatchResult:
    """Validate, preview diff, request approval, apply patch, and incrementally re-index."""
    valid, message = validate_patch(
        file_path, original_snippet, replacement_snippet, expected_hash, workspace
    )
    if not valid:
        return PatchResult(success=False, message=message)

    target = safe_workspace_path(file_path, workspace)
    content = target.read_text(encoding="utf-8")

    new_content = content.replace(original_snippet, replacement_snippet, 1)
    diff = create_unified_diff(file_path, content, new_content)

    if require_approval:
        approval_prompt = (
            f"apply patch to '{file_path}'"
            + (f" (Reason: {reason})" if reason else "")
            + f":\n\n{diff}\n"
        )
        if not request_approval(approval_prompt):
            return PatchResult(
                success=False,
                message="Patch rejected by user.",
                diff=diff,
            )

    # Apply changes atomically
    try:
        target.write_text(new_content, encoding="utf-8")
    except OSError as exc:
        return PatchResult(
            success=False,
            message=f"Failed to write patch to '{file_path}': {exc}",
            diff=diff,
        )

    # Incremental re-indexing of the modified file only (Phase 7)
    rel_path = target.relative_to((workspace or WORKSPACE).resolve()).as_posix()
    global_indexer.update_file(rel_path)

    return PatchResult(
        success=True,
        message=f"Successfully applied patch to '{file_path}'.",
        diff=diff,
    )

