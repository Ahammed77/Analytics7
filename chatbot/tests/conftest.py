"""Test seam: the message endpoint, with the query model replaced by recorded structured queries,
run against a real Postgres loaded with the demo dataset (pgserver bundles the binaries)."""
from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from a7chat import catalogue as cat
from a7chat import settings
from a7chat.api import create_app
from a7chat.expectations import rows_as_dicts  # noqa: F401 - shared with the test modules
from a7chat.conversation import ConversationStore
from a7chat.executor import Executor
from a7chat.query_model import RecordedQueryModel, Recording, recordings_from_config
from a7chat.request_log import RequestLog
from dev_server import start_reporting_db


@dataclass
class Database:
    admin_url: str
    reader_url: str


@pytest.fixture(scope="session")
def database():
    data_dir = Path(tempfile.mkdtemp(prefix="a7pg-"))  # outside OneDrive
    server, admin_url, reader_url = start_reporting_db(data_dir)
    yield Database(admin_url, reader_url)
    server.cleanup()
    shutil.rmtree(data_dir, ignore_errors=True)


class SpyExecutor(Executor):
    """The real read-only executor, counting the statements that reach the database."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.statements: list[str] = []

    def run(self, sql, params=()):
        self.statements.append(sql)  # recorded first, so a statement that fails still counts
        return super().run(sql, params)


@dataclass
class Chat:
    client: TestClient
    model: RecordedQueryModel
    executor: SpyExecutor
    store: ConversationStore
    log: RequestLog
    conversation_id: str = "conv-1"
    responses: list[dict] = field(default_factory=list)

    def ask(self, message: str, conversation_id: str | None = None) -> dict:
        response = self.client.post("/api/messages", json={"message": message, "conversation_id": conversation_id or self.conversation_id})
        assert response.status_code == 200, response.text
        body = response.json()
        self.responses.append(body)
        return body


@pytest.fixture
def make_chat(database, tmp_path):
    """Build the app at the seam. Extra recordings and settings can be passed per test."""

    def build(recordings: list[Recording] | None = None, *, catalogue=None, statement_timeout_ms=5000,
              row_limit=500, approved_questions_path: Path | None = None) -> Chat:
        approved = approved_questions_path or settings.APPROVED_QUESTIONS_PATH
        model = RecordedQueryModel(recordings_from_config(approved) + list(recordings or []))
        executor = SpyExecutor(database.reader_url, statement_timeout_ms)
        store = ConversationStore()
        log = RequestLog(tmp_path / "requests.jsonl")
        app = create_app(catalogue=catalogue or cat.load(), query_model=model, executor=executor, store=store,
                         log=log, approved_questions_path=approved, row_limit=row_limit)
        return Chat(TestClient(app), model, executor, store, log)

    return build
