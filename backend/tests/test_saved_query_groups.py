import json

from app.services.saved_query_groups import load_saved_query_groups, save_saved_query_groups


def test_saved_query_groups_survive_separate_load(tmp_path):
    store_path = tmp_path / "saved_query_groups.json"

    saved = save_saved_query_groups(["Employee", "Operations"], store_path)

    assert saved == ["Employee", "Operations"]
    assert load_saved_query_groups(store_path) == saved
    assert json.loads(store_path.read_text(encoding="utf-8")) == saved


def test_saved_query_groups_are_trimmed_and_deduplicated(tmp_path):
    store_path = tmp_path / "saved_query_groups.json"

    saved = save_saved_query_groups([" Employee ", "employee", "", "Finance"], store_path)

    assert saved == ["Employee", "Finance"]


def test_default_store_falls_back_to_example_groups(tmp_path, monkeypatch):
    store_path = tmp_path / "saved_query_groups.json"
    store_path.with_name("saved_query_groups.example.json").write_text(
        json.dumps(["Employee", "Insights"]),
        encoding="utf-8",
    )
    monkeypatch.setattr("app.services.saved_query_groups.saved_query_groups_path", lambda: store_path)

    assert load_saved_query_groups() == ["Employee", "Insights"]
