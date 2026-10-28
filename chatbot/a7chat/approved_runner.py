"""Approved-question runner (FR-9): every approved case against the query model and the demo dataset.

    python -m a7chat.approved_runner --model claude        # the real query model (needs ANTHROPIC_API_KEY)
    python -m a7chat.approved_runner --model recorded      # replays recorded queries: checks engine + data only
    python -m a7chat.approved_runner --model claude --checkpoint "13 Nov engine checkpoint"

Prints PASS or FAIL per question, keeps each run under runs/ (results plus the
run's request log, for the privacy review), and lists regressions against the
previous run of the same model. --checkpoint also appends the result and the
engine decision to docs/checkpoints.md.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from . import catalogue as cat
from . import settings
from .conversation import ConversationStore
from .executor import Executor
from .expectations import compare
from .orchestrator import Orchestrator
from .query_model import make_query_model, suggestions_from_config
from .request_log import RequestLog


def run(*, model_name: str, dsn: str, approved_path: Path, runs_dir: Path) -> dict[str, Any]:
    approved = yaml.safe_load(approved_path.read_text(encoding="utf-8"))
    catalogue = cat.load()
    query_model = make_query_model(model_name, approved_path)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    runs_dir.mkdir(parents=True, exist_ok=True)
    log = RequestLog(runs_dir / f"{stamp}-{model_name}-requests.jsonl")
    orchestrator = Orchestrator(
        catalogue=catalogue, query_model=query_model, executor=Executor(dsn, settings.STATEMENT_TIMEOUT_MS),
        store=ConversationStore(), log=log, fixed_reply=settings.FIXED_REPLY_PATH.read_text(encoding="utf-8").strip(),
        suggestions=suggestions_from_config(approved_path), row_limit=settings.ROW_LIMIT)

    results = []
    for case in approved["cases"]:
        conversation_id = f"{stamp}-{case['id']}"
        for number, turn in enumerate(case["turns"], start=1):
            before = len(log.lines())
            try:
                answer = orchestrator.handle(conversation_id, turn["question"])
                problems = compare(turn.get("expect", {}), answer)
            except Exception as exc:  # noqa: BLE001 - a crash is a failed question, not a failed run
                problems = [f"error: {exc}"]
            if turn.get("expect", {}).get("kind") == "fixed_reply":
                problems += ["SQL ran for a fixed-reply case" for line in log.lines()[before:] if line["sql"]]
            key = case["id"] if len(case["turns"]) == 1 else f"{case['id']}#{number}"
            results.append({"id": key, "question": turn["question"], "passed": not problems, "problems": problems})
            print(f"{'PASS' if not problems else 'FAIL'}  {key:<22} {turn['question']}")
            for problem in problems:
                print(f"      {problem}")

    previous = sorted(p for p in runs_dir.glob(f"*-{model_name}.json"))
    record = {
        "stamp": stamp,
        "model": model_name if model_name != "claude" else f"claude ({settings.CLAUDE_MODEL})",
        "catalogue_version": catalogue["version"],
        "approved_version": approved.get("version"),
        "passed": sum(r["passed"] for r in results),
        "total": len(results),
        "results": results,
        "regressions": [],
    }
    if previous:
        earlier = {r["id"]: r["passed"] for r in json.loads(previous[-1].read_text(encoding="utf-8"))["results"]}
        record["regressions"] = [r["id"] for r in results if earlier.get(r["id"]) and not r["passed"]]
    (runs_dir / f"{stamp}-{model_name}.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(f"\n{record['passed']}/{record['total']} passed  (run {stamp}, {record['model']})")
    if previous:
        print("regressions since the previous run: " + (", ".join(record["regressions"]) or "none"))
    return record


def record_checkpoint(record: dict[str, Any], label: str, path: Path) -> None:
    all_pass = record["passed"] == record["total"]
    decision = ("engine stays the primary path" if all_pass else
                "switch to the fallback: raw SQL from the model behind a validator (SELECT only, catalogue tables only, limit and timeout)")
    failed = [r["id"] for r in record["results"] if not r["passed"]]
    entry = (f"\n## {label}\n\n"
             f"- Run: {record['stamp']}, model {record['model']}, catalogue {record['catalogue_version']}, "
             f"question set {record['approved_version']}\n"
             f"- Result: {record['passed']}/{record['total']} passed" + (f"; failed: {', '.join(failed)}" if failed else "") + "\n"
             f"- Decision rule outcome: {decision}\n")
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# Engine checkpoints\n\nRecorded by `python -m a7chat.approved_runner --checkpoint <label>`.\n", encoding="utf-8")
    with path.open("a", encoding="utf-8") as f:
        f.write(entry)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m a7chat.approved_runner")
    parser.add_argument("--model", choices=["claude", "recorded"], default="claude")
    parser.add_argument("--dsn", default=settings.DATABASE_URL)
    parser.add_argument("--approved", type=Path, default=settings.APPROVED_QUESTIONS_PATH)
    parser.add_argument("--runs-dir", type=Path, default=settings.RUNS_DIR)
    parser.add_argument("--checkpoint", metavar="LABEL", help="also record this run as a checkpoint in docs/checkpoints.md")
    parser.add_argument("--checkpoints-file", type=Path, default=settings.CHATBOT_DIR / "docs" / "checkpoints.md")
    args = parser.parse_args(argv)

    record = run(model_name=args.model, dsn=args.dsn, approved_path=args.approved, runs_dir=args.runs_dir)
    if args.checkpoint:
        record_checkpoint(record, args.checkpoint, args.checkpoints_file)
        print(f"checkpoint recorded in {args.checkpoints_file}")
    return 0 if record["passed"] == record["total"] else 1


if __name__ == "__main__":
    sys.exit(main())
