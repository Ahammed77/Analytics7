"""Configuration, read from environment variables with demo defaults."""
import os
from pathlib import Path

CHATBOT_DIR = Path(__file__).resolve().parent.parent


def _path(name: str, default: Path) -> Path:
    return Path(os.environ.get(name, default))


CUBE_YAML_DIR = _path("A7_CUBE_YAML_DIR", CHATBOT_DIR.parent / "cube" / "model" / "cubes")
OVERLAY_PATH = _path("A7_OVERLAY_PATH", CHATBOT_DIR / "config" / "catalogue_overlay.yml")
CATALOGUE_PATH = _path("A7_CATALOGUE_PATH", CHATBOT_DIR / "catalogue" / "catalogue.json")
APPROVED_QUESTIONS_PATH = _path("A7_APPROVED_QUESTIONS_PATH", CHATBOT_DIR / "config" / "approved_questions.yml")
FIXED_REPLY_PATH = _path("A7_FIXED_REPLY_PATH", CHATBOT_DIR / "config" / "fixed_reply.txt")
REQUEST_LOG_PATH = _path("A7_REQUEST_LOG_PATH", CHATBOT_DIR / "logs" / "requests.jsonl")
RUNS_DIR = _path("A7_RUNS_DIR", CHATBOT_DIR / "runs")

# Read-only role; see db/roles.sql.
DATABASE_URL = os.environ.get("A7_DATABASE_URL", "postgresql://a7_reader:a7_reader@localhost:5432/a7_reporting")
ROW_LIMIT = int(os.environ.get("A7_ROW_LIMIT", "500"))
STATEMENT_TIMEOUT_MS = int(os.environ.get("A7_STATEMENT_TIMEOUT_MS", "5000"))

# "claude" calls the Anthropic API (demo only: fake data may go to an external model).
# "recorded" replays the structured queries in approved_questions.yml: an offline backup
# that answers only the approved questions. Tests inject their own recorded model.
QUERY_MODEL = os.environ.get("A7_QUERY_MODEL", "claude")
CLAUDE_MODEL = os.environ.get("A7_CLAUDE_MODEL", "claude-opus-5-5")
