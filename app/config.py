import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

WORKSPACE = Path(os.getenv("JARVIS_WORKSPACE", "./workspace")).expanduser().resolve()
GEMINI_API_KEY = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
COMMAND_TIMEOUT = int(os.getenv("JARVIS_COMMAND_TIMEOUT", "60"))
