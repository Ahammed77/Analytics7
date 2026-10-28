"""Ticket 01: one question end to end through the message endpoint."""
from conftest import rows_as_dicts

U1 = "List all customers with a past due balance greater than $100"


def test_past_due_question_returns_the_expected_accounts_as_a_table(make_chat):
    chat = make_chat()
    answer = chat.ask(U1)

    assert answer["kind"] == "answer"
    got = {r["account.accountNumber"]: r["accountBalance.overdueBalance"] for r in rows_as_dicts(answer)}
    assert got == {"100101": 640.0, "100102": 275.5, "100103": 180.25, "100104": 120.0, "100106": 260.0, "100107": 510.0}
    assert answer["sentence"] == "Found 6 rows for your question."
    assert [c["label"] for c in answer["columns"]][:2] == ["Account Number", "Account Name"]


def test_the_answer_has_no_chart_only_a_table_and_a_sentence(make_chat):
    answer = make_chat().ask(U1)
    assert set(answer) == {"conversation_id", "kind", "columns", "rows", "sentence", "note"}


def test_the_same_question_gives_the_same_answer_with_no_cis7_page_context(make_chat):
    chat = make_chat()
    first = chat.ask(U1, conversation_id="a")
    second = chat.ask(U1, conversation_id="b")
    assert first["rows"] == second["rows"]


def test_query_model_gets_question_and_catalogue_only_and_returns_one_structured_query(make_chat):
    chat = make_chat()
    chat.ask(U1)

    [prompt] = chat.model.prompts
    assert set(prompt) == {"today", "catalogue", "earlier_turns", "question"}
    assert prompt["question"] == U1
    assert prompt["earlier_turns"] == []
    [line] = chat.log.lines()
    assert line["structured_query"]["type"] == "query"
