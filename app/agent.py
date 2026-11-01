from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from app.indexer import global_indexer
from app.llm import get_gemini_model, route_task
from app.tools.command_tool import run_cmd
from app.tools.file_tools import (
    apply_patch,
    create_file,
    delete_file,
    get_code_context,
    list_files,
    locate_symbol,
    read_file,
    update_file,
)

SYSTEM_PROMPT = """
You are Jarvis, a context-aware, human-supervised, self-recovering AI coding assistant.
The configured workspace is your only project workspace.

Core Guidelines:
1. Locate first: When asked to find or modify symbols, functions, or classes, use locate_symbol.
2. Targeted context: Use get_code_context or read_file to inspect only the required context. Do not load entire projects into memory.
3. Targeted modifications: When modifying existing files, always prefer apply_patch. Specify the exact original_snippet and the replacement_snippet.
4. New files: Use create_file only when creating brand new files.
5. Verification: Use run_cmd for Git operations or running tests.
6. Honesty: Never claim an operation succeeded unless the tool output confirms it.
7. Ambiguity: Ask the user for clarification when a target or instruction is ambiguous.
"""

TOOLS = [
    locate_symbol,
    get_code_context,
    apply_patch,
    read_file,
    create_file,
    update_file,
    delete_file,
    list_files,
    run_cmd,
]


class JarvisAgent:
    def __init__(self):
        self.model = get_gemini_model().bind_tools(TOOLS)
        self.messages = [SystemMessage(content=SYSTEM_PROMPT)]
        self.last_route = None
        # Initialize repository index
        global_indexer.sync()

    def ask(self, user_text: str) -> str:
        # Route the task to determine workflow (CREATE, UPDATE, SEARCH, DEBUG, TEST, GENERAL)
        self.last_route = route_task(user_text)

        self.messages.append(HumanMessage(content=user_text))

        # Tool execution map
        tool_map = {
            "locate_symbol": locate_symbol,
            "get_code_context": get_code_context,
            "apply_patch": apply_patch,
            "read_file": read_file,
            "create_file": create_file,
            "update_file": update_file,
            "delete_file": delete_file,
            "list_files": list_files,
            "run_cmd": run_cmd,
        }

        # Bounded tool loop
        for _ in range(8):
            response = self.model.invoke(self.messages)
            self.messages.append(response)

            if not response.tool_calls:
                content = response.content
                if isinstance(content, list):
                    content = "".join(
                        c.get("text", "") if isinstance(c, dict) else str(c)
                        for c in content
                    )
                return str(content)

            for call in response.tool_calls:
                name = call["name"]
                args = call.get("args", {})
                tool = tool_map.get(name)

                if tool is None:
                    result = f"Unknown tool: {name}"
                else:
                    try:
                        result = tool.invoke(args)
                    except Exception as exc:
                        result = f"Tool error: {type(exc).__name__}: {exc}"

                self.messages.append(
                    ToolMessage(
                        content=str(result),
                        tool_call_id=call["id"],
                    )
                )

        return "Stopped after 8 tool-calling rounds to prevent an endless loop."
