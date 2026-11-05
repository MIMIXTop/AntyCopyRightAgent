from pathlib import Path


def load_system_prompt() -> str:
    prompt_path = Path(__file__).resolve().parent.parent / "promts" / "system.md"
    return prompt_path.read_text(encoding="utf-8")


def load_speech_prompt() -> str:
    prompt_path = Path(__file__).resolve().parent.parent / "promts" / "speech.md"
    return prompt_path.read_text(encoding="utf-8")
