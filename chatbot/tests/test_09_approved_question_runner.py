"""Ticket 09: one command runs every approved question and reports pass or fail per question."""
import json
from types import SimpleNamespace

import yaml

from a7chat import approved_runner, settings, structured_query
from a7chat import catalogue as cat
from a7chat.query_model import INSTRUCTIONS, ClaudeQueryModel, build_prompt, render_prompt

APPROVED = yaml.safe_load(settings.APPROVED_QUESTIONS_PATH.read_text(encoding="utf-8"))
TURN_COUNT = sum(len(c["turns"]) for c in APPROVED["cases"])


def run(database, tmp_path, approved_path=None):
    return approved_runner.main(["--model", "recorded", "--dsn", database.reader_url, "--runs-dir", str(tmp_path / "runs"),
                                 "--approved", str(approved_path or settings.APPROVED_QUESTIONS_PATH),
                                 "--checkpoint", "test checkpoint", "--checkpoints-file", str(tmp_path / "checkpoints.md")])


def test_one_command_runs_every_case_and_prints_pass_or_fail_per_question(database, tmp_path, capsys):
    code = run(database, tmp_path)
    printed = capsys.readouterr().out

    assert code == 0
    assert printed.count("PASS  ") == TURN_COUNT and "FAIL  " not in printed
    for case in APPROVED["cases"]:
        assert case["id"] in printed
    assert f"{TURN_COUNT}/{TURN_COUNT} passed" in printed


def test_the_run_covers_the_parameter_follow_up_refusal_and_guardrail_cases():
    ids = {c["id"] for c in APPROVED["cases"]}
    assert {"U1", "U1-250", "FOLLOW-UPS", "GUARD-DELETE", "GUARD-WEATHER", "GUARD-OVERRIDE", "GUARD-UNANSWERABLE"} <= ids
    assert all("expect" in turn for c in APPROVED["cases"] for turn in c["turns"])


def test_results_are_kept_per_run_so_regressions_show(database, tmp_path, capsys):
    run(database, tmp_path)
    broken = yaml.safe_load(settings.APPROVED_QUESTIONS_PATH.read_text(encoding="utf-8"))
    broken["cases"][1]["turns"][0]["expect"]["rows"].pop()   # U1-250 now expects 3 rows: it fails
    path = tmp_path / "broken.yml"
    path.write_text(yaml.safe_dump(broken), encoding="utf-8")
    code = run(database, tmp_path, path)
    printed = capsys.readouterr().out

    assert code == 1
    assert "regressions since the previous run: U1-250" in printed
    runs = sorted((tmp_path / "runs").glob("*-recorded.json"))
    latest = json.loads(runs[-1].read_text())
    assert len(runs) == 2 and latest["passed"] == TURN_COUNT - 1 and latest["regressions"] == ["U1-250"]
    assert len(list((tmp_path / "runs").glob("*-recorded-requests.jsonl"))) == 2


def test_the_checkpoint_result_is_recorded(database, tmp_path):
    run(database, tmp_path)
    text = (tmp_path / "checkpoints.md").read_text(encoding="utf-8")
    assert "## test checkpoint" in text
    assert f"{TURN_COUNT}/{TURN_COUNT} passed" in text and "engine stays the primary path" in text


class FakeClaude:
    """Stands in for anthropic.Anthropic() so the real model's request and parsing are checked offline."""

    def __init__(self, response):
        self.response = response
        self.calls = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


def test_the_real_query_model_sends_only_the_checked_prompt_and_returns_its_structured_query():
    u1 = APPROVED["cases"][0]["turns"][0]
    output = {"type": "query", "reason": None, "cube": "accountBalance", "measures": ["accountBalance.overdueBalance"],
              "dimensions": ["account.accountNumber", "account.name"], "timeDimension": None, "order": [], "limit": None,
              "filters": [{"member": "accountBalance.overdueBalance", "operator": "gt", "values": ["100"]}]}
    client = FakeClaude(SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=json.dumps(output))]))
    prompt = build_prompt(cat.model_view(cat.load()), u1["question"], [])

    parsed = structured_query.from_model_output(ClaudeQueryModel("claude-opus-5-5", client).ask(prompt))

    [call] = client.calls
    assert call["messages"] == [{"role": "user", "content": render_prompt(prompt)}]
    assert call["system"] == INSTRUCTIONS
    assert call["output_config"]["format"] == {"type": "json_schema", "schema": structured_query.JSON_SCHEMA}
    assert parsed.filters[0].values == ("100",)


def test_a_refusal_from_the_real_model_becomes_off_topic():
    client = FakeClaude(SimpleNamespace(stop_reason="refusal", content=[]))
    prompt = build_prompt(cat.model_view(cat.load()), "x", [])
    assert ClaudeQueryModel("claude-opus-5-5", client).ask(prompt)["type"] == "off_topic"
