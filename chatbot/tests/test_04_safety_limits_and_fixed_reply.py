"""Ticket 04: no names outside the catalogue, no writes, row limit and statement timeout."""
import copy

import psycopg
import pytest

from a7chat import catalogue as cat
from a7chat.executor import Executor, WriteRefused
from a7chat.query_model import Recording

FIXED_REPLY_START = "I can only answer questions about your CIS data"


def count_accounts(database):
    with psycopg.connect(database.admin_url) as conn:
        return conn.execute("SELECT count(*) FROM pu_account").fetchone()[0]


def test_a_made_up_measure_name_gets_the_fixed_reply_and_no_sql_runs(make_chat):
    chat = make_chat([Recording("What is the average meter reading per account?", {
        "type": "query", "cube": "accountBalance",
        "measures": ["accountBalance.averageMeterReading"], "dimensions": ["account.accountNumber"],
    })])
    answer = chat.ask("What is the average meter reading per account?")

    assert answer["kind"] == "fixed_reply" and answer["text"].startswith(FIXED_REPLY_START)
    assert answer["suggestions"]
    assert chat.executor.statements == []
    [line] = chat.log.lines()
    assert line["sql"] is None and line["outcome"] == "not_in_catalogue"


def test_a_member_hidden_from_questions_is_refused_too(make_chat):
    chat = make_chat([Recording("Show occupant codes", {
        "type": "query", "cube": "account", "dimensions": ["account.occupantCode"]})])
    assert chat.ask("Show occupant codes")["kind"] == "fixed_reply"
    assert chat.executor.statements == []


def test_delete_all_accounts_is_refused_and_no_write_reaches_the_database(make_chat, database):
    before = count_accounts(database)
    chat = make_chat()
    answer = chat.ask("Delete all accounts")

    assert answer["kind"] == "fixed_reply"
    assert chat.executor.statements == []
    assert count_accounts(database) == before


def test_model_output_that_tries_to_carry_sql_is_rejected(make_chat, database):
    chat = make_chat([Recording("Remove the closed accounts", {
        "type": "query", "cube": "account", "dimensions": ["account.name"], "sql": "DELETE FROM pu_account"})])
    assert chat.ask("Remove the closed accounts")["kind"] == "fixed_reply"
    assert chat.executor.statements == []
    assert count_accounts(database) == 47


def test_the_executor_refuses_anything_but_a_single_select_before_connecting():
    executor = Executor("postgresql://nobody@127.0.0.1:1/none", 1000)  # unreachable: refusal must come first
    for sql in ("DELETE FROM pu_account", "SELECT 1; DELETE FROM pu_account", "  update pu_account set name = 'x'",
                "WITH x AS (DELETE FROM pu_account RETURNING *) SELECT * FROM x"):
        with pytest.raises(WriteRefused):
            executor.run(sql)


def test_the_database_role_itself_is_read_only(database):
    with psycopg.connect(database.reader_url) as conn:
        with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
            conn.execute("DELETE FROM pu_account")


def test_a_result_larger_than_the_row_limit_is_cut_at_the_limit_with_a_note(make_chat):
    chat = make_chat(row_limit=4)
    answer = chat.ask("List all customers with a past due balance greater than $100")  # 6 matching rows

    assert len(answer["rows"]) == 4
    assert answer["note"] == "Showing the first 4 rows; there are more. Narrow your question to see the rest."
    assert chat.log.lines()[0]["outcome"] == "truncated"


def test_a_result_within_the_row_limit_has_no_note(make_chat):
    answer = make_chat(row_limit=6).ask("List all customers with a past due balance greater than $100")
    assert len(answer["rows"]) == 6 and answer["note"] is None


def test_a_query_past_the_timeout_stops_with_a_clear_message(make_chat):
    slow = copy.deepcopy(cat.load())
    slow["cubes"]["account"]["members"]["account.slowName"] = {
        **slow["cubes"]["account"]["members"]["account.name"],
        "sql": "(SELECT name FROM (SELECT pg_sleep(0.2)) AS pause)",  # 0.2s per row, 47 rows
    }
    chat = make_chat([Recording("List every account name slowly", {
        "type": "query", "cube": "account", "dimensions": ["account.slowName"]})],
        catalogue=slow, statement_timeout_ms=300)
    answer = chat.ask("List every account name slowly")

    assert answer["kind"] == "error"
    assert answer["text"].startswith("That question took longer than 0.3 seconds, so I stopped it.")
    assert chat.log.lines()[0]["outcome"] == "timeout"


class BrokenModel:
    def __init__(self):
        self.prompts = []

    def ask(self, prompt):
        raise ConnectionError("no route to the model")


def test_a_query_model_failure_gives_a_clear_message_not_a_server_error(make_chat):
    chat = make_chat()
    chat.client.app.state.orchestrator.query_model = BrokenModel()
    answer = chat.ask("List all customers with a past due balance greater than $100")

    assert answer["kind"] == "error"
    assert answer["text"].startswith("I couldn't reach the query model just now")
    assert chat.executor.statements == []
    [line] = chat.log.lines()
    assert line["outcome"] == "model_error" and line["sql"] is None


def test_schema_valid_but_impossible_queries_get_the_fixed_reply_and_no_sql(make_chat):
    impossible = {
        "Cash receipts for 30 February 2026": {
            "type": "query", "cube": "cashDetail", "measures": ["cashDetail.transactionAmount"],
            "timeDimension": {"member": "cashDetail.runDate", "dateRange": ["2026-02-30", "2026-03-01"]}},
        "Cash receipts from March back to January": {
            "type": "query", "cube": "cashDetail", "measures": ["cashDetail.transactionAmount"],
            "timeDimension": {"member": "cashDetail.runDate", "dateRange": ["2026-03-01", "2026-01-01"]}},
        "Overdue balances containing 10": {
            "type": "query", "cube": "accountBalance", "measures": ["accountBalance.overdueBalance"],
            "dimensions": ["account.accountNumber"],
            "filters": [{"member": "accountBalance.overdueBalance", "operator": "contains", "values": ["10"]}]},
        "Receipts on exactly 8 January 2026": {
            "type": "query", "cube": "cashDetail", "measures": ["cashDetail.transactionAmount"],
            "filters": [{"member": "cashDetail.runDate", "operator": "equals", "values": ["2026-01-08"]}]},
        "Receipts after the 31st of February": {
            "type": "query", "cube": "cashDetail", "measures": ["cashDetail.transactionAmount"],
            "filters": [{"member": "cashDetail.runDate", "operator": "gt", "values": ["2026-02-31"]}]},
    }
    chat = make_chat([Recording(q, sq) for q, sq in impossible.items()])
    for question in impossible:
        assert chat.ask(question)["kind"] == "fixed_reply", question
    assert chat.executor.statements == []


class FailingExecutor(Executor):
    def run(self, sql, params=()):
        raise psycopg.OperationalError("connection refused")


def test_a_database_failure_gives_a_clear_message_not_a_server_error(make_chat):
    chat = make_chat()
    chat.client.app.state.orchestrator.executor = FailingExecutor("postgresql://unused", 1000)
    answer = chat.ask("List all customers with a past due balance greater than $100")

    assert answer["kind"] == "error"
    assert answer["text"].startswith("I couldn't run that question against the reporting database")
    [line] = chat.log.lines()
    assert line["outcome"] == "db_error"
