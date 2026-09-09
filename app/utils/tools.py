import json
from pathlib import Path


def get_model_tools() -> list[dict]:
    tools_dir = Path(__file__).resolve().parent.parent / "tools"

    tools = []
    for file in tools_dir.glob("*.json"):  # строго *.json, не *.py!
        with open(file, "r", encoding="utf-8") as f:
            tools.append(json.load(f))

    return tools