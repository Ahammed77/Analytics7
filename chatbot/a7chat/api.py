"""App backend: the message endpoint (the test seam), suggested questions, and the chat page.

    uvicorn --factory a7chat.api:create_app     # settings come from A7_* environment variables
"""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from . import catalogue as cat
from . import settings
from .conversation import ConversationStore
from .executor import Executor
from .orchestrator import Orchestrator
from .query_model import QueryModel, make_query_model, suggestions_from_config
from .request_log import RequestLog

STATIC = Path(__file__).with_name("static")


class MessageIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    conversation_id: str | None = None


def create_app(*, catalogue: dict[str, Any] | None = None, query_model: QueryModel | None = None,
               executor: Executor | None = None, store: ConversationStore | None = None,
               log: RequestLog | None = None, approved_questions_path: Path | None = None,
               fixed_reply: str | None = None, row_limit: int | None = None) -> FastAPI:
    approved_questions_path = Path(approved_questions_path or settings.APPROVED_QUESTIONS_PATH)
    catalogue = catalogue or cat.load()
    query_model = query_model or make_query_model(settings.QUERY_MODEL, approved_questions_path)
    suggestions = suggestions_from_config(approved_questions_path)
    orchestrator = Orchestrator(
        catalogue=catalogue,
        query_model=query_model,
        executor=executor or Executor(settings.DATABASE_URL, settings.STATEMENT_TIMEOUT_MS),
        store=store or ConversationStore(),
        log=log or RequestLog(settings.REQUEST_LOG_PATH),
        fixed_reply=fixed_reply or settings.FIXED_REPLY_PATH.read_text(encoding="utf-8").strip(),
        suggestions=suggestions,
        row_limit=row_limit or settings.ROW_LIMIT,
    )

    app = FastAPI(title="Analytics 7 Chatbot")
    app.state.orchestrator = orchestrator

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    @app.get("/api/suggestions")
    def get_suggestions() -> dict[str, list[str]]:
        return {"suggestions": orchestrator.suggestions}

    @app.post("/api/messages")
    def post_message(body: MessageIn) -> dict[str, Any]:
        conversation_id = body.conversation_id or uuid.uuid4().hex
        answer = orchestrator.handle(conversation_id, body.message.strip())
        return {"conversation_id": conversation_id, **answer}

    return app

