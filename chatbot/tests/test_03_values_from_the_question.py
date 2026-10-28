"""Ticket 03: values typed in the question reach the database as bound parameters."""
import psycopg

from a7chat.query_model import Recording
from conftest import rows_as_dicts


def by_account(answer, column):
    return {r["account.accountNumber"]: r[column] for r in rows_as_dicts(answer)}


def test_250_instead_of_100_returns_only_accounts_over_250(make_chat):
    answer = make_chat().ask("List all customers with a past due balance greater than $250")
    assert by_account(answer, "accountBalance.overdueBalance") == {"100101": 640.0, "100102": 275.5, "100106": 260.0, "100107": 510.0}


def test_an_account_number_in_the_question_returns_that_account(make_chat):
    answer = make_chat().ask("What is the balance for account 100102?")
    assert by_account(answer, "accountBalance.totalBalance") == {"100102": 373.7}


def test_a_service_address_in_the_question_returns_that_account(make_chat):
    answer = make_chat().ask("What does the account at 42 Maple Street owe?")
    [row] = rows_as_dicts(answer)
    assert row["account.accountNumber"] == "100102" and row["account.serviceAddress"] == "42 Maple Street"


def test_a_date_range_returns_rows_for_that_range_only(make_chat):
    chat = make_chat()
    one_day = {r["cashBatchData.cashierUsername"]: r["cashBatchData.tenderedAmount"]
               for r in rows_as_dicts(chat.ask("How much cash did each cashier take in on 14 September 2026?"))}
    three_days = {r["cashBatchData.cashierUsername"]: r["cashBatchData.tenderedAmount"]
                  for r in rows_as_dicts(chat.ask("How much cash did each cashier take in from 12 to 14 September 2026?"))}
    assert one_day == {"jlee": 425.0, "mokafor": 310.5}  # 15 Sep entries are excluded
    assert three_days == {"jlee": 425.0, "mokafor": 310.5, "srao": 135.25}


def test_typed_values_never_change_the_shape_of_the_sql(make_chat, database):
    hostile = "100102'; DELETE FROM pu_account; --"
    chat = make_chat([Recording(f"What is the balance for account {hostile}?", {
        "type": "query", "cube": "accountBalance",
        "measures": ["accountBalance.overdueBalance", "accountBalance.currentBalance", "accountBalance.totalBalance"],
        "dimensions": ["account.accountNumber", "account.name"],
        "filters": [{"member": "account.accountNumber", "operator": "equals", "values": [hostile]}],
    })])
    chat.ask("List all customers with a past due balance greater than $100")
    chat.ask("List all customers with a past due balance greater than $250")
    chat.ask("What is the balance for account 100102?")
    hostile_answer = chat.ask(f"What is the balance for account {hostile}?")

    u1, u250, account, injected = [line["sql"] for line in chat.log.lines()]
    assert u1 == u250
    assert account == injected
    assert "100" not in u1 and "250" not in u250 and hostile not in injected
    assert hostile_answer["rows"] == []
    with psycopg.connect(database.admin_url) as conn:
        assert conn.execute("SELECT count(*) FROM pu_account").fetchone()[0] == 47
