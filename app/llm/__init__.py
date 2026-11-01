import json
import re
from dataclasses import dataclass
from typing import Optional
import httpx
from langchain_google_genai import ChatGoogleGenerativeAI
from app.config import (
    GEMINI_API_KEY,
    GEMINI_MODEL,
    GROQ_API_KEY,
    GROQ_MODEL,
)

VALID_TASK_TYPES = {"CREATE", "UPDATE", "SEARCH", "DEBUG", "TEST", "GENERAL"}


@dataclass
class TaskRoute:
    task_type: str  # CREATE, UPDATE, SEARCH, DEBUG, TEST, GENERAL
    target: Optional[str] = None
    description: str = ""


def get_gemini_model():
    """Initialize and return the primary Gemini coding model."""
    if not GEMINI_API_KEY:
        raise RuntimeError(
            "Missing Gemini API key. Add GOOGLE_API_KEY=... to your .env file."
        )
    return ChatGoogleGenerativeAI(
        model=GEMINI_MODEL,
        google_api_key=GEMINI_API_KEY,
        temperature=0,
    )


def _extract_target(text: str) -> Optional[str]:
    """Helper to detect mentioned file paths or function/class names."""
    # Match common file patterns (e.g., auth/login.py, main.py, test_app.py)
    file_match = re.search(r"[\w\./\\-]+\.(?:py|js|ts|json|html|css|md|txt)", text)
    if file_match:
        return file_match.group(0).strip()
    # Match function or symbol patterns like login() or function_name()
    sym_match = re.search(r"\b([a-zA-Z_]\w*)\(\)", text)
    if sym_match:
        return sym_match.group(1).strip()
    # Match phrases like "function validate_user" or "class User" or "def login"
    named_match = re.search(r"\b(?:function|class|method|def)\s+([a-zA-Z_]\w*)", text, re.IGNORECASE)
    if named_match:
        return named_match.group(1).strip()
    return None


def classify_with_python(text: str) -> TaskRoute:
    """Deterministic, fast Python-based task classifier fallback."""
    lowered = text.lower().strip()
    target = _extract_target(text)

    # Test workflow
    if any(k in lowered for k in ["pytest", "run test", "run tests", "execute test", "unit test"]):
        return TaskRoute(task_type="TEST", target=target, description=text[:80])

    # Search workflow
    if any(k in lowered for k in ["find", "search", "where is", "locate", "list function", "find symbol"]):
        return TaskRoute(task_type="SEARCH", target=target, description=text[:80])

    # Debug workflow
    if any(k in lowered for k in ["fix bug", "fix error", "debug", "traceback", "syntaxerror", "exception"]):
        return TaskRoute(task_type="DEBUG", target=target, description=text[:80])

    # Create workflow
    if any(k in lowered for k in ["create file", "new file", "add file", "make file", "create new"]):
        return TaskRoute(task_type="CREATE", target=target, description=text[:80])

    # Update workflow
    if any(k in lowered for k in ["update", "modify", "change", "edit", "add to", "refactor", "patch"]):
        return TaskRoute(task_type="UPDATE", target=target, description=text[:80])

    return TaskRoute(task_type="GENERAL", target=target, description=text[:80])


def classify_with_groq(text: str) -> Optional[TaskRoute]:
    """Classify the user task using Groq if configured."""
    if not GROQ_API_KEY:
        return None

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }
    system_prompt = (
        "You are a lightweight task router for a coding agent.\n"
        "Analyze the user request and classify it into one of these task types:\n"
        "CREATE: creating a new file or feature from scratch.\n"
        "UPDATE: modifying or refactoring an existing file or function.\n"
        "SEARCH: finding a symbol, function, class, or file.\n"
        "DEBUG: fixing an error, bug, or exception.\n"
        "TEST: running or verifying tests.\n"
        "GENERAL: general inquiries or other operations.\n\n"
        "Return ONLY a JSON object with this exact format:\n"
        "{\"task_type\": \"<TYPE>\", \"target\": \"<path or symbol or null>\", \"description\": \"<brief description>\"}"
    )

    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text},
        ],
        "temperature": 0.0,
        "max_tokens": 150,
    }

    try:
        response = httpx.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=5.0,
        )
        if response.status_code != 200:
            return None

        content = response.json()["choices"][0]["message"]["content"].strip()
        # Strip potential markdown fences
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?\s*", "", content)
            content = re.sub(r"\s*```$", "", content)

        data = json.loads(content)
        task_type = str(data.get("task_type", "GENERAL")).upper()
        if task_type not in VALID_TASK_TYPES:
            task_type = "GENERAL"

        raw_target = data.get("target")
        target = str(raw_target).strip() if raw_target and str(raw_target).lower() != "null" else None
        description = str(data.get("description", text[:80])).strip()

        return TaskRoute(task_type=task_type, target=target, description=description)
    except Exception:
        # Graceful fallback on any network or parsing error
        return None


def route_task(text: str) -> TaskRoute:
    """Route a user coding task using Groq with deterministic Python fallback."""
    if GROQ_API_KEY:
        groq_route = classify_with_groq(text)
        if groq_route is not None:
            return groq_route
    return classify_with_python(text)


__all__ = [
    "TaskRoute",
    "get_gemini_model",
    "route_task",
    "classify_with_python",
    "classify_with_groq",
]
