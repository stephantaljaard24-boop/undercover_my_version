"""UnderCover's business data, the files in data/."""

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).parent.parent / "data"


def load_json(name: str) -> Any:
    """Read a data file, keeping amounts as Decimal."""
    text = (DATA_DIR / name).read_text(encoding="utf-8")
    return json.loads(text, parse_float=Decimal)
