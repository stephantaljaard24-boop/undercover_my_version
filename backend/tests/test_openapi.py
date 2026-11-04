import json
from pathlib import Path

from backend.main import app

SAVED = Path(__file__).parent / "openapi.json"
SAVE = (
    'uv run python -c "import json; from backend.main import app; '
    "open('backend/tests/openapi.json', 'w', encoding='utf-8')"
    ".write(json.dumps(app.openapi(), indent=2, sort_keys=True) + '\\n')\""
)


def test_the_api_is_as_saved():
    """The API only changes on purpose: then save the new document."""
    saved = json.loads(SAVED.read_text(encoding="utf-8"))
    assert json.loads(json.dumps(app.openapi())) == saved, (
        f"The API differs from backend/tests/openapi.json. If you meant to "
        f"change it, review the diff and save the new document with:\n{SAVE}"
    )
