import json
from pathlib import Path


def load_schema(name: str) -> dict:
    tools_dir = Path(__file__).resolve().parent.parent / "tools"
    file = tools_dir / f"{name}.json"
    with open(file, "r") as f:
        return json.load(f)