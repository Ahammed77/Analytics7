"""Plain-code orchestrator: ask -> compile -> run -> phrase, always in that order. No model decides what happens next."""
from __future__ import annotations

import time
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import psycopg

from . import catalogue as cat
from . import formatter, structured_query
from .conversation import ConversationStore
from .engine import Engine
from .executor import Executor, QueryTimeout, WriteRefused
from .query_model import PromptCheckFailed, QueryModel, build_prompt, check_prompt
from .request_log import RequestLog


def _cell(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.date().isoformat() if value.time() == datetime.min.time() else value.isoformat(sep=" ", timespec="minutes")
    if isinstance(value, date):
        return value.isoformat()
    return value


class Orchestrator:
    def __init__(self, *, catalogue: dict[str, Any], query_model: QueryModel, executor: Executor,
                 store: ConversationStore, log: RequestLog, fixed_reply: str, suggestions: list[str],
                 row_limit: int):
        self.catalogue = catalogue
        self.view = cat.model_view(catalogue)
        self.engine = Engine(catalogue, row_limit)
        self.query_model = query_model
        self.executor = executor
        self.store = store
        self.log = log
        self.fixed_reply_text = fixed_reply
        self.suggestions = suggestions

    def _fixed_reply(self) -> dict[str, Any]:
        return {"kind": "fixed_reply", "text": self.fixed_reply_text, "suggestions": list(self.suggestions)}

    def handle(self, conversation_id: str, message: str) -> dict[str, Any]:
        started = time.perf_counter()
        entry: dict[str, Any] = {"conversation_id": conversation_id, "question": message,
                                 "catalogue_version": self.catalogue["version"], "trace": []}
        try:
            response = self._handle(conversation_id, message, entry)
        finally:
            entry["duration_ms"] = round((time.perf_counter() - started) * 1000, 1)
            self.log.write(**entry)
        return response

    def _handle(self, conversation_id: str, message: str, entry: dict[str, Any]) -> dict[str, Any]:
        trace = entry["trace"]
        turns = self.store.turns(conversation_id)

        # 1. Ask: the model gets the catalogue view, earlier turns and the question. Never rows.
        prompt = build_prompt(self.view, message, turns)
        try:
            check_prompt(prompt, catalogue_view=self.view, question=message, turns=turns)
            entry["prompt_check"] = "pass"
        except PromptCheckFailed as exc:
            entry.update(prompt_check=f"fail: {exc}", outcome="prompt_check_failed")
            return self._fixed_reply()
        trace.append({"step": "ask", "to": "query_model", "sent": sorted(prompt), "earlier_turns": len(turns)})
        try:
            parsed = structured_query.from_model_output(self.query_model.ask(prompt))
        except structured_query.InvalidStructuredQuery as exc:
            trace.append({"step": "ask", "from": "query_model", "received": "invalid output", "issue": str(exc)})
            entry["outcome"] = "invalid_model_output"
            return self._fixed_reply()
        except Exception as exc:  # noqa: BLE001 - the model is an external service: missing key, network, rate limit
            trace.append({"step": "ask", "from": "query_model", "received": "error", "issue": type(exc).__name__})
            entry["outcome"] = "model_error"
            return {"kind": "error",
                    "text": "I couldn't reach the query model just now, so nothing was run. Try again in a moment; "
                            "if it keeps happening, check the model settings (A7_QUERY_MODEL, ANTHROPIC_API_KEY)."}
        entry["structured_query"] = parsed.to_dict()
        trace.append({"step": "ask", "from": "query_model", "received": parsed.type})
        if isinstance(parsed, structured_query.OffTopic):
            entry["outcome"] = "off_topic"
            return self._fixed_reply()

        # 2. Compile: every name checked against the catalogue; values bound as parameters.
        try:
            compiled = self.engine.compile(parsed)
        except cat.CatalogueError as exc:
            trace.append({"step": "compile", "issue": str(exc)})
            entry["outcome"] = "not_in_catalogue"
            return self._fixed_reply()
        entry["sql"] = compiled.sql
        trace.append({"step": "compile", "params": len(compiled.params)})

        # 3. Run: read-only, row limit and statement timeout. Rows return to the app only.
        try:
            result = self.executor.run(compiled.sql, compiled.params)
        except WriteRefused:
            entry["outcome"] = "write_refused"
            return self._fixed_reply()
        except QueryTimeout:
            trace.append({"step": "run", "issue": "statement timeout"})
            entry["outcome"] = "timeout"
            seconds = self.executor.statement_timeout_ms / 1000
            return {"kind": "error",
                    "text": f"That question took longer than {seconds:g} seconds, so I stopped it. "
                            "Try a narrower question, for example a shorter date range or one account."}
        except psycopg.Error as exc:
            trace.append({"step": "run", "issue": type(exc).__name__})
            entry["outcome"] = "db_error"
            return {"kind": "error",
                    "text": "I couldn't run that question against the reporting database. Try rewording it, "
                            "or try again in a moment."}
        rows = result.rows
        truncated = compiled.row_cap is not None and len(rows) > compiled.row_cap
        if truncated:
            rows = rows[: compiled.row_cap]
        entry["row_count"] = len(rows)
        trace.append({"step": "run", "rows_to": "app", "row_count": len(rows)})

        # 4. Phrase: the template sentence sees only the row count.
        sentence = formatter.template_sentence(len(rows))
        trace.append({"step": "phrase", "saw": "row_count"})
        self.store.append(conversation_id, message, parsed)
        entry["outcome"] = "truncated" if truncated else "answered"
        return {
            "kind": "answer",
            "columns": [{"key": c, "label": cat.label(self.catalogue, c)} for c in compiled.columns],
            "rows": [[_cell(v) for v in row] for row in rows],
            "sentence": sentence,
            "note": formatter.truncation_note(compiled.row_cap) if truncated and compiled.row_cap else None,
        }
