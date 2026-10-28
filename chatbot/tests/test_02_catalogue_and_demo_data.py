"""Ticket 02: full catalogue and demo dataset."""
import json
import re
import shutil

import psycopg
import pytest
import yaml

from a7chat import catalogue as cat
from a7chat import settings
from a7chat.expectations import compare

APPROVED = yaml.safe_load(settings.APPROVED_QUESTIONS_PATH.read_text(encoding="utf-8"))
CIS_TABLES = ["pu_account_pay", "pu_account", "icpcashm", "icphdrh", "pu_balance_hist", "pu_ar_descript",
              "glsvdata", "csrcalld", "csrctypr", "csrstatc"]


def test_committed_catalogue_is_what_the_yaml_generates():
    assert cat.load() == cat.generate(), "run: python -m a7chat.catalogue generate"


def test_catalogue_lists_every_in_scope_cube_and_member_and_passes_the_schema_check():
    catalogue = cat.load()
    assert cat.validate(catalogue) == []
    assert set(catalogue["cubes"]) == {"account", "accountBalance", "cashBatchData", "cashDetail",
                                       "callTypeAnalysis", "csrActivityAnalysis"}
    assert catalogue["missing_cubes"] == ["keyAccount"]
    for cube_name, cube in catalogue["cubes"].items():
        yaml_names = set()
        for path in settings.CUBE_YAML_DIR.glob("*.yml"):
            for c in yaml.safe_load(path.read_text(encoding="utf-8"))["cubes"]:
                if c["name"] == cube_name:
                    yaml_names = {m["name"] for m in c.get("dimensions", []) + c.get("measures", [])}
        assert yaml_names <= {k.split(".", 1)[1] for k in cube["members"]}
        for member in cube["members"].values():
            assert {"title", "description", "synonyms"} <= set(member)
    assert catalogue["cubes"]["accountBalance"]["joins"]["account"]["relationship"] == "many_to_one"
    assert "arrears" in catalogue["cubes"]["accountBalance"]["members"]["accountBalance.overdueBalance"]["synonyms"]


def test_unresolved_members_are_reported_not_dropped():
    catalogue = cat.load()
    member = catalogue["cubes"]["callTypeAnalysis"]["members"]["callTypeAnalysis.accountName"]
    assert member["resolved"] is False and "another cube" in member["issue"]
    assert {"member": "callTypeAnalysis.accountName", "issue": member["issue"]} in catalogue["unresolved"]


def test_every_resolved_member_runs_on_the_reporting_database(database):
    with psycopg.connect(database.reader_url) as conn:
        assert cat.probe(cat.load(), lambda sql: conn.execute(sql)) == []


def test_changing_a_yaml_field_and_regenerating_changes_the_catalogue(tmp_path):
    yaml_dir = tmp_path / "cubes"
    shutil.copytree(settings.CUBE_YAML_DIR, yaml_dir)
    before = cat.generate(yaml_dir)
    path = yaml_dir / "AccountBalance.yml"
    path.write_text(path.read_text(encoding="utf-8").replace("title: Overdue Balance", "title: Past Due Amount"), encoding="utf-8")
    after = cat.generate(yaml_dir)

    assert after["version"] != before["version"]
    assert after["cubes"]["accountBalance"]["members"]["accountBalance.overdueBalance"]["title"] == "Past Due Amount"


@pytest.mark.parametrize("case", APPROVED["cases"], ids=[c["id"] for c in APPROVED["cases"]])
def test_each_approved_question_returns_its_expected_result(make_chat, case):
    chat = make_chat()
    for turn in case["turns"]:
        answer = chat.ask(turn["question"])
        assert compare(turn["expect"], answer) == [], turn["question"]


def test_no_user_facing_text_shows_a_raw_cis_table_name(make_chat):
    chat = make_chat()
    for case in APPROVED["cases"]:
        for turn in case["turns"]:
            chat.ask(turn["question"], conversation_id=case["id"])
    visible = []
    for answer in chat.responses:
        visible += [answer.get("sentence"), answer.get("note"), answer.get("text")]
        visible += [c["label"] for c in answer.get("columns", [])] + answer.get("suggestions", [])
    text = " ".join(t for t in visible if t)
    for table in CIS_TABLES:
        assert not re.search(rf"\b{table}\b", text, re.IGNORECASE), table
    assert chat.client.get("/api/suggestions").json()["suggestions"]


def test_dataset_provenance_is_documented():
    provenance = (settings.CHATBOT_DIR / "PROVENANCE.md").read_text(encoding="utf-8")
    assert "synthetic" in provenance.lower() and "no row is live customer data" in provenance.lower()
    assert "No row is live customer data" in (settings.CHATBOT_DIR / "db" / "seed.sql").read_text(encoding="utf-8")
