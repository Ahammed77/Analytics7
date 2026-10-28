"""Text-to-SQL engine: structured query + catalogue -> read-only Postgres SQL with bound parameters.

Every name is checked against the catalogue. Each cube becomes a subquery that
projects the members the query needs from the cube's own SQL; cubes are joined
only along joins the catalogue defines from the primary cube. Values from the
question are always parameters, so they can never change the shape of the SQL.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from .catalogue import CatalogueError
from .structured_query import StructuredQuery, is_date

AGGREGATES = {"sum": "SUM({})", "avg": "AVG({})", "min": "MIN({})", "max": "MAX({})", "count_distinct": "COUNT(DISTINCT {})"}
COMPARISONS = {"gt": ">", "gte": ">=", "lt": "<", "lte": "<="}


@dataclass(frozen=True)
class CompiledQuery:
    sql: str
    params: tuple
    columns: tuple[str, ...]      # member names, in select order
    row_cap: int | None           # the row limit, when it (not the user) bounds the result


def _q(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _escape(fragment: str) -> str:
    # Catalogue SQL is spliced into a psycopg query string, where % marks a placeholder.
    return fragment.replace("%", "%%")


class Engine:
    def __init__(self, catalogue: dict[str, Any], row_limit: int):
        self.catalogue = catalogue
        self.row_limit = row_limit

    def _member(self, name: str, primary: str) -> dict[str, Any]:
        cube_name, _, _ = name.partition(".")
        cube = self.catalogue["cubes"].get(cube_name)
        member = cube["members"].get(name) if cube else None
        if member is None:
            raise CatalogueError(f"{name} is not in the catalogue")
        if not member["public"]:
            raise CatalogueError(f"{name} is not available to questions")
        if not member["resolved"]:
            raise CatalogueError(f"{name} is unresolved: {member['issue']}")
        if cube_name != primary and cube_name not in self.catalogue["cubes"][primary]["joins"]:
            raise CatalogueError(f"{cube_name} cannot be joined from {primary}")
        return member

    def compile(self, query: StructuredQuery) -> CompiledQuery:
        primary = query.cube
        if primary not in self.catalogue["cubes"]:
            raise CatalogueError(f"cube {primary} is not in the catalogue")
        members = {name: self._member(name, primary) for name in query.members()}
        for name in query.measures:
            if members[name]["kind"] != "measure":
                raise CatalogueError(f"{name} is not a measure")
        for name in query.dimensions:
            if members[name]["kind"] != "dimension":
                raise CatalogueError(f"{name} is not a dimension")
        td = query.timeDimension
        if td and members[td.member]["type"] != "time":
            raise CatalogueError(f"{td.member} is not a time dimension")

        # Members each cube subquery must project: the ones used, plus join keys.
        needed: dict[str, set[str]] = {primary: set()}
        for name in members:
            cube_name = name.split(".", 1)[0]
            needed.setdefault(cube_name, set()).add(name)
        joined = [c for c in needed if c != primary]
        for target in joined:
            on = self.catalogue["cubes"][primary]["joins"][target]["on"]
            for cube_name in (primary, target):
                for key in self.catalogue["cubes"][cube_name]["members"]:
                    if f'{_q(cube_name)}.{_q(key.split(".", 1)[1])}' in on:
                        needed[cube_name].add(key)

        def ref(name: str) -> str:
            cube_name, short = name.split(".", 1)
            return f"{_q(cube_name)}.{_q(short)}"

        def subquery(cube_name: str) -> str:
            cube = self.catalogue["cubes"][cube_name]
            projections = [
                f"{_escape(cube['members'][m]['sql'])} AS {_q(m.split('.', 1)[1])}"
                for m in sorted(needed[cube_name])
                if cube["members"][m]["sql"]  # count measures have no column
            ] or ["1 AS one"]
            return f"(SELECT {', '.join(projections)} FROM ({_escape(cube['source_sql'])}) AS src) AS {_q(cube_name)}"

        def measure_expr(name: str) -> str:
            member = members[name]
            if member["type"] == "count":
                return "COUNT(*)"
            return AGGREGATES[member["type"]].format(ref(name))

        # WHERE comes before HAVING in the SQL, so each clause keeps its own parameters.
        where_params: list[Any] = []
        having_params: list[Any] = []
        select, group_by, where, having, columns = [], [], [], [], []

        for name in query.dimensions:
            select.append(f"{ref(name)} AS {_q(name)}")
            group_by.append(ref(name))
            columns.append(name)
        if td and td.granularity:
            expr = f"date_trunc('{td.granularity}', {ref(td.member)})"
            select.append(f"{expr} AS {_q(td.member)}")
            group_by.append(expr)
            columns.append(td.member)
        for name in query.measures:
            select.append(f"{measure_expr(name)} AS {_q(name)}")
            columns.append(name)

        for f in query.filters:
            member = members[f.member]
            if member["kind"] == "measure":
                having.append(self._condition(measure_expr(f.member), member, f.operator, f.values, having_params))
            else:
                where.append(self._condition(ref(f.member), member, f.operator, f.values, where_params))
        if td and td.dateRange:
            where.append(f"{ref(td.member)} >= %s::date AND {ref(td.member)} < %s::date + 1")
            where_params.extend(td.dateRange)

        sql = f"SELECT {', '.join(select)} FROM {subquery(primary)}"
        for target in joined:
            on = self.catalogue["cubes"][primary]["joins"][target]["on"]
            sql += f" LEFT JOIN {subquery(target)} ON {_escape(on)}"
        if where:
            sql += " WHERE " + " AND ".join(where)
        if (query.measures or having) and group_by:
            sql += " GROUP BY " + ", ".join(group_by)
        if having:
            sql += " HAVING " + " AND ".join(having)

        order = []
        for o in query.order:
            if o.member not in columns:
                raise CatalogueError(f"cannot order by {o.member}: it is not in the result")
            order.append(f"{_q(o.member)} {o.direction.upper()}")
        order += [f"{_q(c)} ASC" for c in columns if c not in {o.member for o in query.order}]
        sql += " ORDER BY " + ", ".join(order)

        if query.limit is not None and query.limit <= self.row_limit:
            fetch, cap = query.limit, None
        else:
            fetch, cap = self.row_limit + 1, self.row_limit  # one extra row shows the cap was hit
        sql += f" LIMIT {fetch}"
        return CompiledQuery(sql=sql, params=tuple(where_params + having_params), columns=tuple(columns), row_cap=cap)

    @staticmethod
    def _value(member: dict[str, Any], value: Any) -> Any:
        if member["kind"] == "measure" or member["type"] == "number":
            try:
                return Decimal(str(value).replace("$", "").replace(",", "").strip())
            except InvalidOperation as exc:
                raise CatalogueError(f"{value!r} is not a number") from exc
        return str(value)

    def _condition(self, expr: str, member: dict[str, Any], operator: str, values: tuple, params: list) -> str:
        if operator == "set":
            return f"{expr} IS NOT NULL"
        if operator == "notSet":
            return f"{expr} IS NULL"
        if operator == "contains":
            if member["kind"] != "dimension" or member["type"] != "string":
                raise CatalogueError(f"contains only applies to text, not {member['title']}")
            needle = str(values[0]).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            params.append(f"%{needle}%")
            return f"{expr} ILIKE %s"
        if member["type"] == "time":
            if operator in ("equals", "notEquals"):
                raise CatalogueError("use a date range or a comparison for dates")
            if not is_date(values[0]):
                raise CatalogueError(f"{values[0]!r} is not a real date")
            params.append(str(values[0]))
            return f"{expr} {COMPARISONS[operator]} %s::date"
        if operator in ("equals", "notEquals"):
            params.append([self._value(member, v) for v in values])
            return f"{expr} = ANY(%s)" if operator == "equals" else f"NOT ({expr} = ANY(%s))"
        params.append(self._value(member, values[0]))
        return f"{expr} {COMPARISONS[operator]} %s"
