import ast
import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
import httpx
from app.config import WORKSPACE, GROQ_API_KEY, GROQ_MODEL

logger = logging.getLogger(__name__)

IGNORED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    "build",
    "dist",
    ".idea",
    ".vscode",
    ".pytest_cache",
    ".mypy_cache",
    ".tox",
}


def compute_file_hash(content: str) -> str:
    """Compute SHA-256 hash of text content."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def parse_python_ast(source_code: str, rel_path: str = "") -> Dict[str, Any]:
    """Extract functions, classes, and methods with line numbers using Python AST."""
    functions: List[Dict[str, Any]] = []
    classes: List[Dict[str, Any]] = []

    try:
        tree = ast.parse(source_code, filename=rel_path)
    except SyntaxError:
        return {"functions": [], "classes": [], "parse_error": True}

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append({
                "name": node.name,
                "start": node.lineno,
                "end": getattr(node, "end_lineno", node.lineno),
            })
        elif isinstance(node, ast.ClassDef):
            methods: List[Dict[str, Any]] = []
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    methods.append({
                        "name": item.name,
                        "start": item.lineno,
                        "end": getattr(item, "end_lineno", item.lineno),
                    })
            classes.append({
                "name": node.name,
                "start": node.lineno,
                "end": getattr(node, "end_lineno", node.lineno),
                "methods": methods,
            })

    return {"functions": functions, "classes": classes, "parse_error": False}


class RepoIndexer:
    """AST-based repository scanner, incremental indexer, and context locator."""

    def __init__(self, workspace: Optional[Path] = None):
        self.workspace = (workspace or WORKSPACE).resolve()
        self.repo_map: Dict[str, Dict[str, Any]] = {}

    def _is_ignored(self, path: Path) -> bool:
        """Check if any parent or name of path belongs to ignored directories."""
        try:
            rel_parts = path.relative_to(self.workspace).parts
            return any(part in IGNORED_DIRS for part in rel_parts)
        except ValueError:
            return True

    def scan_file(self, rel_path: str) -> Optional[Dict[str, Any]]:
        """Parse a single file and return its indexed metadata."""
        target = (self.workspace / rel_path).resolve()
        if not target.is_file():
            return None

        try:
            content = target.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            return None

        file_hash = compute_file_hash(content)
        ast_info = parse_python_ast(content, rel_path=rel_path)

        return {
            "hash": file_hash,
            "functions": ast_info["functions"],
            "classes": ast_info["classes"],
            "parse_error": ast_info["parse_error"],
        }

    def update_file(self, rel_path: str) -> bool:
        """Incrementally update or remove a single file in the repository map."""
        norm_path = Path(rel_path).as_posix()
        target = (self.workspace / norm_path).resolve()

        if not target.exists():
            if norm_path in self.repo_map:
                del self.repo_map[norm_path]
                return True
            return False

        if target.suffix != ".py":
            return False

        try:
            content = target.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            return False

        file_hash = compute_file_hash(content)
        existing = self.repo_map.get(norm_path)
        if existing and existing.get("hash") == file_hash:
            return False  # Content unchanged

        ast_info = parse_python_ast(content, rel_path=norm_path)
        self.repo_map[norm_path] = {
            "hash": file_hash,
            "functions": ast_info["functions"],
            "classes": ast_info["classes"],
            "parse_error": ast_info["parse_error"],
        }
        return True

    def scan_all(self) -> Dict[str, Dict[str, Any]]:
        """Perform a full scan of all Python files in the workspace."""
        new_map: Dict[str, Dict[str, Any]] = {}
        if not self.workspace.exists():
            self.repo_map = new_map
            return self.repo_map

        for file_path in self.workspace.rglob("*.py"):
            if not self._is_ignored(file_path) and file_path.is_file():
                rel_path = file_path.relative_to(self.workspace).as_posix()
                try:
                    content = file_path.read_text(encoding="utf-8")
                except (UnicodeDecodeError, OSError):
                    continue

                file_hash = compute_file_hash(content)
                ast_info = parse_python_ast(content, rel_path=rel_path)
                new_map[rel_path] = {
                    "hash": file_hash,
                    "functions": ast_info["functions"],
                    "classes": ast_info["classes"],
                    "parse_error": ast_info["parse_error"],
                }

        self.repo_map = new_map
        return self.repo_map

    def sync(self) -> Dict[str, List[str]]:
        """Incrementally sync repository map with current workspace files."""
        added: List[str] = []
        modified: List[str] = []
        deleted: List[str] = []

        if not self.workspace.exists():
            deleted = list(self.repo_map.keys())
            self.repo_map.clear()
            return {"added": added, "modified": modified, "deleted": deleted}

        current_files = set()
        for file_path in self.workspace.rglob("*.py"):
            if not self._is_ignored(file_path) and file_path.is_file():
                rel_path = file_path.relative_to(self.workspace).as_posix()
                current_files.add(rel_path)

                try:
                    content = file_path.read_text(encoding="utf-8")
                except (UnicodeDecodeError, OSError):
                    continue

                file_hash = compute_file_hash(content)
                existing = self.repo_map.get(rel_path)

                if existing is None:
                    ast_info = parse_python_ast(content, rel_path=rel_path)
                    self.repo_map[rel_path] = {
                        "hash": file_hash,
                        "functions": ast_info["functions"],
                        "classes": ast_info["classes"],
                        "parse_error": ast_info["parse_error"],
                    }
                    added.append(rel_path)
                elif existing.get("hash") != file_hash:
                    ast_info = parse_python_ast(content, rel_path=rel_path)
                    self.repo_map[rel_path] = {
                        "hash": file_hash,
                        "functions": ast_info["functions"],
                        "classes": ast_info["classes"],
                        "parse_error": ast_info["parse_error"],
                    }
                    modified.append(rel_path)

        for rel_path in list(self.repo_map.keys()):
            if rel_path not in current_files:
                del self.repo_map[rel_path]
                deleted.append(rel_path)

        return {"added": added, "modified": modified, "deleted": deleted}

    def locate(self, query: str, target: Optional[str] = None) -> List[Dict[str, Any]]:
        """Locate relevant files and symbols (functions, classes, methods) matching query or target."""
        matches: List[Dict[str, Any]] = []
        clean_target = (target or "").strip().lower()
        clean_query = query.strip().lower()

        # If map is empty, do an initial scan
        if not self.repo_map:
            self.scan_all()

        for rel_path, info in self.repo_map.items():
            file_lower = rel_path.lower()
            file_matched = (clean_target and clean_target in file_lower) or any(
                part in clean_query for part in Path(rel_path).name.lower().split(".")
            )

            # Match functions
            for fn in info.get("functions", []):
                fn_name_lower = fn["name"].lower()
                is_exact = clean_target == fn_name_lower or f"{fn_name_lower}()" == clean_target
                is_in_query = fn_name_lower in clean_query
                if is_exact or is_in_query or (file_matched and clean_target == ""):
                    matches.append({
                        "file": rel_path,
                        "symbol": fn["name"],
                        "type": "function",
                        "start": fn["start"],
                        "end": fn["end"],
                        "exact": is_exact,
                    })

            # Match classes and methods
            for cls in info.get("classes", []):
                cls_name_lower = cls["name"].lower()
                cls_exact = clean_target == cls_name_lower
                cls_in_query = cls_name_lower in clean_query
                if cls_exact or cls_in_query:
                    matches.append({
                        "file": rel_path,
                        "symbol": cls["name"],
                        "type": "class",
                        "start": cls["start"],
                        "end": cls["end"],
                        "exact": cls_exact,
                    })

                for m in cls.get("methods", []):
                    m_name_lower = m["name"].lower()
                    m_exact = clean_target == m_name_lower or f"{m_name_lower}()" == clean_target
                    m_in_query = m_name_lower in clean_query
                    if m_exact or m_in_query:
                        matches.append({
                            "file": rel_path,
                            "symbol": f"{cls['name']}.{m['name']}",
                            "type": "method",
                            "start": m["start"],
                            "end": m["end"],
                            "exact": m_exact,
                        })

            # If no symbols matched but file matches
            if file_matched and not any(m["file"] == rel_path for m in matches):
                matches.append({
                    "file": rel_path,
                    "symbol": None,
                    "type": "file",
                    "start": 1,
                    "end": 1,
                    "exact": clean_target == file_lower,
                })

        # Sort exact matches first
        matches.sort(key=lambda m: (not m.get("exact", False), m["file"]))

        if matches:
            return matches

        # Fallback to LLM semantic search when string matching yields no results
        return self._semantic_locate(query)

    def _semantic_locate(self, query: str) -> List[Dict[str, Any]]:
        """Fast semantic lookup using Groq when keyword matching yields no results."""
        if not self.repo_map or not GROQ_API_KEY:
            return []

        # 1. Format a compact outline of repository symbols, including class methods
        summary_lines = []
        for rel_path, info in self.repo_map.items():
            fns = [f["name"] for f in info.get("functions", [])]
            classes_info = []
            for c in info.get("classes", []):
                methods = [m["name"] for m in c.get("methods", [])]
                if methods:
                    classes_info.append(f"{c['name']}({', '.join(methods)})")
                else:
                    classes_info.append(c["name"])

            parts = [f"File: {rel_path}"]
            if fns:
                parts.append(f"Functions: {', '.join(fns)}")
            if classes_info:
                parts.append(f"Classes: {'; '.join(classes_info)}")
            summary_lines.append(" | ".join(parts))

        system_prompt = (
            "You are a code locator. Identify matching files and symbols based on meaning.\n"
            "Return ONLY a JSON array of objects: [{\"file\": \"...\", \"symbol\": \"...\", \"reason\": \"...\"}]\n"
            "Note: 'symbol' can be a function, ClassName, or ClassName.method_name. Set 'symbol' to null only for whole-file matches.\n"
            "If nothing matches, return []."
        )
        payload = {
            "model": GROQ_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Query: {query}\n\nRepo:\n" + "\n".join(summary_lines)},
            ],
            "temperature": 0.0,
            "max_tokens": 250,
        }

        try:
            resp = httpx.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
                json=payload,
                timeout=15.0,
            )
            if resp.status_code != 200:
                logger.warning(
                    f"Groq semantic search failed: HTTP {resp.status_code} - {resp.text[:200]}"
                )
                return []
            content = resp.json()["choices"][0]["message"]["content"].strip()
            if content.startswith("```"):
                content = re.sub(r"^```(?:json)?\s*", "", content)
                content = re.sub(r"\s*```$", "", content)
            items = json.loads(content)
            if not isinstance(items, list):
                logger.warning(f"Groq semantic search returned non-list response: {content[:100]}")
                return []
        except Exception as exc:
            logger.warning(f"Groq semantic search error: {type(exc).__name__}: {exc}")
            return []

        # 2. Validate suggestions against repo_map to prevent hallucinations
        validated_matches: List[Dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            file_path = str(item.get("file", "")).strip()
            if file_path not in self.repo_map:
                continue

            raw_sym = item.get("symbol")
            sym = str(raw_sym).strip() if raw_sym and str(raw_sym).lower() != "null" else None
            info = self.repo_map[file_path]
            matched = False

            if sym:
                clean_sym = sym.replace("()", "").strip().lower()

                # A. Check top-level functions
                for fn in info.get("functions", []):
                    if fn["name"].lower() == clean_sym:
                        validated_matches.append({
                            "file": file_path,
                            "symbol": fn["name"],
                            "type": "function",
                            "start": fn["start"],
                            "end": fn["end"],
                            "exact": False,
                            "semantic": True,
                            "reason": item.get("reason", ""),
                        })
                        matched = True
                        break

                # B. Check classes and class methods (e.g. AuthManager or AuthManager.login or login)
                if not matched:
                    for cls in info.get("classes", []):
                        cls_name_lower = cls["name"].lower()

                        # Match class itself
                        if cls_name_lower == clean_sym:
                            validated_matches.append({
                                "file": file_path,
                                "symbol": cls["name"],
                                "type": "class",
                                "start": cls["start"],
                                "end": cls["end"],
                                "exact": False,
                                "semantic": True,
                                "reason": item.get("reason", ""),
                            })
                            matched = True
                            break

                        # Match methods inside class
                        for m in cls.get("methods", []):
                            m_name_lower = m["name"].lower()
                            full_m_lower = f"{cls_name_lower}.{m_name_lower}"
                            if clean_sym in (m_name_lower, full_m_lower):
                                validated_matches.append({
                                    "file": file_path,
                                    "symbol": f"{cls['name']}.{m['name']}",
                                    "type": "method",
                                    "start": m["start"],
                                    "end": m["end"],
                                    "exact": False,
                                    "semantic": True,
                                    "reason": item.get("reason", ""),
                                })
                                matched = True
                                break
                        if matched:
                            break

                # If Groq specifically named a symbol that doesn't exist, log and discard it
                if not matched:
                    logger.debug(
                        f"Discarded hallucinated symbol '{sym}' for file '{file_path}'"
                    )
            else:
                # Whole-file match explicitly indicated (symbol is None/null)
                validated_matches.append({
                    "file": file_path,
                    "symbol": None,
                    "type": "file",
                    "start": 1,
                    "end": 1,
                    "exact": False,
                    "semantic": True,
                    "reason": item.get("reason", ""),
                })

        return validated_matches

    def get_context(
        self, rel_path: str, symbol_name: Optional[str] = None, padding: int = 5
    ) -> Optional[Dict[str, Any]]:
        """Retrieve relevant code context for a file or symbol with surrounding lines."""
        norm_path = Path(rel_path).as_posix()
        target = (self.workspace / norm_path).resolve()
        if not target.is_file():
            return None

        try:
            content = target.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            return None

        lines = content.splitlines()
        total_lines = len(lines)
        file_hash = compute_file_hash(content)

        # Collect top-level imports
        imports: List[str] = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("import ") or stripped.startswith("from "):
                imports.append(line)

        # If a specific symbol is requested, locate line range
        start_line = 1
        end_line = total_lines

        if symbol_name and norm_path in self.repo_map:
            info = self.repo_map[norm_path]
            clean_sym = symbol_name.replace("()", "").strip()

            # Check functions
            for fn in info.get("functions", []):
                if fn["name"] == clean_sym:
                    start_line = max(1, fn["start"] - padding)
                    end_line = min(total_lines, fn["end"] + padding)
                    break

            # Check classes / methods
            for cls in info.get("classes", []):
                if cls["name"] == clean_sym:
                    start_line = max(1, cls["start"] - padding)
                    end_line = min(total_lines, cls["end"] + padding)
                    break
                for m in cls.get("methods", []):
                    if m["name"] == clean_sym or f"{cls['name']}.{m['name']}" == clean_sym:
                        start_line = max(1, m["start"] - padding)
                        end_line = min(total_lines, m["end"] + padding)
                        break

        # Extract targeted lines with line numbers
        snippet_lines = []
        for i in range(start_line - 1, end_line):
            if 0 <= i < total_lines:
                snippet_lines.append(f"{i + 1:4d} | {lines[i]}")

        snippet_code = "\n".join(lines[start_line - 1:end_line])

        return {
            "file": norm_path,
            "symbol": symbol_name,
            "start_line": start_line,
            "end_line": end_line,
            "total_lines": total_lines,
            "formatted_snippet": "\n".join(snippet_lines),
            "code": snippet_code,
            "imports": "\n".join(imports),
            "file_hash": file_hash,
        }

    def get_map(self) -> Dict[str, Dict[str, Any]]:
        """Return the current repository map."""
        return self.repo_map


# Global indexer instance for convenience
global_indexer = RepoIndexer()

