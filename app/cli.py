from app.agent import JarvisAgent
from app.config import WORKSPACE


def main():
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    print("Jarvis Phase 1 — modular coding assistant")
    print(f"Workspace: {WORKSPACE}")
    print("Type 'exit' to quit.\n")

    agent = JarvisAgent()

    while True:
        try:
            user_text = input("You: ").strip()
            if user_text.lower() in {"exit", "quit"}:
                print("Jarvis: Goodbye!")
                break
            if not user_text:
                continue
            response = agent.ask(user_text)
            wf = f"[{agent.last_route.task_type}] " if agent.last_route else ""
            print(f"\nJarvis {wf}: {response}\n")
        except KeyboardInterrupt:
            print("\nJarvis: Goodbye!")
            break


if __name__ == "__main__":
    main()
