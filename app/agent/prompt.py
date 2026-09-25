from pathlib import Path


def load_system_prompt() -> str:
    prompt_path = Path(__file__).resolve().parent.parent / "promts" / "system.md"
    return prompt_path.read_text(encoding="utf-8")
