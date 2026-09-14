import json

from granola_engineer import (
    GranolaParseError,
    collect_action_items,
    extract_from_notes,
    infer_priority,
    load_export,
    main,
    parse_export,
    send_to_dojo,
    write_action_items,
)
from to_dojo import load_state


def _write(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_parse_list_and_wrapper_and_single_shapes():
    meeting = {"title": "Planning", "action_items": ["TODO: ship it"]}
    assert len(parse_export([meeting])) == 1
    assert len(parse_export({"meetings": [meeting]})) == 1
    assert len(parse_export(meeting)) == 1


def test_parse_rejects_non_object_root():
    try:
        parse_export("nope")
        assert False, "expected GranolaParseError"
    except GranolaParseError:
        pass


def test_explicit_action_objects_with_owner_and_due():
    meetings = parse_export(
        {
            "id": "m1",
            "title": "Roadmap",
            "action_items": [
                {"text": "Draft spec", "owner": "sam", "due": "2026-10-01", "priority": "high"},
            ],
        }
    )
    item = meetings[0].action_items[0]
    assert item.text == "Draft spec"
    assert item.assignee == "sam"
    assert item.due_date == "2026-10-01"
    assert item.priority == "high"
    assert item.meeting_id == "m1"


def test_action_extraction_from_notes_markdown():
    notes = (
        "# Notes\n"
        "Some discussion happened.\n"
        "- [ ] Follow up with vendor @alex by 2026-09-30\n"
        "TODO: write the migration\n"
        "Just a normal sentence, not an action.\n"
        "* [x] Already done thing\n"
    )
    meeting = parse_export({"title": "Sync", "notes": notes})[0]
    texts = [i.text for i in meeting.action_items]
    assert "Follow up with vendor" in " ".join(texts)
    assert "write the migration" in texts
    assert any("Already done thing" == t for t in texts)
    assert not any("normal sentence" in t for t in texts)
    follow = next(i for i in meeting.action_items if i.text.startswith("Follow up"))
    assert follow.assignee == "alex"
    assert follow.due_date == "2026-09-30"


def test_extract_from_notes_dedupes(tmp_path):
    from granola_engineer import Meeting

    notes = "TODO: same task\n- [ ] same task\n"
    items = extract_from_notes(notes, Meeting(title="m"))
    assert len(items) == 1


def test_priority_inference_keywords():
    assert infer_priority("this is URGENT, do asap") == "critical"
    assert infer_priority("important cleanup") == "high"
    assert infer_priority("nice to have polish") == "low"
    assert infer_priority("routine update") == "normal"
    assert infer_priority("routine update", explicit="critical") == "critical"


def test_load_export_missing_and_bad_json(tmp_path):
    missing = tmp_path / "nope.json"
    try:
        load_export(missing)
        assert False, "expected GranolaParseError"
    except GranolaParseError:
        pass
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    try:
        load_export(bad)
        assert False, "expected GranolaParseError"
    except GranolaParseError:
        pass


def test_write_action_items_is_atomic_and_valid(tmp_path):
    meetings = parse_export({"title": "m", "action_items": ["TODO: alpha", "TODO: beta"]})
    items = collect_action_items(meetings)
    out = tmp_path / "nested" / "items.json"
    write_action_items(items, out)
    assert out.is_file()
    assert not (out.with_name(out.name + ".tmp")).exists()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert [d["text"] for d in data] == ["alpha", "beta"]


def test_send_to_dojo_creates_tasks_and_dedupes(tmp_path):
    export = _write(
        tmp_path / "export.json",
        {
            "title": "Kickoff",
            "action_items": [
                {"text": "Set up CI", "priority": "high"},
                "TODO: urgent hotfix asap",
            ],
        },
    )
    data_file = tmp_path / "dojo.json"
    meetings = load_export(export)
    items = collect_action_items(meetings)

    created = send_to_dojo(items, data_file)
    assert set(created) == {"Set up CI", "urgent hotfix asap"}
    state = load_state(data_file)
    assert len(state.tasks) == 2
    titles = {t["title"]: t for t in state.tasks}
    assert titles["Set up CI"]["priority"] == "high"
    assert titles["urgent hotfix asap"]["priority"] == "critical"
    assert "granola" in titles["Set up CI"]["tags"]

    again = send_to_dojo(items, data_file)
    assert again == []
    assert len(load_state(data_file).tasks) == 2


def test_send_to_dojo_forced_priority(tmp_path):
    export = _write(tmp_path / "e.json", {"title": "m", "action_items": ["TODO: something"]})
    data_file = tmp_path / "dojo.json"
    items = collect_action_items(load_export(export))
    send_to_dojo(items, data_file, default_priority="low")
    state = load_state(data_file)
    assert state.tasks[0]["priority"] == "low"


def test_cli_list_export_and_to_dojo(tmp_path):
    export = _write(
        tmp_path / "export.json",
        {"meetings": [{"title": "m", "action_items": ["TODO: do a thing"]}]},
    )
    assert main(["list", str(export)]) == 0

    out = tmp_path / "items.json"
    assert main(["export", str(export), "--out", str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))[0]["text"] == "do a thing"

    data_file = tmp_path / "dojo.json"
    assert main(["to-dojo", str(export), "--data-file", str(data_file)]) == 0
    assert load_state(data_file).tasks[0]["title"] == "do a thing"

    assert main(["to-dojo", str(export), "--data-file", str(data_file), "--dry-run"]) == 0


def test_cli_missing_file_returns_1(tmp_path):
    assert main(["list", str(tmp_path / "missing.json")]) == 1
