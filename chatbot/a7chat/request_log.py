"""Request log: one JSON line per request. Question, catalogue version, structured query,
compiled SQL, row count and time taken; never rows. Stored wherever A7_REQUEST_LOG_PATH
points, which in the product is inside the customer's region."""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

FIELDS = ("ts", "conversation_id", "question", "catalogue_version", "structured_query", "sql",
          "row_count", "duration_ms", "outcome", "prompt_check", "trace")


class RequestLog:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.Lock()

    def write(self, **entry: Any) -> None:
        unknown = set(entry) - set(FIELDS)
        if unknown:
            raise ValueError(f"not a request log field: {sorted(unknown)}")
        line: dict[str, Any] = {"ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds")}
        line.update({key: entry.get(key) for key in FIELDS if key != "ts"})
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(line, default=str) + "\n")

    def lines(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines() if line.strip()]
