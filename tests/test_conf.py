from imapbackup import conf


def test_bool_opt():
    assert conf.bool_opt({"a": True}, "a") is True
    assert conf.bool_opt({"a": False}, "a") is False
    assert conf.bool_opt({"a": "on"}, "a") is True
    assert conf.bool_opt({"a": "YES"}, "a") is True
    assert conf.bool_opt({"a": "1"}, "a") is True
    assert conf.bool_opt({"a": "off"}, "a") is False
    assert conf.bool_opt({"a": "no"}, "a") is False
    assert conf.bool_opt({"a": "0"}, "a") is False
    assert conf.bool_opt({"a": "invalid"}, "a", default=True) is True
    assert conf.bool_opt({"b": "on"}, "a", default=False) is False


def test_find():
    configs = [{"name": "A", "val": 1}, {"name": "B", "val": 2}]
    assert conf.find(configs, "name", "A") == {"name": "A", "val": 1}
    assert conf.find(configs, "name", "b") == {"name": "B", "val": 2}  # Case insensitive
    assert conf.find(configs, "name", "C") is None
    assert conf.find(configs, "name", "C", default={"name": "C"}) == {"name": "C"}


def test_load(tmp_path):
    yaml_file = tmp_path / "test.yaml"
    yaml_file.write_text("job1:\n  param: 1\njob2:\n  param: 2\n")
    loaded = conf.load(yaml_file)
    assert len(loaded) == 2
    assert loaded[0]["name"] == "job1"
    assert loaded[0]["param"] == 1
    assert loaded[1]["name"] == "job2"
    assert loaded[1]["param"] == 2
