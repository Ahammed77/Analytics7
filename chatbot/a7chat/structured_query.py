"""The structured query: the only thing the query model may return.

Format (fixed in ticket 01; Kyi to confirm before M2):

    {"type": "query",
     "cube": "accountBalance",                          # primary cube
     "measures": ["accountBalance.overdueBalance"],
     "dimensions": ["account.accountNumber", "account.name"],
     "filters": [{"member": "accountBalance.overdueBalance", "operator": "gt", "values": ["100"]}],
     "timeDimension": {"member": "cashDetail.runDate", "dateRange": ["2026-01-08", "2026-01-08"],
                       "granularity": null},            # or null
     "order": [{"member": "accountBalance.overdueBalance", "direction": "desc"}],
     "limit": null}

or, for anything that is not a question about the user's CIS data:

    {"type": "off_topic", "reason": "weather"}

Values typed in the question (accounts, addresses, dates, amounts) go into
filters and timeDimension. They never become SQL text; the engine binds them.
Optional keys may be left out; unknown keys make the query invalid.
"""
from __future__ import annotations

import re
from datetime import date
from dataclasses import asdict, dataclass, field
from typing import Any

OPERATORS = ("equals", "notEquals", "contains", "gt", "gte", "lt", "lte", "set", "notSet")
GRANULARITIES = ("day", "week", "month", "quarter", "year")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
QUERY_KEYS = {"type", "cube", "measures", "dimensions", "filters", "timeDimension", "order", "limit", "reason"}


class InvalidStructuredQuery(Exception):
    pass


def is_date(value: Any) -> bool:
    """A real calendar date written YYYY-MM-DD (so 2026-02-30 is not one)."""
    if not (isinstance(value, str) and DATE.match(value)):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


@dataclass(frozen=True)
class Filter:
    member: str
    operator: str
    values: tuple = ()


@dataclass(frozen=True)
class TimeDimension:
    member: str
    dateRange: tuple[str, str] | None = None
    granularity: str | None = None


@dataclass(frozen=True)
class Order:
    member: str
    direction: str = "asc"


@dataclass(frozen=True)
class StructuredQuery:
    cube: str
    measures: tuple[str, ...] = ()
    dimensions: tuple[str, ...] = ()
    filters: tuple[Filter, ...] = ()
    timeDimension: TimeDimension | None = None
    order: tuple[Order, ...] = ()
    limit: int | None = None
    type: str = field(default="query")

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        for f in data["filters"]:
            f["values"] = list(f["values"])
        if data["timeDimension"] and data["timeDimension"]["dateRange"]:
            data["timeDimension"]["dateRange"] = list(data["timeDimension"]["dateRange"])
        for key in ("measures", "dimensions", "filters", "order"):
            data[key] = list(data[key])
        return data

    def members(self) -> list[str]:
        names = list(self.measures) + list(self.dimensions)
        names += [f.member for f in self.filters] + [o.member for o in self.order]
        if self.timeDimension:
            names.append(self.timeDimension.member)
        return names


@dataclass(frozen=True)
class OffTopic:
    reason: str = "off_topic"
    type: str = field(default="off_topic")

    def to_dict(self) -> dict[str, Any]:
        return {"type": "off_topic", "reason": self.reason}


def _str_list(data: dict, key: str) -> tuple[str, ...]:
    value = data.get(key) or []
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise InvalidStructuredQuery(f"{key} must be a list of names")
    return tuple(value)


def parse(data: Any) -> StructuredQuery | OffTopic:
    """Validate the model's output. Anything other than one query or off_topic is rejected."""
    if not isinstance(data, dict):
        raise InvalidStructuredQuery("output is not an object")
    extra = set(data) - QUERY_KEYS
    if extra:
        raise InvalidStructuredQuery(f"unexpected keys: {sorted(extra)}")
    kind = data.get("type")
    if kind == "off_topic":
        return OffTopic(reason=str(data.get("reason") or "off_topic"))
    if kind != "query":
        raise InvalidStructuredQuery(f"type must be query or off_topic, got {kind!r}")
    if not isinstance(data.get("cube"), str):
        raise InvalidStructuredQuery("cube is required")

    filters = []
    for item in data.get("filters") or []:
        if not isinstance(item, dict) or set(item) - {"member", "operator", "values"}:
            raise InvalidStructuredQuery("bad filter")
        if item.get("operator") not in OPERATORS:
            raise InvalidStructuredQuery(f"unknown operator {item.get('operator')!r}")
        values = item.get("values") or []
        if not isinstance(values, list) or not all(isinstance(v, (str, int, float)) and not isinstance(v, bool) for v in values):
            raise InvalidStructuredQuery("filter values must be strings or numbers")
        if item["operator"] not in ("set", "notSet") and not values:
            raise InvalidStructuredQuery(f"filter on {item.get('member')} has no values")
        filters.append(Filter(str(item.get("member")), item["operator"], tuple(values)))

    time_dim = None
    td = data.get("timeDimension")
    if td is not None:
        if not isinstance(td, dict) or set(td) - {"member", "dateRange", "granularity"} or not isinstance(td.get("member"), str):
            raise InvalidStructuredQuery("bad timeDimension")
        date_range = td.get("dateRange")
        if date_range is not None:
            if not (isinstance(date_range, list) and len(date_range) == 2 and all(is_date(d) for d in date_range)):
                raise InvalidStructuredQuery("dateRange must be two real YYYY-MM-DD dates")
            if date_range[0] > date_range[1]:
                raise InvalidStructuredQuery("dateRange starts after it ends")
            date_range = tuple(date_range)
        if td.get("granularity") not in (None, *GRANULARITIES):
            raise InvalidStructuredQuery(f"unknown granularity {td.get('granularity')!r}")
        time_dim = TimeDimension(td["member"], date_range, td.get("granularity"))

    order = []
    for item in data.get("order") or []:
        if not isinstance(item, dict) or set(item) - {"member", "direction"} or item.get("direction", "asc") not in ("asc", "desc"):
            raise InvalidStructuredQuery("bad order")
        order.append(Order(str(item.get("member")), item.get("direction", "asc")))

    limit = data.get("limit")
    if limit is not None and (not isinstance(limit, int) or isinstance(limit, bool) or limit < 1):
        raise InvalidStructuredQuery("limit must be a positive integer")

    query = StructuredQuery(
        cube=data["cube"],
        measures=_str_list(data, "measures"),
        dimensions=_str_list(data, "dimensions"),
        filters=tuple(filters),
        timeDimension=time_dim,
        order=tuple(order),
        limit=limit,
    )
    if not query.measures and not query.dimensions and not (time_dim and time_dim.granularity):
        raise InvalidStructuredQuery("query selects nothing")
    return query


# JSON schema handed to the real query model (structured outputs). Every key is
# required there, with null for "not used"; parse() accepts that form too.
_NAME_LIST = {"type": "array", "items": {"type": "string"}}
JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["type", "reason", "cube", "measures", "dimensions", "filters", "timeDimension", "order", "limit"],
    "properties": {
        "type": {"type": "string", "enum": ["query", "off_topic"]},
        "reason": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "cube": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "measures": _NAME_LIST,
        "dimensions": _NAME_LIST,
        "filters": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["member", "operator", "values"],
                "properties": {
                    "member": {"type": "string"},
                    "operator": {"type": "string", "enum": list(OPERATORS)},
                    "values": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "timeDimension": {
            "anyOf": [
                {"type": "null"},
                {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["member", "dateRange", "granularity"],
                    "properties": {
                        "member": {"type": "string"},
                        "dateRange": {"anyOf": [{"type": "null"}, {"type": "array", "items": {"type": "string", "format": "date"}}]},
                        "granularity": {"anyOf": [{"type": "null"}, {"type": "string", "enum": list(GRANULARITIES)}]},
                    },
                },
            ]
        },
        "order": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["member", "direction"],
                "properties": {"member": {"type": "string"}, "direction": {"type": "string", "enum": ["asc", "desc"]}},
            },
        },
        "limit": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
    },
}


def from_model_output(data: dict[str, Any]) -> StructuredQuery | OffTopic:
    """Drop the nulls the model must send for unused keys, then parse."""
    if isinstance(data, dict):
        data = {k: v for k, v in data.items() if v is not None}
    return parse(data)
