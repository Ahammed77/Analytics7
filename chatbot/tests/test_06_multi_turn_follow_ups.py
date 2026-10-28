"""Ticket 06: follow-ups build on earlier turns; the store keeps questions and queries, never rows."""
import json
from dataclasses import fields

import pytest

from a7chat.conversation import ConversationStore, Turn
from conftest import rows_as_dicts

U1 = "List all customers with a past due balance greater than $100"


def accounts(answer):
    return sorted(r["account.accountNumber"] for r in rows_as_dicts(answer))


def test_each_follow_up_builds_on_the_turn_before(make_chat):
    chat = make_chat()
    assert accounts(chat.ask(U1)) == ["100101", "100102", "100103", "100104", "100106", "100107"]
    assert accounts(chat.ask("Only commercial accounts")) == ["100101", "100103", "100107"]
    assert accounts(chat.ask("And only those over $500")) == ["100101", "100107"]

    first, second, third = chat.model.prompts
    assert first["earlier_turns"] == []
    assert [t["question"] for t in second["earlier_turns"]] == [U1]
    assert [t["question"] for t in third["earlier_turns"]] == [U1, "Only commercial accounts"]
    assert third["earlier_turns"][1]["structured_query"]["filters"][1]["values"] == ["COM"]


def test_follow_ups_match_whatever_the_case_of_the_earlier_question(make_chat):
    chat = make_chat()
    chat.ask(U1.upper())
    assert accounts(chat.ask("only commercial accounts")) == ["100101", "100103", "100107"]


def test_a_follow_up_without_its_earlier_turns_is_not_answered(make_chat):
    assert make_chat().ask("Only commercial accounts", conversation_id="fresh")["kind"] == "fixed_reply"


def test_an_unrelated_question_in_the_same_conversation_returns_its_own_answer(make_chat):
    chat = make_chat()
    chat.ask(U1)
    chat.ask("Only commercial accounts")
    answer = chat.ask("How many calls of each type were logged in 2025?")
    assert {r["callTypeAnalysis.callType"]: r["callTypeAnalysis.totalCalls"] for r in rows_as_dicts(answer)} == {
        "BILLQ": 4, "MOVEIN": 5, "RECON": 3}


def test_the_store_holds_questions_and_queries_only(make_chat):
    chat = make_chat()
    for question in (U1, "Only commercial accounts", "What's the weather?", "And only those over $500"):
        chat.ask(question)
    turns = chat.store.turns(chat.conversation_id)

    assert [f.name for f in fields(Turn)] == ["question", "structured_query"]
    assert [t.question for t in turns] == [U1, "Only commercial accounts", "And only those over $500"]
    stored = json.dumps([t.to_prompt() for t in turns])
    assert "Harbor View Bakery" not in stored and "640" not in stored
    with pytest.raises(TypeError):
        ConversationStore().append("c", "q", {"rows": [["Harbor View Bakery"]]})


def test_earlier_turns_sent_to_the_query_model_contain_no_rows(make_chat):
    chat = make_chat()
    for question in (U1, "Only commercial accounts", "And only those over $500"):
        chat.ask(question)
    sent = json.dumps([p["earlier_turns"] for p in chat.model.prompts])
    for value in ("Harbor View Bakery", "Pinecrest Dental", "640", "180.25"):
        assert value not in sent
    assert all(set(t) == {"question", "structured_query"} for p in chat.model.prompts for t in p["earlier_turns"])
