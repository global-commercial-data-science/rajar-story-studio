from app.backend import cache


def test_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    key = cache.make_key("angles", release=202602, facts="abc")
    assert cache.get(key) is None
    cache.put(key, {"angles": [1, 2]})
    assert cache.get(key)["value"] == {"angles": [1, 2]}
    assert cache.get(key)["cached_at"]


def test_key_changes_with_inputs():
    a = cache.make_key("angles", release=202602, facts="abc", query="")
    assert a == cache.make_key("angles", query="", facts="abc", release=202602)
    assert a != cache.make_key("angles", release=202602, facts="abd", query="")
    assert a != cache.make_key("draft", release=202602, facts="abc", query="")


def test_corrupt_file_is_a_miss(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    (tmp_path / "angles_x.json").write_text("{not json")
    assert cache.get("angles_x") is None
