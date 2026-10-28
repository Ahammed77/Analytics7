"""Semantic catalogue: generated from the Cube YAML definitions plus a chatbot overlay.

The catalogue is the one source of truth for the query model (names, labels,
descriptions, synonyms) and for the engine (SQL, joins). Cube SQL is written for
MS SQL; the generator translates the constructs the in-scope cubes use into
Postgres and marks anything it cannot translate as unresolved, with a reason.
Unresolved members stay in the catalogue (reported, not dropped) but the engine
refuses to use them.

    python -m a7chat.catalogue generate   # writes catalogue/catalogue.json
    python -m a7chat.catalogue check      # schema check + probe every member on the DB
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml

from . import settings

MEMBER_REF = re.compile(r"\{(CUBE|[A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)\}|\{CUBE\}\.([A-Za-z_][A-Za-z0-9_]*)")
MSSQL_ONLY = re.compile(r"\b(dateadd|datediff|datepart|iif|isnull|getdate|convert|len|charindex)\s*\(", re.IGNORECASE)
MEASURE_TYPES = {"sum", "avg", "count", "count_distinct", "min", "max"}
DIMENSION_TYPES = {"string", "number", "time", "boolean"}


class CatalogueError(Exception):
    """A structured query named something the catalogue does not allow."""


# ---------------------------------------------------------------- MS SQL -> Postgres

def _split_args(text: str, start: int) -> tuple[list[str], int]:
    """Split the comma-separated arguments of a call whose '(' is at text[start-1]."""
    depth, i = 0, start
    args: list[str] = []
    current: list[str] = []
    while i < len(text):
        ch = text[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            if depth == 0:
                args.append("".join(current).strip())
                return args, i + 1
            depth -= 1
        elif ch == "," and depth == 0:
            args.append("".join(current).strip())
            current = []
            i += 1
            continue
        current.append(ch)
        i += 1
    raise ValueError("unbalanced parentheses")


def _rewrite_calls(sql: str, name: str, rewrite) -> str:
    pattern = re.compile(rf"\b{name}\s*\(", re.IGNORECASE)
    while (match := pattern.search(sql)) is not None:
        args, end = _split_args(sql, match.end())
        sql = sql[: match.start()] + rewrite(args) + sql[end:]
    return sql


def _dateadd(args: list[str]) -> str:
    # dateadd(unit, datediff(unit, 0, x), 0) is the MS SQL idiom for truncating to a unit.
    inner = re.fullmatch(r"datediff\s*\((.*)\)", args[1], re.IGNORECASE | re.DOTALL) if len(args) == 3 else None
    if inner and args[2] == "0":
        unit, zero, value = _split_args(inner.group(1) + ")", 0)[0]
        if unit.lower() == args[0].lower() and zero == "0":
            return f"date_trunc('{unit.lower()}', {value})"
    raise ValueError("dateadd form not supported")


def squash_whitespace(sql: str) -> str:
    """Collapse runs of whitespace to one space, leaving quoted string literals alone."""
    parts = re.split(r"('(?:[^']|'')*')", sql)
    return "".join(part if part.startswith("'") else re.sub(r"\s+", " ", part) for part in parts).strip()


def translate_sql(sql: str) -> str:
    """Translate the MS SQL constructs used by the Cube YAMLs into Postgres."""
    sql = squash_whitespace(sql)
    sql = _rewrite_calls(sql, "dateadd", _dateadd)
    sql = _rewrite_calls(sql, "iif", lambda a: f"CASE WHEN {a[0]} THEN {a[1]} ELSE {a[2]} END")
    sql = _rewrite_calls(sql, "datepart", lambda a: f"EXTRACT({a[0].upper()} FROM {a[1]})")
    if MSSQL_ONLY.search(sql):
        raise ValueError(f"untranslated MS SQL function in: {sql}")
    return sql


# ---------------------------------------------------------------- generation

def _load_cubes(yaml_dir: Path) -> tuple[dict[str, dict], dict[str, str]]:
    cubes, hashes = {}, {}
    for path in sorted(yaml_dir.glob("*.yml")):
        text = path.read_text(encoding="utf-8")
        hashes[path.name] = hashlib.sha256(text.encode()).hexdigest()[:12]
        for cube in (yaml.safe_load(text) or {}).get("cubes", []):
            cubes[cube["name"]] = cube
    return cubes, hashes


def _resolve_extends(name: str, raw: dict[str, dict]) -> dict:
    cube = copy.deepcopy(raw[name])
    parent_name = cube.pop("extends", None)
    if not parent_name:
        return cube
    parent = _resolve_extends(parent_name, raw)
    for key in ("dimensions", "measures", "joins"):
        merged = {m["name"]: m for m in parent.get(key, [])}
        merged.update({m["name"]: m for m in cube.get(key, [])})
        cube[key] = list(merged.values())
    for key in ("sql", "sql_table"):
        if key not in cube and key in parent:
            cube[key] = parent[key]
    return cube


def _member_sql(cube_name: str, member: dict, by_name: dict[str, dict], seen: tuple = ()) -> str:
    """Expand {CUBE.x} / {CUBE}.x references into the referenced member's SQL."""
    if member["name"] in seen:
        raise ValueError("circular member reference")
    sql = member.get("sql")
    if sql is None:
        if member.get("type") == "count":
            return ""
        raise ValueError("member has no sql")

    def expand(match: re.Match) -> str:
        cube_ref, ref = (match.group(1), match.group(2)) if match.group(2) else ("CUBE", match.group(3))
        if cube_ref not in ("CUBE", cube_name):
            raise ValueError(f"references another cube ({cube_ref}.{ref}); cross-cube members are not supported")
        if ref not in by_name:
            raise ValueError(f"references unknown member {ref}")
        return f"({_member_sql(cube_name, by_name[ref], by_name, seen + (member['name'],))})"

    return translate_sql(MEMBER_REF.sub(expand, str(sql)))


def _join_on(cube_name: str, sql: str) -> str:
    def quote(match: re.Match) -> str:
        cube_ref = cube_name if match.group(1) == "CUBE" else match.group(1)
        return f'"{cube_ref}"."{match.group(2)}"'

    return MEMBER_REF.sub(quote, sql)


def generate(yaml_dir: Path | None = None, overlay_path: Path | None = None) -> dict[str, Any]:
    yaml_dir = Path(yaml_dir or settings.CUBE_YAML_DIR)
    overlay = yaml.safe_load(Path(overlay_path or settings.OVERLAY_PATH).read_text(encoding="utf-8")) or {}
    raw, hashes = _load_cubes(yaml_dir)
    labels = overlay.get("labels", {})
    synonyms = overlay.get("synonyms", {})
    hidden = set(overlay.get("hidden", []))

    cubes: dict[str, Any] = {}
    missing, unresolved = [], []
    for name in overlay["in_scope"]:
        if name not in raw:
            missing.append(name)
            continue
        cube = _resolve_extends(name, raw)
        extra = overlay.get("extra_members", {}).get(name, {})
        if cube.get("sql_table"):
            source_sql = f"SELECT * FROM {cube['sql_table']}"
        else:
            source_sql = str(cube["sql"])
        dims = [dict(d, origin="yaml") for d in cube.get("dimensions", [])]
        dims += [dict(d, origin="overlay") for d in extra.get("dimensions", [])]
        measures = [dict(m, origin="yaml") for m in cube.get("measures", [])]
        by_name = {m["name"]: m for m in dims + measures}

        members: dict[str, Any] = {}
        for kind, items in (("dimension", dims), ("measure", measures)):
            for item in items:
                key = f"{name}.{item['name']}"
                entry = {
                    "kind": kind,
                    "type": item.get("type"),
                    "title": labels.get(key, item.get("title") or item["name"]),
                    "description": " ".join(str(item.get("description", "")).split()),
                    "synonyms": synonyms.get(key, []),
                    "public": item.get("public", True) is not False and key not in hidden,
                    "origin": item["origin"],
                    "sql": None,
                    "resolved": True,
                    "issue": None,
                }
                if item.get("known_values"):
                    entry["known_values"] = item["known_values"]
                if item.get("note"):
                    entry["note"] = item["note"]
                valid_types = DIMENSION_TYPES if kind == "dimension" else MEASURE_TYPES
                try:
                    if entry["type"] not in valid_types:
                        raise ValueError(f"{kind} type {entry['type']!r} not supported")
                    entry["sql"] = _member_sql(name, item, by_name)
                except ValueError as exc:
                    entry["resolved"] = False
                    entry["issue"] = str(exc)
                    unresolved.append({"member": key, "issue": str(exc)})
                members[key] = entry

        joins = {
            j["name"]: {"relationship": j["relationship"], "on": _join_on(name, j["sql"])}
            for j in cube.get("joins", [])
        }
        cubes[name] = {
            "title": cube.get("title", name),
            "description": " ".join(str(cube.get("description", "")).split()),
            "source_sql": translate_sql(source_sql),
            "joins": joins,
            "members": members,
        }

    body = {
        "sources": {"yaml_files": hashes},
        "cubes": cubes,
        "missing_cubes": missing,
        "unresolved": unresolved,
    }
    digest = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()[:12]
    return {"version": digest, **body}


# ---------------------------------------------------------------- schema check

def validate(catalogue: dict[str, Any]) -> list[str]:
    """Structural schema check. Returns a list of problems (empty means valid)."""
    problems = []
    for key in ("version", "cubes", "missing_cubes", "unresolved"):
        if key not in catalogue:
            problems.append(f"missing top-level key {key}")
    reported = {u["member"] for u in catalogue.get("unresolved", [])}
    for cube_name, cube in catalogue.get("cubes", {}).items():
        for key in ("title", "description", "source_sql", "joins", "members"):
            if key not in cube:
                problems.append(f"{cube_name}: missing {key}")
        for target, join in cube.get("joins", {}).items():
            if target not in catalogue["cubes"]:
                problems.append(f"{cube_name}: join to {target}, which is not in the catalogue")
            if join.get("relationship") not in ("many_to_one", "one_to_one", "one_to_many"):
                problems.append(f"{cube_name}: join to {target} has bad relationship")
        for key, member in cube.get("members", {}).items():
            if not key.startswith(cube_name + "."):
                problems.append(f"{key}: not named after its cube")
            for field in ("kind", "type", "title", "description", "synonyms", "public", "resolved"):
                if field not in member:
                    problems.append(f"{key}: missing {field}")
            if member.get("resolved") and member.get("sql") is None:
                problems.append(f"{key}: resolved but has no sql")
            if not member.get("resolved") and key not in reported:
                problems.append(f"{key}: unresolved but not reported")
    return problems


def probe(catalogue: dict[str, Any], run_sql) -> list[dict[str, str]]:
    """Run every resolved member against the reporting DB (LIMIT 0).

    `run_sql(sql)` executes a statement. Members that fail are returned so the
    caller can report them; generation stays static so it needs no database.
    """
    failures = []
    for cube_name, cube in catalogue["cubes"].items():
        for key, member in cube["members"].items():
            if not member["resolved"] or not member["sql"]:
                continue
            sql = f'SELECT {member["sql"]} FROM ({cube["source_sql"]}) AS src LIMIT 0'
            try:
                run_sql(sql)
            except Exception as exc:  # noqa: BLE001 - every failure is reported
                failures.append({"member": key, "issue": str(exc).splitlines()[0]})
    return failures


# ---------------------------------------------------------------- loading and views

def load(path: Path | None = None) -> dict[str, Any]:
    return json.loads(Path(path or settings.CATALOGUE_PATH).read_text(encoding="utf-8"))


def model_view(catalogue: dict[str, Any]) -> dict[str, Any]:
    """What the query model is allowed to see: public, resolved names and their meanings. No SQL."""
    cubes = []
    for cube_name, cube in catalogue["cubes"].items():
        members = []
        for key, member in cube["members"].items():
            if not (member["public"] and member["resolved"]):
                continue
            view = {
                "name": key,
                "kind": member["kind"],
                "type": member["type"],
                "title": member["title"],
                "description": member["description"],
                "synonyms": member["synonyms"],
            }
            if "known_values" in member:
                view["known_values"] = member["known_values"]
            members.append(view)
        cubes.append({
            "name": cube_name,
            "title": cube["title"],
            "description": cube["description"],
            "joins_to": sorted(cube["joins"]),
            "members": members,
        })
    return {"version": catalogue["version"], "cubes": cubes}


def label(catalogue: dict[str, Any], member: str) -> str:
    cube_name = member.split(".", 1)[0]
    return catalogue["cubes"][cube_name]["members"][member]["title"]


# ---------------------------------------------------------------- CLI

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m a7chat.catalogue")
    sub = parser.add_subparsers(dest="command", required=True)
    gen = sub.add_parser("generate", help="regenerate the catalogue from the Cube YAMLs")
    gen.add_argument("--yaml-dir", type=Path, default=settings.CUBE_YAML_DIR)
    gen.add_argument("--overlay", type=Path, default=settings.OVERLAY_PATH)
    gen.add_argument("--out", type=Path, default=settings.CATALOGUE_PATH)
    chk = sub.add_parser("check", help="schema check, and probe each member on the reporting DB")
    chk.add_argument("--catalogue", type=Path, default=settings.CATALOGUE_PATH)
    chk.add_argument("--dsn", default=settings.DATABASE_URL)
    args = parser.parse_args(argv)

    if args.command == "generate":
        catalogue = generate(args.yaml_dir, args.overlay)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(catalogue, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"catalogue {catalogue['version']}: {len(catalogue['cubes'])} cubes -> {args.out}")
        for name in catalogue["missing_cubes"]:
            print(f"  missing cube (no YAML): {name}")
        for item in catalogue["unresolved"]:
            print(f"  unresolved: {item['member']}: {item['issue']}")
        return 0

    import psycopg

    catalogue = load(args.catalogue)
    problems = validate(catalogue)
    with psycopg.connect(args.dsn) as conn:
        failures = probe(catalogue, lambda sql: conn.execute(sql))
    for problem in problems:
        print(f"schema: {problem}")
    for failure in failures:
        print(f"probe: {failure['member']}: {failure['issue']}")
    print("catalogue check:", "FAIL" if problems or failures else "PASS")
    return 1 if problems or failures else 0


if __name__ == "__main__":
    sys.exit(main())
