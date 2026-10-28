"""Ticket 05: one log line per request with no row data, and a check that prompts carry schema and question text only."""
import json

import pytest
import yaml

from a7chat import catalogue as cat
from a7chat import orchestrator, settings
from a7chat.conversation import Turn
from a7chat.query_model import PromptCheckFailed, build_prompt, check_prompt
from a7chat.request_log import FIELDS
from a7chat.structured_query import parse

APPROVED = yaml.safe_load(settings.APPROVED_QUESTIONS_PATH.read_text(encoding="utf-8"))


def run_every_case(chat):
    asked = []
    for case in APPROVED["cases"]:
        for turn in case["turns"]:
            asked.append(turn["question"])
            chat.ask(turn["question"], conversation_id=case["id"])
    return asked


def test_every_request_produces_exactly_one_log_line(make_chat):
    chat = make_chat()
    asked = run_every_case(chat)
    lines = chat.log.lines()

    assert [line["question"] for line in lines] == asked
    assert all(set(line) == set(FIELDS) for line in lines)
    answered = [line for line in lines if line["outcome"] == "answered"]
    assert answered and all(line["sql"] and line["row_count"] is not None and line["duration_ms"] >= 0 for line in answered)
    assert {line["catalogue_version"] for line in lines} == {cat.load()["version"]}


def test_no_log_line_contains_row_data(make_chat):
    chat = make_chat()
    run_every_case(chat)
    log_text = chat.log.path.read_text(encoding="utf-8")

    # Values a user typed (so they appear in some question or query) are not row data.
    typed = " ".join(line["question"] + json.dumps(line["structured_query"]) for line in chat.log.lines())
    cells = {str(value) for answer in chat.responses for row in answer.get("rows", []) for value in row}
    cells = {text for text in cells if len(text) >= 4 and text not in typed}
    assert {"Harbor View Bakery", "Elena Marsh", "Payment - Counter"} <= cells
    leaked = sorted(c for c in cells if c in log_text)
    assert leaked == []


def test_the_prompt_check_passes_for_every_request(make_chat):
    chat = make_chat()
    run_every_case(chat)
    assert {line["prompt_check"] for line in chat.log.lines()} == {"pass"}


@pytest.fixture
def valid_prompt():
    view = cat.model_view(cat.load())
    u1 = APPROVED["cases"][0]["turns"][0]
    turns = [Turn(u1["question"], parse(u1["structured_query"]))]
    return view, turns, build_prompt(view, "Only commercial accounts", turns)


def test_the_prompt_check_accepts_schema_and_question_text(valid_prompt):
    view, turns, prompt = valid_prompt
    check_prompt(prompt, catalogue_view=view, question="Only commercial accounts", turns=turns)
    assert "sql" not in json.dumps(prompt["catalogue"]).lower().replace("sql_", "")


@pytest.mark.parametrize("inject", ["extra key", "row in an earlier turn", "row in the question", "row in the catalogue"])
def test_the_prompt_check_fails_when_a_row_is_injected(valid_prompt, inject):
    view, turns, prompt = valid_prompt
    row = {"account.accountNumber": "100101", "account.name": "Harbor View Bakery", "accountBalance.overdueBalance": 640.0}
    if inject == "extra key":
        prompt["rows"] = [row]
    elif inject == "row in an earlier turn":
        prompt["earlier_turns"][0]["rows"] = [row]
    elif inject == "row in the question":
        prompt["question"] += " " + json.dumps(row)
    else:
        prompt["catalogue"] = {**prompt["catalogue"], "sample_rows": [row]}
    with pytest.raises(PromptCheckFailed):
        check_prompt(prompt, catalogue_view=view, question="Only commercial accounts", turns=turns)


def test_a_prompt_that_fails_the_check_is_never_sent(make_chat, monkeypatch):
    real_build = orchestrator.build_prompt

    def leaky_build(*args, **kwargs):
        prompt = real_build(*args, **kwargs)
        prompt["earlier_turns"].append({"question": "x", "structured_query": {}, "rows": [["Harbor View Bakery"]]})
        return prompt

    monkeypatch.setattr(orchestrator, "build_prompt", leaky_build)
    chat = make_chat()
    answer = chat.ask("List all customers with a past due balance greater than $100")

    assert answer["kind"] == "fixed_reply"
    assert chat.model.prompts == []
    [line] = chat.log.lines()
    assert line["prompt_check"].startswith("fail")


def test_the_trace_shows_a_structured_query_leaving_the_model_and_rows_returning_to_the_app_only(make_chat):
    chat = make_chat()
    chat.ask("List all customers with a past due balance greater than $100")
    [line] = chat.log.lines()

    steps = line["trace"]
    assert steps[0] == {"step": "ask", "to": "query_model", "sent": ["catalogue", "earlier_turns", "question", "today"], "earlier_turns": 0}
    assert steps[1] == {"step": "ask", "from": "query_model", "received": "query"}
    run = next(s for s in steps if s["step"] == "run")
    assert run == {"step": "run", "rows_to": "app", "row_count": 6}
    assert not any(s.get("to") == "query_model" for s in steps[1:])
