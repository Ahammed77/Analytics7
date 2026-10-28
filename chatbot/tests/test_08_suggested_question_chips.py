"""Ticket 08: suggested-question chips come from the approved set in configuration."""
import yaml

from a7chat import settings

APPROVED = yaml.safe_load(settings.APPROVED_QUESTIONS_PATH.read_text(encoding="utf-8"))


def test_chips_show_when_the_chat_opens(make_chat):
    chat = make_chat()
    page = chat.client.get("/")
    assert page.status_code == 200 and 'id="chips"' in page.text and "/api/suggestions" in page.text
    assert len(chat.client.get("/api/suggestions").json()["suggestions"]) >= 5


def test_every_chip_is_in_the_approved_set(make_chat):
    chips = make_chat().client.get("/api/suggestions").json()["suggestions"]
    approved = {turn["question"] for case in APPROVED["cases"] for turn in case["turns"]}
    assert set(chips) <= approved
    assert chips == [c["turns"][0]["question"] for c in APPROVED["cases"] if c.get("suggest")]


def test_clicking_a_chip_and_typing_its_text_give_the_same_result(make_chat):
    chat = make_chat()
    page = chat.client.get("/").text
    # The page sends a chip's own text through the same send() the input box uses.
    assert 'chip.addEventListener("click", () => send(q))' in page
    assert "send(text);" in page
    for chip in chat.client.get("/api/suggestions").json()["suggestions"]:
        clicked = chat.ask(chip, conversation_id="clicked-" + chip)
        typed = chat.ask(chip, conversation_id="typed-" + chip)
        assert {k: v for k, v in clicked.items() if k != "conversation_id"} == {k: v for k, v in typed.items() if k != "conversation_id"}
        assert clicked["kind"] == "answer"


def test_changing_the_configuration_changes_the_chips_without_a_code_change(make_chat, tmp_path):
    config = yaml.safe_load(settings.APPROVED_QUESTIONS_PATH.read_text(encoding="utf-8"))
    for case in config["cases"]:
        case["suggest"] = case["id"] in ("CALLS-BY-MONTH", "U1-250")
    path = tmp_path / "approved_questions.yml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")

    chips = make_chat(approved_questions_path=path).client.get("/api/suggestions").json()["suggestions"]
    assert chips == ["List all customers with a past due balance greater than $250",
                     "How many calls were logged each month in 2025?"]
