import json
from pathlib import Path

from backend.main import app

SAVED = Path(__file__).parent / "openapi.json"


def test_the_api_is_as_saved():
    """The API only changes on purpose: then save the new document."""
    saved = json.loads(SAVED.read_text(encoding="utf-8"))
    assert json.loads(json.dumps(app.openapi())) == saved
