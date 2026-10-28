"""Conversation store: past questions and their structured queries, per conversation. Never rows."""
from __future__ import annotations

import threading
from dataclasses import dataclass

from .structured_query import StructuredQuery


@dataclass(frozen=True)
class Turn:
    question: str
    structured_query: StructuredQuery

    def to_prompt(self) -> dict:
        return {"question": self.question, "structured_query": self.structured_query.to_dict()}


class ConversationStore:
    def __init__(self) -> None:
        self._turns: dict[str, list[Turn]] = {}
        self._lock = threading.Lock()

    def turns(self, conversation_id: str) -> list[Turn]:
        with self._lock:
            return list(self._turns.get(conversation_id, []))

    def append(self, conversation_id: str, question: str, structured_query: StructuredQuery) -> None:
        if not isinstance(structured_query, StructuredQuery):
            raise TypeError("only structured queries are stored")
        with self._lock:
            self._turns.setdefault(conversation_id, []).append(Turn(question, structured_query))
