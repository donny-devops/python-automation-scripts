from datetime import date, timedelta

from to_dojo import (
    DojoState,
    add_task_record,
    complete_task_by_id,
    current_streak,
    get_rank,
    load_state,
    main,
    record_activity,
    save_state,
    streak_multiplier,
)


def test_rank_thresholds():
    assert get_rank(0)[0] == "White Belt"
    assert get_rank(100)[0] == "Yellow Belt"
    assert get_rank(4200)[0] == "Black Belt"
    assert get_rank(6000)[0] == "Grand Master"


def test_streak_multiplier_tiers():
    assert streak_multiplier(1) == 1.0
    assert streak_multiplier(3) == 1.25
    assert streak_multiplier(7) == 1.5
    assert streak_multiplier(14) == 2.0
    assert streak_multiplier(30) == 3.0


def test_opening_app_does_not_inflate_streak():
    state = DojoState(streak=4, last_active_date=str(date.today() - timedelta(days=1)))
    assert current_streak(state) == 4
    state_missed = DojoState(streak=4, last_active_date=str(date.today() - timedelta(days=3)))
    assert current_streak(state_missed) == 0


def test_record_activity_resets_after_gap():
    state = DojoState(streak=9, last_active_date=str(date.today() - timedelta(days=3)))
    assert record_activity(state) == 1
    assert record_activity(state) == 1  # same day


def test_complete_task_awards_dp_and_achievement(tmp_path):
    state = DojoState()
    task = add_task_record(state, "First kata", priority="critical")
    result = complete_task_by_id(state, task.id)
    assert result is not None
    _task, earned, _promoted, badges = result
    assert earned == 40
    assert state.total_completed == 1
    assert "first_blood" in badges
    path = tmp_path / "dojo.json"
    save_state(state, path)
    loaded = load_state(path)
    assert loaded.total_dp == 40
    assert loaded.tasks[0]["completed_at"]


def test_corrupt_state_is_quarantined(tmp_path):
    path = tmp_path / "dojo.json"
    path.write_text("{not-json", encoding="utf-8")
    state = load_state(path)
    assert state.total_dp == 0
    assert path.with_suffix(".json.corrupt").exists()


def test_invalid_priority_and_due_date_rejected():
    state = DojoState()
    try:
        add_task_record(state, "x", priority="urgent")
        assert False, "expected ValueError"
    except ValueError:
        pass
    try:
        add_task_record(state, "x", due_date="14-09-2026")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_cli_add_and_complete(tmp_path):
    data = tmp_path / "dojo.json"
    assert main(["--data-file", str(data), "add", "Ship tests", "--priority", "high"]) == 0
    assert main(["--data-file", str(data), "complete", "1"]) == 0
    loaded = load_state(data)
    assert loaded.total_completed == 1
    assert loaded.total_dp == 20
    assert main(["--data-file", str(data), "list"]) == 0
    assert main(["--data-file", str(data), "stats"]) == 0
