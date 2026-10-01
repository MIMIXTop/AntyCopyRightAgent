import json
from pathlib import Path
from app.core.logging import logger


def load_schema(name: str) -> dict:
    tools_dir = Path(__file__).resolve().parent.parent / "tools"
    file = tools_dir / f"{name}.json"
    logger.info("Loading tool schema: name=%s path=%s", name, file)
    with open(file, "r") as f:
        schema = json.load(f)
    logger.info("Tool schema loaded: name=%s schema=%s", name, schema)
    return schema