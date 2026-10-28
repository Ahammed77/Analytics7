"""Read-only executor owned by the application. Rows come back to the app and go nowhere else.

Three layers keep it read-only: anything that is not a single SELECT is refused
before a connection is opened; the transaction is READ ONLY; and the DSN is the
read-only role from db/roles.sql. Every statement runs under a statement timeout.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import psycopg

SINGLE_SELECT = re.compile(r"^\s*SELECT\b", re.IGNORECASE)


class WriteRefused(Exception):
    """The SQL was not a single read-only SELECT; it never reached the database."""


class QueryTimeout(Exception):
    pass


@dataclass(frozen=True)
class Result:
    columns: tuple[str, ...]
    rows: list[tuple]


def assert_read_only(sql: str) -> None:
    if not SINGLE_SELECT.match(sql) or ";" in sql:
        raise WriteRefused("only a single SELECT statement may run")


class Executor:
    def __init__(self, dsn: str, statement_timeout_ms: int):
        self.dsn = dsn
        self.statement_timeout_ms = int(statement_timeout_ms)

    def run(self, sql: str, params: tuple[Any, ...] = ()) -> Result:
        assert_read_only(sql)
        try:
            with psycopg.connect(self.dsn) as conn:
                conn.read_only = True
                with conn.transaction():
                    conn.execute(f"SET LOCAL statement_timeout = {self.statement_timeout_ms}")
                    cur = conn.execute(sql, params)
                    columns = tuple(d.name for d in cur.description or ())
                    return Result(columns, cur.fetchall())
        except psycopg.errors.QueryCanceled as exc:
            raise QueryTimeout(str(exc)) from exc
