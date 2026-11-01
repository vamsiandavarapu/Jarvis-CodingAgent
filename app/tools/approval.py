def request_approval(action: str) -> bool:
    """Ask the local CLI user to approve an operation."""
    answer = input(f"\nJarvis wants to {action}\nApprove? [y/N]: ").strip().lower()
    return answer == "y"
