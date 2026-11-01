# Jarvis — AI Coding Agent

A context-aware, human-supervised, and self-recovering local AI coding assistant.

## Current Capabilities

- **Dual-Model LLM Layer (`app/llm`)**:
  - **Gemini**: Primary intelligence for reasoning, planning, targeted code generation, and patch synthesis.
  - **Groq Task Router (Optional)**: Ultra-fast task classification (`CREATE`, `UPDATE`, `SEARCH`, `DEBUG`, `TEST`, `GENERAL`).
  - **Safe Fallback**: If Groq is not configured or fails, deterministic Python classification handles routing seamlessly.
- **AST-Based Repository Indexer (`app/indexer.py`)**:
  - Parses Python files using standard library `ast` without vector databases.
  - Extracts functions, classes, methods, and line ranges.
  - Incremental indexing using SHA-256 file hashes to re-parse only modified or added files.
- **Localization & Context Retrieval**:
  - `locate_symbol`: Pinpoints files and symbol definitions without reading whole repositories.
  - `get_code_context`: Retrieves only the required function/class snippet, line numbers, and file imports.
- **Contextual Patch-Based Editing (`app/patcher.py`)**:
  - `apply_patch`: Replaces exact snippet with proposed replacement.
  - **Validation**: Enforces target file existence, unique snippet match (rejects ambiguous matches), and hash freshness (rejects stale patches).
  - **Unified Diff**: Displays git-style unified diff for human inspection.
  - **Interactive Human Approval**: Requests user approval before applying changes to disk.
  - **Automatic Incremental Re-indexing**: Updates the repository map immediately upon applying changes.
- **Safety & Workspaces**:
  - Workspace boundaries enforced (`safe_path`).
  - Command timeout and interactive approval for terminal execution (`run_cmd`).

## Setup (Windows PowerShell)

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `.env` and configure your API keys:
- `GOOGLE_API_KEY`: Your Gemini API key (required).
- `GROQ_API_KEY`: Your Groq API key (optional for fast task routing).

Run:

```powershell
python -m app.cli
```

## Running Tests

Run the unit test suite:

```powershell
python -m unittest discover -s tests -v
```
